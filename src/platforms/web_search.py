"""Web-search scanner — fallback for platforms without direct APIs.

Instantiate one per platform:

    WebSearchScanner("facebook")
    WebSearchScanner("instagram")
    WebSearchScanner("discord")
    WebSearchScanner("tiktok")
    WebSearchScanner("telegram")

Each instance scopes searches to the correct site and maps results to the
right ``Platform`` enum.

The query builder intentionally avoids over-specific exact-match searches such
as "HYROX UK 2026-2027 Season" because those usually return no results. For
priority verticals like HYROX, it searches city/intent keywords instead, such as
"HYROX London" + accommodation, hotel, room share, WhatsApp, and group chat.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from src.classifier import classify
from src.models import Event, Platform, Signal, SignalType
from src.platforms.base import Scanner

logger = logging.getLogger(__name__)

# Site-scoped search prefixes for DuckDuckGo
_SITE_PREFIXES: dict[str, str] = {
    "facebook": "site:facebook.com",
    "instagram": "site:instagram.com",
    "discord": "site:discord.com OR site:discord.gg",
    "tiktok": "site:tiktok.com",
    "telegram": "site:t.me",
}

_PLATFORM_ENUM: dict[str, Platform] = {
    "facebook": Platform.FACEBOOK,
    "instagram": Platform.INSTAGRAM,
    "discord": Platform.DISCORD,
    "tiktok": Platform.TIKTOK,
    "telegram": Platform.TELEGRAM,
}

_ACCOMMODATION_TERMS = [
    "accommodation",
    "hotel",
    "airbnb",
    "room share",
    "roommate",
    "place to stay",
]

_COMMUNITY_TERMS = [
    "whatsapp",
    "group chat",
    "discord",
    "telegram",
    "facebook group",
    "athlete group",
]


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


class WebSearchScanner(Scanner):
    """Searches a specific platform via DuckDuckGo HTML (no API key)."""

    def __init__(self, platform_name: str):
        if platform_name not in _SITE_PREFIXES:
            raise ValueError(
                f"Unknown platform '{platform_name}'. "
                f"Choose from: {', '.join(_SITE_PREFIXES)}"
            )
        self._platform_name = platform_name
        self._site_prefix = _SITE_PREFIXES[platform_name]
        self._platform_enum = _PLATFORM_ENUM.get(platform_name, Platform.WEB)

    @property
    def name(self) -> str:
        return self._platform_name.title()

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
                queries = self._queries_for_event(event)
                logger.info("  %s: %s search queries for %s", self.name, len(queries), event.name)

                for query in queries:
                    try:
                        results = await self._search(client, query)
                        for result in results:
                            signal = self._classify(result, event, country)
                            if signal:
                                signals.append(signal)
                    except Exception as e:
                        logger.warning(f"Web search failed for '{query}': {e}")

        return self._deduplicate(signals)

    # ------------------------------------------------------------------
    # Query building
    # ------------------------------------------------------------------

    def _queries_for_event(self, event: Event) -> list[str]:
        """Build search queries that are specific enough to be useful.

        HYROX needs different handling from normal event search. Exact quoted
        season names are too narrow, so we prioritise event.keywords and pair
        them with accommodation/community terms.
        """
        max_queries = _int_env("WEB_SEARCH_MAX_QUERIES_PER_EVENT", 8)
        event_type = (event.type or "").lower()
        keywords = [kw.strip() for kw in event.keywords if kw and kw.strip()]

        queries: list[str] = []

        if event_type == "hyrox":
            # Prefer city/country HYROX keywords first, then intent keywords.
            city_keywords = [
                kw for kw in keywords
                if "hyrox" in kw.lower()
                and not any(term in kw.lower() for term in _ACCOMMODATION_TERMS + _COMMUNITY_TERMS)
            ]
            intent_keywords = [
                kw for kw in keywords
                if any(term in kw.lower() for term in _ACCOMMODATION_TERMS + _COMMUNITY_TERMS)
            ]

            for kw in city_keywords[:4]:
                queries.append(f'{self._site_prefix} "{kw}" accommodation hotel airbnb')
                queries.append(f'{self._site_prefix} "{kw}" "room share" roommate "group chat" whatsapp')

            for kw in intent_keywords[:4]:
                queries.append(f'{self._site_prefix} "{kw}"')

            # Fallbacks if the config only has a broad HYROX event name.
            if not queries:
                queries.extend([
                    f'{self._site_prefix} hyrox accommodation hotel airbnb',
                    f'{self._site_prefix} hyrox "room share" whatsapp "group chat"',
                ])

            return self._unique(queries)[:max_queries]

        # Standard event search for festivals/conferences/other events.
        if event.name:
            queries.append(f'{self._site_prefix} "{event.name}" share accommodation')
            queries.append(f'{self._site_prefix} "{event.name}" hotel airbnb room share')

        for kw in keywords[:4]:
            queries.append(f'{self._site_prefix} "{kw}" accommodation hotel airbnb')
            queries.append(f'{self._site_prefix} "{kw}" "room share" "group chat"')

        if event.location:
            # Do not quote full multi-city strings like "London / Manchester".
            for part in event.location.replace("/", ",").split(",")[:3]:
                location = part.strip()
                if location:
                    queries.append(f'{self._site_prefix} "{location}" "{event.name}" hotel room')

        return self._unique(queries)[:max_queries]

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _search(client: httpx.AsyncClient, query: str) -> list[dict]:
        """Run a DuckDuckGo HTML search; returns [{title, url, snippet}]."""
        results: list[dict] = []
        try:
            encoded = quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            response = await client.get(url)
            if response.status_code != 200:
                return results

            soup = BeautifulSoup(response.text, "html.parser")
            for div in soup.select(".result")[:10]:
                title_el = div.select_one(".result__title a")
                snippet_el = div.select_one(".result__snippet")
                if not title_el:
                    continue

                result_url = title_el.get("href", "")
                if "uddg=" in result_url:
                    parsed = urlparse(result_url)
                    params = parse_qs(parsed.query)
                    result_url = unquote(params.get("uddg", [result_url])[0])

                results.append({
                    "title": title_el.get_text(strip=True),
                    "url": result_url,
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                })
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")

        return results

    def _classify(
        self,
        result: dict,
        event: Event,
        country: str,
    ) -> Signal | None:
        text = f"{result['title']} {result['snippet']}"
        signal_type = classify(text, platform=self._platform_name)

        # HYROX fallback: if search found a HYROX result with accommodation or
        # community wording, keep it as a lead/community signal for the quality
        # layer to score. This avoids losing useful results where the central
        # classifier misses a short social-search snippet.
        if not signal_type and (event.type or "").lower() == "hyrox":
            text_lower = text.lower()
            if "hyrox" in text_lower:
                if any(term in text_lower for term in _ACCOMMODATION_TERMS):
                    signal_type = SignalType.SEEKING
                elif any(term in text_lower for term in _COMMUNITY_TERMS):
                    signal_type = SignalType.GROUP_FORMING

        if not signal_type:
            return None

        return Signal(
            id=f"{self._platform_name}_{hash(result['url']) & 0xFFFFFFFF:08x}",
            signal_type=signal_type,
            platform=self._platform_enum,
            country=country,
            event=event.name,
            title=result["title"][:120],
            content=result["snippet"][:300],
            url=result["url"],
        )

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
