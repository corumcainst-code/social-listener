"""Trustpilot review monitor — CLI entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.models import TrustpilotState
from src.platforms.trustpilot import TrustpilotMonitor
from src.slack_bot import SlackPoster

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent / "data" / "state"


async def check_trustpilot() -> int:
    """Check for new Trustpilot reviews and post them to Slack."""
    logger.info("Checking Trustpilot for new reviews...")
    
    # Load state
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / "trustpilot.json"
    
    if state_path.exists():
        with open(state_path) as f:
            state = TrustpilotState(**json.load(f))
    else:
        state = TrustpilotState()
    
    # Scrape reviews
    url = os.getenv("TRUSTPILOT_URL", "https://www.trustpilot.com/review/splitstay.travel")
    monitor = TrustpilotMonitor(url)
    
    all_reviews = await monitor.check_for_reviews()
    logger.info(f"Found {len(all_reviews)} reviews on page")
    
    # Filter to new reviews only
    new_reviews = [r for r in all_reviews if not state.is_known(r)]
    logger.info(f"New reviews: {len(new_reviews)}")
    
    # Post to Slack
    posted = 0
    if new_reviews:
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        channel_id = os.getenv("SLACK_CHANNEL_ID")
        
        if slack_token and channel_id:
            # NO darwin_id — don't tag anyone on Trustpilot reviews
            poster = SlackPoster(slack_token, channel_id, darwin_slack_id=None)
            
            for review in new_reviews:
                if poster.post_trustpilot_review(review):
                    posted += 1
                    # Add to known reviews
                    state.known_reviews.append({
                        "reviewer": review.reviewer,
                        "rating": review.rating,
                        "title": review.title,
                        "date": review.date,
                    })
        else:
            logger.warning("Slack credentials not set")
            for r in new_reviews:
                logger.info(f"  ⭐ {r.rating}/5 by {r.reviewer}: {r.title}")
    else:
        logger.info("No new reviews — staying silent")
    
    # Save state
    state.last_check = datetime.now(timezone.utc).isoformat()
    state.check_count += 1
    with open(state_path, "w") as f:
        json.dump(state.model_dump(), f, indent=2, default=str)
    
    return posted


def main():
    posted = asyncio.run(check_trustpilot())
    if posted:
        print(f"\n✅ Posted {posted} new Trustpilot reviews to Slack")
    else:
        print("\n✅ No new Trustpilot reviews")
    sys.exit(0)


if __name__ == "__main__":
    main()
