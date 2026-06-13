"""Twitter/X scanner — searches for accommodation-sharing signals via Nitter.

ADR: Twitter classification intentionally uses only SEEKING and COST_PAIN
categories.  Tweets are too short for reliable OFFERING or GROUP_FORMING
detection, so we keep the set narrow to avoid false positives.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from src.models import Signal, SignalType, Platform, Event
from src.platforms.base import Scanner

logger = logging.getLogger(__name__)

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


class TwitterScanner(Scanner):
    """Scans Twitter/X via Nitter instances (no API key needed)."""

    @property
    def name(self) -> str:
        return "Twitter/X"

    async def scan(
        self,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
    ) -> list[Signal]:
        signals: list[Signal] = []

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "SplitStay Social Listener v1.0"},
        ) as client:
            for event in events:
                for term_template in SEARCH_TERMS[:3]:
                    term = term_template.format(
                        event=event.name,
                        location=event.location,
                    )
                    try:
                        new = await self._search_nitter(client, term, event, country)
                        signals.extend(new)
                    except Exception as e:
                        logger.warning(f"Twitter search failed for '{term}': {e}")

        return self._deduplicate(signals)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _search_nitter(
        self,
        client: httpx.AsyncClient,
        query: str,
        event: Event,
        country: str,
    ) -> list[Signal]:
        signals: list[Signal] = []

        for instance in NITTER_INSTANCES:
            try:
                url = f"{instance}/search?f=tweets&q={query}"
                response = await client.get(url)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                for tweet in soup.select(".timeline-item")[:10]:
                    signal = self._parse_tweet(tweet, event, country)
                    if signal:
                        signals.append(signal)
                break  # Success — don't try other instances
            except Exception as e:
                logger.debug(f"Nitter instance {instance} failed: {e}")

        return signals

    @staticmethod
    def _parse_tweet(
        tweet_element,
        event: Event,
        country: str,
    ) -> Signal | None:
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

            # ADR: intentionally narrow — SEEKING + COST_PAIN only for tweets
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

    @staticmethod
    def _deduplicate(signals: list[Signal]) -> list[Signal]:
        seen: set[str] = set()
        unique: list[Signal] = []
        for s in signals:
            key = s.dedup_key()
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return unique
