"""Data models for the social listener."""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    OFFERING = "OFFERING"       # Someone offering to share accommodation
    SEEKING = "SEEKING"         # Someone looking for people to share with
    COST_PAIN = "COST_PAIN"     # Complaining about accommodation costs
    GROUP_FORMING = "GROUP_FORMING"  # Group organising to share stays
    BRAND = "BRAND"             # SplitStay brand mention
    COMPETITOR = "COMPETITOR"   # Competitor mention
    TIKTOK = "TIKTOK"           # Signal from TikTok
    TELEGRAM = "TELEGRAM"       # Signal from Telegram
    PRICE_SPIKE = "PRICE_SPIKE" # Accommodation price spike alert


class Platform(str, Enum):
    REDDIT = "reddit"
    TWITTER = "twitter"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    DISCORD = "discord"
    TIKTOK = "tiktok"
    TELEGRAM = "telegram"
    WEB = "web"
    TRUSTPILOT = "trustpilot"


class Signal(BaseModel):
    """A single social listening signal."""
    id: str = Field(description="Unique ID: platform_hash")
    signal_type: SignalType
    platform: Platform
    country: str
    event: str | None = None
    title: str
    content: str
    author: str | None = None
    url: str
    posted_at: datetime | None = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    
    def dedup_key(self) -> str:
        """Key for deduplication — URL is the most reliable."""
        return self.url.lower().strip().rstrip("/")


class TrustpilotReview(BaseModel):
    """A Trustpilot review."""
    reviewer: str
    rating: int = Field(ge=1, le=5)
    title: str
    content: str
    date: str
    url: str = "https://www.trustpilot.com/review/splitstay.travel"
    
    def dedup_key(self) -> str:
        return f"{self.reviewer}_{self.date}_{self.title}".lower()


class Event(BaseModel):
    """An event to monitor."""
    name: str
    location: str
    dates: str
    type: str = "general"
    keywords: list[str] = Field(default_factory=list)


class CountryConfig(BaseModel):
    """Configuration for a country scan."""
    country: str
    country_emoji: str
    events: list[Event]
    platforms: list[str] = Field(default_factory=list)
    subreddits: list[str] = Field(default_factory=list)
    date_range: dict = Field(default_factory=lambda: {
        "start": "2026-06-12",
        "end": "2027-06-30"
    })


class ScanState(BaseModel):
    """State tracking for a scanner."""
    last_scan: str | None = None
    scan_count: int = 0
    known_signal_urls: list[str] = Field(default_factory=list)
    
    def is_known(self, url: str) -> bool:
        return url.lower().strip().rstrip("/") in [
            u.lower().strip().rstrip("/") for u in self.known_signal_urls
        ]
    
    def add_signal(self, url: str):
        normalised = url.lower().strip().rstrip("/")
        if normalised not in [u.lower().strip().rstrip("/") for u in self.known_signal_urls]:
            self.known_signal_urls.append(url)


class TrustpilotState(BaseModel):
    """State tracking for Trustpilot monitor."""
    last_check: str | None = None
    check_count: int = 0
    known_reviews: list[dict] = Field(default_factory=list)
    
    def is_known(self, review: TrustpilotReview) -> bool:
        key = review.dedup_key()
        return any(
            f"{r.get('reviewer','')}_{r.get('date','')}_{r.get('title','')}".lower() == key
            for r in self.known_reviews
        )
