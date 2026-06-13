"""Web-search scanner — fallback for platforms without direct APIs.

Instantiate one per platform:

    WebSearchScanner("facebook")
    WebSearchScanner("instagram")
    WebSearchScanner("discord")
    WebSearchScanner("tiktok")
    WebSearchScanner("telegram")

Each instance scopes searches to the correct site and maps results to the
right ``Platform`` enum.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from src.models import Signal, SignalType, Platform, Event
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

# Classification keywords (shared by all web-search platforms)
_SEEKING = ["looking for", "share", "split", "roommate", "anyone want"]
_OFFERING = ["spare room", "extra space", "bed available", "room for"]
_COST_PAIN = ["expensive", "afford", "insane", "ridiculous", "prices"]
_GROUP = ["group", "meet up", "camp together", "travel together"]


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
                queries = [
                    f'{self._site_prefix} "{event.name}" share accommodation',
                    f'{self._site_prefix} "{event.location}" share hotel roommate',
                ]
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
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _search(client: httpx.AsyncClient, query: str) -> list[dict]:
        """Run a DuckDuckGo HTML search; returns [{title, url, snippet}]."""
        results: list[dict] = []
        try:
            encoded = query.replace(" ", "+")
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
        text = f"{result['title']} {result['snippet']}".lower()

        signal_type = None
        if any(kw in text for kw in _SEEKING):
            signal_type = SignalType.SEEKING
        elif any(kw in text for kw in _OFFERING):
            signal_type = SignalType.OFFERING
        elif any(kw in text for kw in _COST_PAIN):
            signal_type = SignalType.COST_PAIN
        elif any(kw in text for kw in _GROUP):
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
