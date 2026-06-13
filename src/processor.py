"""Signal processor — deduplication, classification, and filtering."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.models import Signal, ScanState

logger = logging.getLogger(__name__)


class SignalProcessor:
    """Processes raw signals: deduplicates, filters by recency, and validates."""

    def __init__(self, state: ScanState, max_age_days: int = 60):
        self.state = state
        self.max_age_days = max_age_days
        self.cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    def process(self, signals: list[Signal]) -> list[Signal]:
        """
        Filter and deduplicate signals.

        Important: this method does not add URLs to state.
        State is updated only after Slack confirms that every signal was posted,
        so a temporary Slack failure does not silently lose leads.
        """
        new_signals: list[Signal] = []
        seen_batch_keys: set[str] = set()

        for signal in signals:
            # Skip if already known from a previous successful Slack post.
            if self.state.is_known(signal.url):
                logger.debug("Skipping known signal: %s", signal.url)
                continue

            # Skip if too old.
            if signal.posted_at and signal.posted_at < self.cutoff:
                logger.debug("Skipping old signal (%s): %s", signal.posted_at, signal.url)
                continue

            # Skip if empty content.
            if not signal.title and not signal.content:
                continue

            # Skip duplicate URLs within this batch.
            dedup_key = signal.dedup_key()
            if dedup_key in seen_batch_keys:
                continue

            seen_batch_keys.add(dedup_key)
            new_signals.append(signal)

        logger.info(
            "Processed %s signals → %s new (filtered %s duplicates/old)",
            len(signals),
            len(new_signals),
            len(signals) - len(new_signals),
        )

        return new_signals

    def mark_posted(self, signals: list[Signal]) -> None:
        """Mark signals as known after they were successfully posted to Slack."""
        for signal in signals:
            self.state.add_signal(signal.url)

    def trim_state(self, max_urls: int = 5000):
        """Keep state manageable by trimming old URLs."""
        if len(self.state.known_signal_urls) > max_urls:
            self.state.known_signal_urls = self.state.known_signal_urls[-max_urls:]
            logger.info("Trimmed state to %s URLs", max_urls)
