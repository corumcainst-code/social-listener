"""Price spike monitor — alerts when accommodation prices spike near events."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.models import ScanState
from src.platforms.web_search import WebSearchScanner
from src.slack_bot import SlackPoster

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"

# Events known for extreme price spikes
HIGH_SPIKE_EVENTS = [
    {"name": "Glastonbury Festival", "location": "Somerset, UK", "emoji": "🇬🇧"},
    {"name": "Formula 1 Barcelona Grand Prix", "location": "Barcelona", "emoji": "🇪🇸"},
    {"name": "Oktoberfest", "location": "Munich", "emoji": "🇩🇪"},
    {"name": "Coachella", "location": "Indio, CA", "emoji": "🇺🇸"},
    {"name": "SDCC Comic-Con", "location": "San Diego, CA", "emoji": "🇺🇸"},
    {"name": "Tomorrowland", "location": "Boom, Belgium", "emoji": "🇧🇪"},
    {"name": "Carnival Rio", "location": "Rio de Janeiro", "emoji": "🇧🇷"},
    {"name": "Web Summit", "location": "Lisbon", "emoji": "🇵🇹"},
    {"name": "MWC Barcelona", "location": "Barcelona", "emoji": "🇪🇸"},
]


async def scan_price_spikes() -> int:
    """Search for accommodation price spike reports near major events."""
    logger.info("Starting price spike scan")
    
    state_path = STATE_DIR / "prices.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    if state_path.exists():
        with open(state_path) as f:
            state = ScanState(**json.load(f))
    else:
        state = ScanState()
    
    web = WebSearchScanner()
    posted = 0
    
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID")
    darwin_id = os.getenv("DARWIN_SLACK_ID")
    
    poster = None
    if slack_token and channel_id:
        poster = SlackPoster(slack_token, channel_id, darwin_id)
    
    for event in HIGH_SPIKE_EVENTS:
        queries = [
            f'"{event["name"]}" accommodation price spike 2026',
            f'"{event["location"]}" hotel prices {event["name"]} expensive',
            f'"{event["name"]}" accommodation sold out',
        ]
        
        for query in queries[:2]:
            try:
                results = await web._search(query)
                for result in results:
                    url = result["url"].lower().strip().rstrip("/")
                    if state.is_known(url):
                        continue
                    
                    snippet = result["snippet"].lower()
                    # Only post if it mentions actual prices or spike indicators
                    price_indicators = [
                        "£", "$", "€", "per night", "spike", "surge",
                        "sold out", "triple", "double", "expensive",
                    ]
                    if not any(ind in snippet for ind in price_indicators):
                        continue
                    
                    if poster:
                        success = poster.post_price_alert(
                            event_name=event["name"],
                            location=event["location"],
                            country_emoji=event["emoji"],
                            avg_price="See link for details",
                            spike_pct="Price spike detected",
                            source_url=result["url"],
                        )
                        if success:
                            posted += 1
                    
                    state.add_signal(url)
                    
            except Exception as e:
                logger.warning(f"Price search failed for '{query}': {e}")
    
    await web.close()
    
    # Save state
    state.last_scan = datetime.now(timezone.utc).isoformat()
    state.scan_count += 1
    with open(state_path, "w") as f:
        json.dump(state.model_dump(), f, indent=2, default=str)
    
    logger.info(f"Price scan complete — {posted} alerts posted")
    return posted


def main():
    posted = asyncio.run(scan_price_spikes())
    print(f"\n✅ Price scan done — {posted} alerts posted")
    sys.exit(0)


if __name__ == "__main__":
    main()
