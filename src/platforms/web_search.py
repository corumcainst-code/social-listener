"""General web search scanner — fallback for platforms without APIs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from src.models import Signal, SignalType, Platform, Event

logger = logging.getLogger(__name__)

# Platforms to search via web
PLATFORM_SEARCH_PREFIXES = {
    "facebook": "site:facebook.com",
    "instagram": "site:instagram.com",
    "discord": "site:discord.com OR site:discord.gg",
    "tiktok": "site:tiktok.com",
    "telegram": "site:t.me",
}


class WebSearchScanner:
    """Searches the web for accommodation-sharing signals on various platforms."""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "SplitStay Social Listener v1.0"},
        )
    
    async def scan_platform(
        self,
        platform_name: str,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
    ) -> list[Signal]:
        """Search a platform via web search for accommodation signals."""
        signals = []
        site_prefix = PLATFORM_SEARCH_PREFIXES.get(platform_name, "")
        
        for event in events:
            queries = [
                f'{site_prefix} "{event.name}" share accommodation',
                f'{site_prefix} "{event.location}" share hotel roommate',
                f'{site_prefix} "{event.name}" split stay cost',
            ]
            
            for query in queries[:2]:  # Limit queries per event
                try:
                    results = await self._search(query)
                    for result in results:
                        signal = self._classify_result(
                            result, platform_name, event, country
                        )
                        if signal:
                            signals.append(signal)
                except Exception as e:
                    logger.warning(f"Web search failed for '{query}': {e}")
        
        # Deduplicate
        seen = set()
        unique = []
        for s in signals:
            key = s.dedup_key()
            if key not in seen:
                seen.add(key)
                unique.append(s)
        
        return unique
    
    async def _search(self, query: str) -> list[dict]:
        """
        Perform a web search. 
        
        This is a placeholder — in production, use one of:
        - SerpAPI (free tier: 100 searches/month)
        - Brave Search API (free tier: 2000/month)
        - DuckDuckGo HTML scraping
        
        Returns list of {title, url, snippet} dicts.
        """
        results = []
        
        try:
            # DuckDuckGo HTML search (no API key needed)
            encoded_query = query.replace(" ", "+")
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            
            response = await self.client.get(url)
            if response.status_code != 200:
                return results
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            for result_div in soup.select(".result")[:10]:
                title_el = result_div.select_one(".result__title a")
                snippet_el = result_div.select_one(".result__snippet")
                
                if title_el:
                    result_url = title_el.get("href", "")
                    # DuckDuckGo wraps URLs in redirect — extract actual URL
                    if "uddg=" in result_url:
                        from urllib.parse import unquote, parse_qs, urlparse
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
    
    def _classify_result(
        self,
        result: dict,
        platform_name: str,
        event: Event,
        country: str,
    ) -> Signal | None:
        """Classify a search result as a signal."""
        text = f"{result['title']} {result['snippet']}".lower()
        
        seeking_kw = ["looking for", "share", "split", "roommate", "anyone want"]
        offering_kw = ["spare room", "extra space", "bed available", "room for"]
        cost_kw = ["expensive", "afford", "insane", "ridiculous", "prices"]
        group_kw = ["group", "meet up", "camp together", "travel together"]
        
        signal_type = None
        if any(kw in text for kw in seeking_kw):
            signal_type = SignalType.SEEKING
        elif any(kw in text for kw in offering_kw):
            signal_type = SignalType.OFFERING
        elif any(kw in text for kw in cost_kw):
            signal_type = SignalType.COST_PAIN
        elif any(kw in text for kw in group_kw):
            signal_type = SignalType.GROUP_FORMING
        
        if not signal_type:
            return None
        
        # Map platform name to enum
        platform_map = {
            "facebook": Platform.FACEBOOK,
            "instagram": Platform.INSTAGRAM,
            "discord": Platform.DISCORD,
            "tiktok": Platform.TIKTOK,
            "telegram": Platform.TELEGRAM,
        }
        platform = platform_map.get(platform_name, Platform.WEB)
        
        return Signal(
            id=f"{platform_name}_{hash(result['url']) & 0xFFFFFFFF:08x}",
            signal_type=signal_type,
            platform=platform,
            country=country,
            event=event.name,
            title=result["title"][:120],
            content=result["snippet"][:300],
            url=result["url"],
        )
    
    async def close(self):
        await self.client.aclose()
