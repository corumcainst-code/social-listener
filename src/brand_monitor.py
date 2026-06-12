"""Brand & competitor monitor — tracks mentions of SplitStay and competitors."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.models import Signal, SignalType, Platform, ScanState
from src.platforms.web_search import WebSearchScanner
from src.processor import SignalProcessor
from src.slack_bot import SlackPoster

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent / "data" / "state"

# Brand & competitor search terms
BRAND_QUERIES = [
    '"splitstay" OR "split stay" accommodation',
    '"splitstay.travel" review',
    '"splitstay" festival accommodation',
]

COMPETITOR_QUERIES = [
    '"ShareMy" accommodation festival',
    '"RoomBuddy" event sharing',
    '"SplitBooking" accommodation',
    '"Roomi" OR "SpareRoom" festival accommodation share',
    '"Hostelworld" group booking share',
]


async def scan_brand_and_competitors() -> int:
    """Scan for brand mentions and competitor activity."""
    logger.info("Starting brand & competitor scan")
    
    state_path = STATE_DIR / "brand.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    if state_path.exists():
        with open(state_path) as f:
            state = ScanState(**json.load(f))
    else:
        state = ScanState()
    
    all_signals = []
    web = WebSearchScanner()
    
    # Brand mentions
    for query in BRAND_QUERIES:
        try:
            results = await web._search(query)
            for result in results:
                signal = Signal(
                    id=f"brand_{hash(result['url']) & 0xFFFFFFFF:08x}",
                    signal_type=SignalType.BRAND,
                    platform=Platform.WEB,
                    country="global",
                    title=result["title"][:120],
                    content=result["snippet"][:300],
                    url=result["url"],
                )
                all_signals.append(signal)
        except Exception as e:
            logger.warning(f"Brand search failed for '{query}': {e}")
    
    # Competitor mentions
    for query in COMPETITOR_QUERIES:
        try:
            results = await web._search(query)
            for result in results:
                signal = Signal(
                    id=f"competitor_{hash(result['url']) & 0xFFFFFFFF:08x}",
                    signal_type=SignalType.COMPETITOR,
                    platform=Platform.WEB,
                    country="global",
                    title=result["title"][:120],
                    content=result["snippet"][:300],
                    url=result["url"],
                )
                all_signals.append(signal)
        except Exception as e:
            logger.warning(f"Competitor search failed for '{query}': {e}")
    
    await web.close()
    
    # Process
    processor = SignalProcessor(state, max_age_days=60)
    new_signals = processor.process(all_signals)
    
    # Post to Slack
    posted = 0
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID")
    darwin_id = os.getenv("DARWIN_SLACK_ID")
    
    if slack_token and channel_id and new_signals:
        poster = SlackPoster(slack_token, channel_id, darwin_id)
        posted = poster.post_signals_batch(
            new_signals, "Brand & Competitor", "🏷️"
        )
    
    # Save state
    state.last_scan = datetime.now(timezone.utc).isoformat()
    state.scan_count += 1
    with open(state_path, "w") as f:
        json.dump(state.model_dump(), f, indent=2, default=str)
    
    logger.info(f"Brand scan complete — {posted} signals posted")
    return posted


def main():
    posted = asyncio.run(scan_brand_and_competitors())
    print(f"\n✅ Brand scan done — {posted} signals posted")
    sys.exit(0)


if __name__ == "__main__":
    main()
