"""Facebook group scanner — searches for accommodation-sharing signals."""

from __future__ import annotations

import logging

from src.models import Signal, Event
from src.platforms.web_search import WebSearchScanner

logger = logging.getLogger(__name__)


class FacebookScanner:
    """
    Scans Facebook groups for accommodation-sharing signals.
    
    Facebook's API is extremely restrictive for group content,
    so this uses web search to find public group posts.
    """
    
    def __init__(self):
        self.web_scanner = WebSearchScanner()
    
    async def scan(
        self,
        events: list[Event],
        country: str,
        groups: list[str] | None = None,
        max_age_days: int = 60,
    ) -> list[Signal]:
        """Scan Facebook for signals."""
        return await self.web_scanner.scan_platform(
            platform_name="facebook",
            events=events,
            country=country,
            max_age_days=max_age_days,
        )
    
    async def close(self):
        await self.web_scanner.close()
