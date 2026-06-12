"""Twitter/X scanner — searches for accommodation-sharing signals via web scraping."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from src.models import Signal, SignalType, Platform, Event

logger = logging.getLogger(__name__)

# Twitter's free API is very limited, so we use Nitter instances or web search
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
]

SEARCH_TERMS = [
    "share accommodation {event}",
    "split hotel {event}",
    "roommate {event}",
    "share airbnb {location}",
    "accommodation too expensive {event}",
    "looking for someone to share {event}",
]


class TwitterScanner:
    """Scans Twitter/X for accommodation-sharing signals using web search fallback."""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "SplitStay Social Listener v1.0"},
        )
    
    async def scan(
        self,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
    ) -> list[Signal]:
        """Scan Twitter for signals about events."""
        signals = []
        
        for event in events:
            for term_template in SEARCH_TERMS[:3]:
                term = term_template.format(
                    event=event.name,
                    location=event.location,
                )
                try:
                    new_signals = await self._search_via_nitter(term, event, country)
                    signals.extend(new_signals)
                except Exception as e:
                    logger.warning(f"Twitter search failed for '{term}': {e}")
        
        # Deduplicate
        seen = set()
        unique = []
        for s in signals:
            key = s.dedup_key()
            if key not in seen:
                seen.add(key)
                unique.append(s)
        
        return unique
    
    async def _search_via_nitter(
        self,
        query: str,
        event: Event,
        country: str,
    ) -> list[Signal]:
        """Search using Nitter (privacy-respecting Twitter frontend)."""
        signals = []
        
        for instance in NITTER_INSTANCES:
            try:
                url = f"{instance}/search?f=tweets&q={query}"
                response = await self.client.get(url)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, "html.parser")
                tweets = soup.select(".timeline-item")
                
                for tweet in tweets[:10]:
                    signal = self._parse_tweet(tweet, event, country, instance)
                    if signal:
                        signals.append(signal)
                
                break  # Success — don't try other instances
                
            except Exception as e:
                logger.debug(f"Nitter instance {instance} failed: {e}")
                continue
        
        return signals
    
    def _parse_tweet(
        self,
        tweet_element,
        event: Event,
        country: str,
        nitter_base: str,
    ) -> Signal | None:
        """Parse a tweet element from Nitter HTML."""
        try:
            content_el = tweet_element.select_one(".tweet-content")
            if not content_el:
                return None
            
            content = content_el.get_text(strip=True)
            
            author_el = tweet_element.select_one(".username")
            author = author_el.get_text(strip=True) if author_el else None
            
            link_el = tweet_element.select_one(".tweet-link")
            permalink = link_el["href"] if link_el else ""
            url = f"https://x.com{permalink}" if permalink else ""
            
            # Classify
            text_lower = content.lower()
            if any(kw in text_lower for kw in ["share", "split", "roommate", "looking for"]):
                signal_type = SignalType.SEEKING
            elif any(kw in text_lower for kw in ["expensive", "insane", "afford", "crazy"]):
                signal_type = SignalType.COST_PAIN
            else:
                return None
            
            return Signal(
                id=f"twitter_{hash(url) & 0xFFFFFFFF:08x}",
                signal_type=signal_type,
                platform=Platform.TWITTER,
                country=country,
                event=event.name,
                title=content[:80] + ("…" if len(content) > 80 else ""),
                content=content[:300],
                author=author,
                url=url,
            )
        except Exception:
            return None
    
    async def close(self):
        await self.client.aclose()
