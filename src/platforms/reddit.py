"""Reddit scanner — searches subreddits for accommodation-sharing signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import praw

from src.models import Signal, SignalType, Platform, Event

logger = logging.getLogger(__name__)

# Keywords that indicate someone is looking to share accommodation
SEEKING_KEYWORDS = [
    "looking for roommate", "share accommodation", "share a room",
    "split hotel", "split airbnb", "split the cost", "share stay",
    "looking for someone to share", "anyone want to share",
    "need a roommate", "room share", "hostel mate",
    "share an apartment", "share housing", "split rent",
    "anyone sharing", "who wants to share", "looking to share",
    "share a place", "share accom", "splitting costs",
]

OFFERING_KEYWORDS = [
    "have a spare bed", "extra space", "room available",
    "spare room", "looking for someone to fill", "empty bed",
    "have space in", "bed available", "have room for",
    "offering a spot", "space in my airbnb",
]

COST_PAIN_KEYWORDS = [
    "so expensive", "prices are insane", "can't afford",
    "accommodation prices", "hotel prices crazy", "airbnb too expensive",
    "ridiculous prices", "price gouging", "way too much",
    "sold out everywhere", "no affordable", "robbery",
]

GROUP_FORMING_KEYWORDS = [
    "group chat", "whatsapp group", "discord server",
    "group of us", "anyone else going", "meet up",
    "looking for a group", "forming a group", "travel group",
    "carpool and share", "festival group", "camp together",
]


class RedditScanner:
    """Scans Reddit for accommodation-sharing signals."""
    
    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self.reddit.read_only = True
    
    def scan_subreddit(
        self,
        subreddit_name: str,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
        limit: int = 100,
    ) -> list[Signal]:
        """Scan a subreddit for relevant signals."""
        signals = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            
            # Search with event-specific keywords
            for event in events:
                for keyword in event.keywords[:3]:  # Top 3 keywords per event
                    query = f"{keyword} (share OR split OR roommate OR accommodation)"
                    try:
                        for submission in subreddit.search(
                            query, time_filter="month", limit=limit // len(events)
                        ):
                            created = datetime.fromtimestamp(
                                submission.created_utc, tz=timezone.utc
                            )
                            if created < cutoff:
                                continue
                            
                            signal = self._classify_submission(
                                submission, event, country, created
                            )
                            if signal:
                                signals.append(signal)
                    except Exception as e:
                        logger.warning(f"Search failed for '{query}' in r/{subreddit_name}: {e}")
            
            # Also scan recent posts with general accommodation keywords
            general_queries = [
                "share accommodation", "split hotel", "roommate festival",
                "share airbnb", "looking to share stay",
            ]
            for query in general_queries:
                try:
                    for submission in subreddit.search(
                        query, time_filter="month", limit=20
                    ):
                        created = datetime.fromtimestamp(
                            submission.created_utc, tz=timezone.utc
                        )
                        if created < cutoff:
                            continue
                        
                        signal = self._classify_submission(
                            submission, None, country, created
                        )
                        if signal:
                            signals.append(signal)
                except Exception as e:
                    logger.warning(f"General search failed in r/{subreddit_name}: {e}")
            
        except Exception as e:
            logger.error(f"Failed to scan r/{subreddit_name}: {e}")
        
        # Deduplicate by URL
        seen = set()
        unique = []
        for s in signals:
            key = s.dedup_key()
            if key not in seen:
                seen.add(key)
                unique.append(s)
        
        return unique
    
    def _classify_submission(
        self,
        submission,
        event: Event | None,
        country: str,
        created: datetime,
    ) -> Signal | None:
        """Classify a Reddit submission as a signal type."""
        text = f"{submission.title} {submission.selftext}".lower()
        
        # Determine signal type
        signal_type = None
        if any(kw in text for kw in SEEKING_KEYWORDS):
            signal_type = SignalType.SEEKING
        elif any(kw in text for kw in OFFERING_KEYWORDS):
            signal_type = SignalType.OFFERING
        elif any(kw in text for kw in COST_PAIN_KEYWORDS):
            signal_type = SignalType.COST_PAIN
        elif any(kw in text for kw in GROUP_FORMING_KEYWORDS):
            signal_type = SignalType.GROUP_FORMING
        
        if not signal_type:
            return None
        
        # Build content preview (first 300 chars)
        content = submission.selftext[:300]
        if len(submission.selftext) > 300:
            content += "…"
        
        return Signal(
            id=f"reddit_{submission.id}",
            signal_type=signal_type,
            platform=Platform.REDDIT,
            country=country,
            event=event.name if event else None,
            title=submission.title,
            content=content,
            author=f"u/{submission.author}" if submission.author else None,
            url=f"https://reddit.com{submission.permalink}",
            posted_at=created,
        )
