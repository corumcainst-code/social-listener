"""Web-search scanner — fallback for platforms without direct APIs.

Instantiate one per platform:

    WebSearchScanner("facebook")
    WebSearchScanner("instagram")
    WebSearchScanner("discord")
    WebSearchScanner("tiktok")
    WebSearchScanner("telegram")

Each instance scopes searches to the correct site and maps results to the
right ``Platform`` enum.

This scanner is deliberately limited to public/searchable web results. It does
not log in to Facebook, Instagram, TikTok, Discord, or Telegram, and it cannot
read private groups, locked profiles, or hidden comment threads.

v0.14 adds optional Smart Source Scanning. v0.14.1 keeps that feature OFF by
default but makes it much lighter when enabled:
- fewer total queries per platform/event
- shorter per-query web-search timeout
- configurable base/smart query counts

It remains limited to public/searchable web results only.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from src.classifier import classify
from src.models import Event, Platform, Signal, SignalType
from src.platforms.base import Scanner

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

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
    "accomodation",
    "hotel",
    "airbnb",
    "hostel",
    "room share",
    "roommate",
    "room mate",
    "share room",
    "share a room",
    "share accommodation",
    "share accom",
    "share hotel",
    "split hotel",
    "split airbnb",
    "split the cost",
    "place to stay",
    "somewhere to stay",
    "stay near",
    "stay in",
    "spare bed",
    "apartment",
    "flat",
    "house",
    "couch",
    "sofa",
    "near the venue",
    "near venue",
]

_COMMUNITY_TERMS = [
    "whatsapp",
    "group chat",
    "discord",
    "telegram",
    "facebook group",
    "athlete group",
    "race group",
    "travel group",
    "community",
    "join the group",
    "group link",
]

_DISCUSSION_TERMS = [
    "comment",
    "comments",
    "comment section",
    "thread",
    "discussion",
    "anyone going",
    "who is going",
    "where is everyone staying",
    "where are people staying",
    "where are you staying",
    "anyone staying",
    "anyone need a room",
    "anyone have a room",
    "who needs a room",
    "hotel share",
    "room share",
    "roommate",
    "room mate",
    "travel together",
    "split costs",
]

_COST_PAIN_TERMS = [
    "too expensive",
    "so expensive",
    "hotel prices",
    "accommodation prices",
    "airbnb prices",
    "sold out",
    "sold out everywhere",
    "no affordable",
    "cheap hotel",
    "budget hotel",
]

# Stronger search patterns by platform. These improve discovery of public event,
# group, caption and comment-like surfaces without pretending to access private
# comments.
_PLATFORM_INTENT_QUERIES: dict[str, list[str]] = {
    "facebook": [
        '"{kw}" "where is everyone staying"',
        '"{kw}" "room share" OR "hotel share"',
        '"{kw}" "facebook group" accommodation',
        '"{kw}" "event" accommodation hotel',
    ],
    "instagram": [
        '"{kw}" accommodation hotel airbnb',
        '"{kw}" "room share" OR roommate',
        '"{kw}" "anyone going" hotel',
        '"{kw}" "where is everyone staying"',
    ],
    "tiktok": [
        '"{kw}" accommodation hotel airbnb',
        '"{kw}" "room share" OR roommate',
        '"{kw}" "comments" accommodation',
        '"{kw}" "anyone going" hotel',
    ],
    "telegram": [
        '"{kw}" "group chat" accommodation',
        '"{kw}" "room share" telegram',
        '"{kw}" "hotel share"',
        '"{kw}" "anyone going"',
    ],
    "discord": [
        '"{kw}" discord accommodation',
        '"{kw}" "group chat" "room share"',
        '"{kw}" "hotel share"',
        '"{kw}" "anyone going"',
    ],
}


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


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_source_map() -> dict:
    """Load optional v0.14 public source map.

    The file is additive only. If it is missing or invalid, the scanner falls
    back to the existing query behaviour.
    """
    path = CONFIG_DIR / "source_map.json"
    if not path.exists():
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("public_sources_only", True):
            logger.warning("source_map.json must remain public-sources-only; ignoring source map")
            return {}
        return data
    except Exception as exc:
        logger.warning("Could not load source_map.json: %s", exc)
        return {}


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

        http_timeout = _int_env("WEB_SEARCH_HTTP_TIMEOUT_SECONDS", 12)
        async with httpx.AsyncClient(
            timeout=http_timeout,
            headers={"User-Agent": "SplitStay Social Listener v1.0"},
        ) as client:
            for event in events:
                queries = self._queries_for_event(event, country)
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

    def _queries_for_event(self, event: Event, country: str) -> list[str]:
        """Build search queries that are specific enough to be useful.

        HYROX and other event-led scans need more than generic accommodation
        searches. We search for public event pages, group pages, captions and
        comment-like snippets where people are asking where to stay, looking for
        rooms, or forming travel/accommodation groups.

        Smart Source Scanning is additive and OFF by default.
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

            # Keep this tight so all platforms finish quickly on Apify.
            for kw in city_keywords[:2]:
                queries.extend(self._platform_queries_for_keyword(kw))

            for kw in intent_keywords[:2]:
                queries.append(f'{self._site_prefix} "{kw}"')

            # Fallbacks if the config only has a broad HYROX event name.
            if not queries:
                queries.extend([
                    f'{self._site_prefix} hyrox accommodation hotel airbnb',
                    f'{self._site_prefix} hyrox "room share" whatsapp "group chat"',
                    f'{self._site_prefix} hyrox "where is everyone staying"',
                    f'{self._site_prefix} hyrox "anyone going" hotel',
                ])

        else:
            # Standard event search for festivals/conferences/other events.
            if event.name:
                queries.extend(self._platform_queries_for_keyword(event.name))

            for kw in keywords[:3]:
                queries.extend(self._platform_queries_for_keyword(kw))

            if event.location:
                # Do not quote full multi-city strings like "London / Manchester".
                for part in event.location.replace("/", ",").split(",")[:3]:
                    location = part.strip()
                    if location:
                        queries.append(f'{self._site_prefix} "{location}" "{event.name}" hotel room')
                        queries.append(f'{self._site_prefix} "{location}" "{event.name}" "where is everyone staying"')

        if _bool_env("SMART_SOURCE_SCANNING", default=False):
            # v0.14.1 light mode:
            # Keep only a very small mix of the existing high-confidence queries
            # plus a few source-map-led smart queries. This avoids the full-batch
            # timeout we saw when v0.14 generated too many search URLs.
            smart_queries = self._smart_source_queries_for_event(event, country, keywords)

            base_keep = _int_env("SMART_SOURCE_BASE_QUERIES_PER_EVENT", 1)
            smart_keep = _int_env("SMART_SOURCE_EXTRA_QUERIES_PER_EVENT", 2)
            light_queries = self._unique(queries[:base_keep] + smart_queries[:smart_keep])

            logger.info(
                "  %s: Smart Source Scanning LIGHT enabled for %s (%s base + %s smart queries)",
                self.name,
                country,
                base_keep,
                smart_keep,
            )
            return light_queries

        return self._unique(queries)[:max_queries]

    def _smart_source_queries_for_event(
        self,
        event: Event,
        country: str,
        keywords: list[str],
    ) -> list[str]:
        """Build extra source-map-led queries for public/searchable surfaces only."""
        source_map = _load_source_map()
        if not source_map:
            return []

        country_map = source_map.get("countries", {}).get(country, {})
        global_intents = source_map.get("global_intent_phrases", [])
        country_intents = country_map.get("intent_phrases", [])
        country_aliases = country_map.get("event_aliases", [])
        global_surfaces = source_map.get("global_surface_terms", [])
        country_surfaces = country_map.get("surface_terms", [])

        intent_phrases = self._unique([*country_intents, *global_intents])
        surface_terms = self._unique([*country_surfaces, *global_surfaces])

        event_terms = self._unique([
            event.name,
            *country_aliases[:4],
            *[kw for kw in keywords if kw],
        ])
        event_terms = [term for term in event_terms if term and str(term).strip()]

        queries: list[str] = []

        # v0.14.1 light mode: generate a small ordered list only.
        # The caller then takes just the first few smart queries.
        primary_event_terms = event_terms[:2]
        primary_intents = intent_phrases[:3]
        primary_surfaces = surface_terms[:2]

        # High-intent queries: event + accommodation/room-share/cost-pain phrase.
        for event_term in primary_event_terms:
            for phrase in primary_intents:
                queries.append(f'{self._site_prefix} "{event_term}" "{phrase}"')

        # Surface-aware queries: public event pages, public groups, comments, forums.
        # Keep this small; broad surface queries caused slow batch runs in v0.14.
        for event_term in primary_event_terms[:1]:
            for surface in primary_surfaces:
                queries.append(f'{self._site_prefix} "{event_term}" "{surface}" accommodation')

        # Location-intent queries catch cases where people mention the venue/city.
        if event.location:
            for part in event.location.replace("/", ",").split(",")[:1]:
                location = part.strip()
                if location:
                    queries.append(f'{self._site_prefix} "{location}" "{event.name}" "need somewhere to stay"')

        return self._unique(queries)

    def _platform_queries_for_keyword(self, keyword: str) -> list[str]:
        """Return platform-specific search patterns for one event keyword."""
        templates = _PLATFORM_INTENT_QUERIES.get(self._platform_name)
        if not templates:
            templates = [
                '"{kw}" accommodation hotel airbnb',
                '"{kw}" "room share" "group chat"',
                '"{kw}" "where is everyone staying"',
                '"{kw}" "anyone going"',
            ]

        return [f"{self._site_prefix} " + template.format(kw=keyword) for template in templates]

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
        text_lower = text.lower()
        signal_type = classify(text, platform=self._platform_name)

        has_hyrox = "hyrox" in text_lower or (event.type or "").lower() == "hyrox"
        has_accommodation = any(term in text_lower for term in _ACCOMMODATION_TERMS)
        has_community = any(term in text_lower for term in _COMMUNITY_TERMS)
        has_discussion = any(term in text_lower for term in _DISCUSSION_TERMS)
        has_cost_pain = any(term in text_lower for term in _COST_PAIN_TERMS)

        # HYROX/event fallback: if search found a relevant result with
        # accommodation, community, cost-pain or discussion wording, keep it for
        # the quality layer to score. This avoids losing useful short snippets.
        if not signal_type and has_hyrox:
            if has_accommodation or has_discussion:
                signal_type = SignalType.SEEKING
            elif has_community:
                signal_type = SignalType.GROUP_FORMING
            elif has_cost_pain:
                signal_type = SignalType.COST_PAIN

        if not signal_type:
            return None

        source_context = self._source_context(result, text)
        snippet = result["snippet"][:300]
        if source_context:
            snippet = f"Source context: {source_context}\n{snippet}"
        if _bool_env("SMART_SOURCE_SCANNING", default=False):
            snippet = f"Smart source scan: enabled\n{snippet}"

        return Signal(
            id=f"{self._platform_name}_{hash(result['url']) & 0xFFFFFFFF:08x}",
            signal_type=signal_type,
            platform=self._platform_enum,
            country=country,
            event=event.name,
            title=result["title"][:120],
            content=snippet[:500],
            url=result["url"],
        )

    def _source_context(self, result: dict, text: str) -> str:
        """Best-effort label for what kind of public surface was found."""
        url = (result.get("url") or "").lower()
        combined = f"{url} {text}".lower()

        if "facebook.com/events" in combined or "event page" in combined:
            return "Facebook event page"
        if "facebook.com/groups" in combined or "facebook group" in combined:
            return "Facebook group"
        if "discord.gg" in combined or "discord.com/invite" in combined:
            return "Discord invite/community"
        if "t.me/" in combined or "telegram" in combined:
            return "Telegram public group/channel"
        if "tiktok.com" in combined:
            if "comment" in combined or "comments" in combined:
                return "TikTok comment/caption signal"
            return "TikTok public post"
        if "instagram.com" in combined:
            if "comment" in combined or "comments" in combined:
                return "Instagram comment/caption signal"
            return "Instagram public post"
        if "thread" in combined or "discussion" in combined or "comments" in combined:
            return "Public thread/discussion"

        return f"{self.name} public/searchable result"

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
