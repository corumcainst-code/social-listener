"""Reddit scanner — searches subreddits for accommodation-sharing signals."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import praw

from src.classifier import classify
from src.models import Signal, Platform, Event
from src.platforms.base import Scanner

logger = logging.getLogger(__name__)


class RedditScanner(Scanner):
    """Scans Reddit for accommodation-sharing signals.

    PRAW is synchronous, so blocking calls are wrapped with
    ``asyncio.to_thread`` to keep the async interface non-blocking.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        subreddits: list[str],
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._subreddits = subreddits

    @property
    def name(self) -> str:
        return "Reddit"

    async def scan(
        self,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
    ) -> list[Signal]:
        """Scan configured subreddits for signals (runs PRAW in a thread)."""
        return await asyncio.to_thread(
            self._scan_sync, events, country, max_age_days
        )

    # ------------------------------------------------------------------
    # Private helpers (all synchronous — run inside to_thread)
    # ------------------------------------------------------------------

    def _scan_sync(
        self,
        events: list[Event],
        country: str,
        max_age_days: int,
    ) -> list[Signal]:
        """Synchronous scanning logic — creates and discards the PRAW client."""
        reddit = praw.Reddit(
            client_id=self._client_id,
            client_secret=self._client_secret,
            user_agent=self._user_agent,
        )
        reddit.read_only = True

        signals: list[Signal] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        for subreddit_name in self._subreddits:
            try:
                sub_signals = self._scan_subreddit(
                    reddit, subreddit_name, events, country, cutoff
                )
                signals.extend(sub_signals)
                logger.info(f"  r/{subreddit_name}: {len(sub_signals)} signals")
            except Exception as e:
                logger.error(f"  r/{subreddit_name} failed: {e}")

        return self._deduplicate(signals)

    def _scan_subreddit(
        self,
        reddit: praw.Reddit,
        subreddit_name: str,
        events: list[Event],
        country: str,
        cutoff: datetime,
        limit: int = 100,
    ) -> list[Signal]:
        signals: list[Signal] = []
        subreddit = reddit.subreddit(subreddit_name)

        # Event-specific searches
        for event in events:
            for keyword in event.keywords[:3]:
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
                    logger.warning(
                        f"Search failed for '{query}' in r/{subreddit_name}: {e}"
                    )

        # General accommodation keyword searches
        for query in [
            "share accommodation",
            "split hotel",
            "roommate festival",
            "share airbnb",
            "looking to share stay",
        ]:
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

        return signals

    @staticmethod
    def _classify_submission(
        submission,
        event: Event | None,
        country: str,
        created: datetime,
    ) -> Signal | None:
        text = f"{submission.title} {submission.selftext}"
        signal_type = classify(text, platform="reddit")

        if not signal_type:
            return None

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
