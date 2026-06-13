"""Main scanner — orchestrates platform scanners for a country.

All platform scanners implement the same ``Scanner`` interface, so this
module simply builds a list and iterates.  No per-platform branching.
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

from src.models import CountryConfig, ScanState
from src.platforms.base import Scanner
from src.platforms.reddit import RedditScanner
from src.platforms.twitter import TwitterScanner
from src.platforms.web_search import WebSearchScanner
from src.processor import SignalProcessor
from src.slack_bot import SlackPoster

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"


# ------------------------------------------------------------------
# Config / state helpers
# ------------------------------------------------------------------

def load_config(country: str) -> CountryConfig:
    config_path = CONFIG_DIR / f"{country}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path) as f:
        data = json.load(f)
    return CountryConfig(**data)


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


# ------------------------------------------------------------------
# Scanner factory
# ------------------------------------------------------------------

def build_scanners(config: CountryConfig) -> list[Scanner]:
    """Build the list of scanners for a country, skipping unavailable ones."""
    scanners: list[Scanner] = []

    # Reddit (needs credentials)
    reddit_id = os.getenv("REDDIT_CLIENT_ID")
    reddit_secret = os.getenv("REDDIT_CLIENT_SECRET")
    reddit_ua = os.getenv("REDDIT_USER_AGENT", "SplitStay Social Listener v1.0")

    if reddit_id and reddit_secret:
        scanners.append(
            RedditScanner(reddit_id, reddit_secret, reddit_ua, config.subreddits)
        )
    else:
        logger.warning("Reddit credentials not set — skipping Reddit")

    # Twitter/X (no credentials needed — uses Nitter)
    scanners.append(TwitterScanner())

    # Web-search-based platforms (no credentials needed)
    for platform in ("facebook", "instagram", "discord", "tiktok", "telegram"):
        scanners.append(WebSearchScanner(platform))

    return scanners


# ------------------------------------------------------------------
# Main scan
# ------------------------------------------------------------------

async def scan_country(country: str) -> int:
    """Run a full scan for one country. Returns number of new signals posted."""
    logger.info("%s", "=" * 40)
    logger.info("Starting scan: %s", country.upper())
    logger.info("%s", "=" * 40)

    config = load_config(country)
    state = load_state(country)
    scanners = build_scanners(config)

    # Uniform loop — every scanner has the same interface
    all_signals = []
    for scanner in scanners:
        logger.info("Scanning %s...", scanner.name)
        try:
            signals = await scanner.scan(config.events, config.country)
            all_signals.extend(signals)
            logger.info("  %s: %s signals", scanner.name, len(signals))
        except Exception as e:
            logger.error("  %s failed: %s", scanner.name, e)

    # Process & deduplicate
    processor = SignalProcessor(state, max_age_days=60)
    new_signals = processor.process(all_signals)

    logger.info("Total: %s raw → %s new signals", len(all_signals), len(new_signals))

    # Post to Slack
    posted = 0
    if new_signals:
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        channel_id = os.getenv("SLACK_CHANNEL_ID")
        darwin_id = os.getenv("DARWIN_SLACK_ID")

        if slack_token and channel_id:
            poster = SlackPoster(slack_token, channel_id, darwin_id)
            posted = poster.post_signals_batch(
                new_signals, config.country, config.country_emoji
            )
            logger.info("Posted %s of %s signals to Slack", posted, len(new_signals))

            if posted == len(new_signals):
                processor.mark_posted(new_signals)
                processor.trim_state()
                logger.info("Marked %s signals as known", len(new_signals))
            else:
                logger.warning(
                    "Slack did not confirm every signal was posted. "
                    "State was not updated, so unconfirmed signals can be retried."
                )
        else:
            logger.warning("Slack credentials not set — signals not posted")
            logger.warning("State was not updated, so these signals can be retried.")
            for s in new_signals:
                logger.info("  [%s] %s — %s", s.signal_type.value, s.title[:60], s.url)

    # Save scan metadata and any successfully posted state.
    state.last_scan = datetime.now(timezone.utc).isoformat()
    state.scan_count += 1
    save_state(country, state)

    logger.info("Scan complete: %s — %s signals posted", country.upper(), posted)
    return posted


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SplitStay Social Listener — Country Scanner"
    )
    parser.add_argument(
        "--country",
        required=True,
        choices=[
            "spain", "uk", "us", "brazil",
            "germany", "taiwan", "china", "portugal",
        ],
        help="Country to scan",
    )
    args = parser.parse_args()

    posted = asyncio.run(scan_country(args.country))
    print(f"\n✅ Done — {posted} new signals posted to Slack")
    sys.exit(0)


if __name__ == "__main__":
    main()
