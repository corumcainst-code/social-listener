"""Main scanner — orchestrates platform scanners for a country.

Adds Apify safety controls:
- SCAN_MAX_EVENTS limits how many events are scanned in one run.
- SCAN_PLATFORMS limits which scanners run, e.g. "twitter" or "twitter,facebook".
- SCANNER_TIMEOUT_SECONDS prevents one slow platform from hanging the whole Actor.

Adds Darwin quality controls:
- past events are filtered before scanning
- priority events such as HYROX are merged from config/priority_events.json
- raw signals are qualified/scored before Slack posting
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.models import CountryConfig, Event, ScanState
from src.platforms.base import Scanner
from src.platforms.reddit import RedditScanner
from src.platforms.twitter import TwitterScanner
from src.platforms.web_search import WebSearchScanner
from src.processor import SignalProcessor
from src.qualifier import filter_future_events
from src.slack_bot import SlackPoster

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
WEB_PLATFORMS = ("facebook", "instagram", "discord", "tiktok", "telegram")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        value = int(str(raw).strip())
        return value if value > 0 else default
    except ValueError:
        logger.warning("Invalid %s=%r — using default %s", name, raw, default)
        return default


def _enabled_platforms() -> set[str] | None:
    raw = os.getenv("SCAN_PLATFORMS", "").strip()
    if not raw:
        return None
    platforms = {p.strip().lower() for p in raw.replace(";", ",").split(",") if p.strip()}
    return platforms or None


def _platform_enabled(name: str, enabled: set[str] | None) -> bool:
    if enabled is None:
        return True
    if name == "twitter":
        return "twitter" in enabled or "x" in enabled
    return name.lower() in enabled


def load_config(country: str) -> CountryConfig:
    config_path = CONFIG_DIR / f"{country}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path) as f:
        data = json.load(f)
    return CountryConfig(**data)


def load_priority_events(country: str) -> list[Event]:
    """Load optional priority events, such as HYROX season tracking."""
    path = CONFIG_DIR / "priority_events.json"
    if not path.exists():
        return []

    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Could not load priority events: %s", exc)
        return []

    raw_events = data.get(country, [])
    events: list[Event] = []

    for raw_event in raw_events:
        try:
            events.append(Event(**raw_event))
        except Exception as exc:
            logger.warning("Skipping invalid priority event %r: %s", raw_event, exc)

    return events


def merge_priority_events(config: CountryConfig) -> CountryConfig:
    """Append country-specific priority events unless already present."""
    priority_events = load_priority_events(config.country)
    if not priority_events:
        return config

    existing_names = {event.name.lower().strip() for event in config.events}

    # Put priority events first so small Apify test runs still cover HYROX.
    merged: list[Event] = []
    for event in priority_events:
        if event.name.lower().strip() not in existing_names:
            merged.append(event)

    merged.extend(config.events)

    config.events = merged
    logger.info("Loaded %s priority events for %s", len(priority_events), config.country)
    return config


def load_state(country: str) -> ScanState:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / f"{country}.json"
    if state_path.exists():
        with open(state_path) as f:
            return ScanState(**json.load(f))
    return ScanState()


def save_state(country: str, state: ScanState):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / f"{country}.json"
    with open(state_path, "w") as f:
        json.dump(state.model_dump(), f, indent=2, default=str)


def build_scanners(config: CountryConfig) -> list[Scanner]:
    scanners: list[Scanner] = []
    enabled = _enabled_platforms()
    if enabled:
        logger.info("Platform filter active: %s", ", ".join(sorted(enabled)))

    reddit_id = os.getenv("REDDIT_CLIENT_ID")
    reddit_secret = os.getenv("REDDIT_CLIENT_SECRET")
    reddit_ua = os.getenv("REDDIT_USER_AGENT", "SplitStay Social Listener v1.0")

    if _platform_enabled("reddit", enabled):
        if reddit_id and reddit_secret:
            scanners.append(RedditScanner(reddit_id, reddit_secret, reddit_ua, config.subreddits))
        else:
            logger.warning("Reddit credentials not set — skipping Reddit")

    if _platform_enabled("twitter", enabled):
        scanners.append(TwitterScanner())

    for platform in WEB_PLATFORMS:
        if _platform_enabled(platform, enabled):
            scanners.append(WebSearchScanner(platform))

    return scanners


async def scan_country(country: str) -> int:
    logger.info("%s", "=" * 40)
    logger.info("Starting scan: %s", country.upper())
    logger.info("%s", "=" * 40)

    config = merge_priority_events(load_config(country))

    original_event_count = len(config.events)
    config.events = filter_future_events(config.events)
    logger.info(
        "Future-event filter: scanning %s of %s configured events",
        len(config.events),
        original_event_count,
    )

    max_events = _int_env("SCAN_MAX_EVENTS", 0)
    if max_events:
        original_count = len(config.events)
        config.events = config.events[:max_events]
        logger.info(
            "SCAN_MAX_EVENTS active: scanning %s of %s future/priority events",
            len(config.events),
            original_count,
        )

    state = load_state(country)
    scanners = build_scanners(config)

    if not scanners:
        logger.warning("No scanners enabled — nothing to do")
        return 0

    scanner_timeout = _int_env("SCANNER_TIMEOUT_SECONDS", 120)
    logger.info("Per-scanner timeout: %s seconds", scanner_timeout)

    all_signals = []
    for scanner in scanners:
        logger.info("Scanning %s...", scanner.name)
        try:
            signals = await asyncio.wait_for(
                scanner.scan(config.events, config.country),
                timeout=scanner_timeout,
            )
            all_signals.extend(signals)
            logger.info("  %s: %s signals", scanner.name, len(signals))
        except asyncio.TimeoutError:
            logger.warning(
                "  %s timed out after %s seconds — continuing with next scanner",
                scanner.name,
                scanner_timeout,
            )
        except Exception as e:
            logger.error("  %s failed: %s", scanner.name, e)

    processor = SignalProcessor(state, max_age_days=60, events=config.events)
    new_signals = processor.process(all_signals)
    logger.info("Total: %s raw → %s qualified new signals", len(all_signals), len(new_signals))

    posted = 0
    if new_signals:
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        channel_id = os.getenv("SLACK_CHANNEL_ID")
        darwin_id = os.getenv("DARWIN_SLACK_ID")

        if slack_token and channel_id:
            poster = SlackPoster(slack_token, channel_id, darwin_id)
            posted = poster.post_signals_batch(
                new_signals,
                config.country,
                config.country_emoji,
                events=config.events,
            )
            logger.info("Posted %s of %s qualified signals to Slack", posted, len(new_signals))

            if posted == len(new_signals):
                processor.mark_posted(new_signals)
                processor.trim_state()
                logger.info("Marked %s signals as known", len(new_signals))
            else:
                logger.warning("Slack did not confirm every signal was posted. State was not updated.")
        else:
            logger.warning("Slack credentials not set — signals not posted")
            logger.warning("State was not updated, so these signals can be retried.")
            for s in new_signals:
                logger.info("  [%s] %s — %s", s.signal_type.value, s.title[:60], s.url)

    state.last_scan = datetime.now(timezone.utc).isoformat()
    state.scan_count += 1
    save_state(country, state)

    logger.info("Scan complete: %s — %s signals posted", country.upper(), posted)
    return posted


def main():
    parser = argparse.ArgumentParser(description="SplitStay Social Listener — Country Scanner")
    parser.add_argument(
        "--country",
        required=True,
        choices=["spain", "uk", "us", "brazil", "germany", "taiwan", "china", "portugal"],
        help="Country to scan",
    )
    args = parser.parse_args()

    posted = asyncio.run(scan_country(args.country))
    print(f"\n✅ Done — {posted} qualified signals posted to Slack")
    sys.exit(0)


if __name__ == "__main__":
    main()
