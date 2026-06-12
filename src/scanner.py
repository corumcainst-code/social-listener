"""Main scanner — orchestrates platform scanners for a country."""

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

from src.models import CountryConfig, ScanState, Event
from src.platforms.reddit import RedditScanner
from src.platforms.twitter import TwitterScanner
from src.platforms.web_search import WebSearchScanner
from src.platforms.facebook import FacebookScanner
from src.processor import SignalProcessor
from src.slack_bot import SlackPoster

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
CONFIG_DIR = Path(__file__).parent.parent / "config"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"


def load_config(country: str) -> CountryConfig:
    """Load a country config from JSON."""
    config_path = CONFIG_DIR / f"{country}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    
    with open(config_path) as f:
        data = json.load(f)
    
    return CountryConfig(**data)


def load_state(country: str) -> ScanState:
    """Load scan state for a country."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / f"{country}.json"
    
    if state_path.exists():
        with open(state_path) as f:
            return ScanState(**json.load(f))
    
    return ScanState()


def save_state(country: str, state: ScanState):
    """Save scan state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / f"{country}.json"
    
    with open(state_path, "w") as f:
        json.dump(state.model_dump(), f, indent=2, default=str)


async def scan_country(country: str) -> int:
    """Run a full scan for one country. Returns number of new signals posted."""
    logger.info(f"{'='*40}")
    logger.info(f"Starting scan: {country.upper()}")
    logger.info(f"{'='*40}")
    
    # Load config and state
    config = load_config(country)
    state = load_state(country)
    
    # Initialise scanners
    all_signals = []
    
    # 1. Reddit (most reliable source)
    reddit_id = os.getenv("REDDIT_CLIENT_ID")
    reddit_secret = os.getenv("REDDIT_CLIENT_SECRET")
    reddit_ua = os.getenv("REDDIT_USER_AGENT", "SplitStay Social Listener v1.0")
    
    if reddit_id and reddit_secret:
        logger.info("Scanning Reddit...")
        reddit = RedditScanner(reddit_id, reddit_secret, reddit_ua)
        
        for subreddit in config.subreddits:
            try:
                signals = reddit.scan_subreddit(
                    subreddit_name=subreddit,
                    events=config.events,
                    country=config.country,
                )
                all_signals.extend(signals)
                logger.info(f"  r/{subreddit}: {len(signals)} signals")
            except Exception as e:
                logger.error(f"  r/{subreddit} failed: {e}")
    else:
        logger.warning("Reddit credentials not set — skipping Reddit scan")
    
    # 2. Twitter/X
    logger.info("Scanning Twitter/X...")
    twitter = TwitterScanner()
    try:
        signals = await twitter.scan(config.events, config.country)
        all_signals.extend(signals)
        logger.info(f"  Twitter: {len(signals)} signals")
    except Exception as e:
        logger.error(f"  Twitter scan failed: {e}")
    finally:
        await twitter.close()
    
    # 3. Facebook
    logger.info("Scanning Facebook...")
    facebook = FacebookScanner()
    try:
        signals = await facebook.scan(config.events, config.country)
        all_signals.extend(signals)
        logger.info(f"  Facebook: {len(signals)} signals")
    except Exception as e:
        logger.error(f"  Facebook scan failed: {e}")
    finally:
        await facebook.close()
    
    # 4. Other platforms (Instagram, Discord, TikTok, Telegram)
    web = WebSearchScanner()
    for platform in ["instagram", "discord", "tiktok", "telegram"]:
        logger.info(f"Scanning {platform.title()}...")
        try:
            signals = await web.scan_platform(
                platform, config.events, config.country
            )
            all_signals.extend(signals)
            logger.info(f"  {platform.title()}: {len(signals)} signals")
        except Exception as e:
            logger.error(f"  {platform.title()} scan failed: {e}")
    await web.close()
    
    # Process & deduplicate
    processor = SignalProcessor(state, max_age_days=60)
    new_signals = processor.process(all_signals)
    processor.trim_state()
    
    logger.info(f"Total: {len(all_signals)} raw → {len(new_signals)} new signals")
    
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
            logger.info(f"Posted {posted} signals to Slack")
        else:
            logger.warning("Slack credentials not set — signals not posted")
            for s in new_signals:
                logger.info(f"  [{s.signal_type.value}] {s.title[:60]} — {s.url}")
    
    # Save state
    state.last_scan = datetime.now(timezone.utc).isoformat()
    state.scan_count += 1
    save_state(country, state)
    
    logger.info(f"Scan complete: {country.upper()} — {posted} signals posted")
    return posted


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="SplitStay Social Listener — Country Scanner")
    parser.add_argument(
        "--country",
        required=True,
        choices=["spain", "uk", "us", "brazil", "germany", "taiwan", "china", "portugal"],
        help="Country to scan",
    )
    args = parser.parse_args()
    
    posted = asyncio.run(scan_country(args.country))
    print(f"\n✅ Done — {posted} new signals posted to Slack")
    sys.exit(0)


if __name__ == "__main__":
    main()
