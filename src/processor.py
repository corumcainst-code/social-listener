"""Signal processor — deduplication, classification, qualification and filtering."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from src.models import Event, Signal, ScanState
from src.qualifier import build_event_lookup, qualify_signal

logger = logging.getLogger(__name__)


class SignalProcessor:
    """Processes raw signals before they are allowed into Slack."""

    def __init__(
        self,
        state: ScanState,
        max_age_days: int = 60,
        events: list[Event] | None = None,
    ):
        self.state = state
        self.max_age_days = max_age_days
        self.cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        self.event_lookup = build_event_lookup(events or [])
        self.min_score = int(os.getenv("QUALIFY_MIN_SCORE", "60"))

    def process(self, signals: list[Signal]) -> list[Signal]:
        """
        Filter, qualify and deduplicate signals.

        Important: this method does not add URLs to state.
        State is updated only after Slack confirms that every signal was posted,
        so a temporary Slack failure does not silently lose leads.
        """
        new_signals: list[Signal] = []
        seen_batch_keys: set[str] = set()
        filtered_known = 0
        filtered_old = 0
        filtered_empty = 0
        filtered_duplicate = 0
        filtered_low_quality = 0

        for signal in signals:
            # Skip if already known from a previous successful Slack post.
            if self.state.is_known(signal.url):
                filtered_known += 1
                logger.debug("Skipping known signal: %s", signal.url)
                continue

            # Skip if too old.
            if signal.posted_at and signal.posted_at < self.cutoff:
                filtered_old += 1
                logger.debug("Skipping old signal (%s): %s", signal.posted_at, signal.url)
                continue

            # Skip if empty content.
            if not signal.title and not signal.content:
                filtered_empty += 1
                continue

            # Skip duplicate URLs within this batch.
            dedup_key = signal.dedup_key()
            if dedup_key in seen_batch_keys:
                filtered_duplicate += 1
                continue

            event = self.event_lookup.get((signal.event or "").lower().strip())
            qualification = qualify_signal(signal, event=event, min_score=self.min_score)
            if not qualification.should_post:
                filtered_low_quality += 1
                logger.info(
                    "Holding back signal score=%s label=%s title=%s",
                    qualification.score,
                    qualification.label,
                    signal.title[:80],
                )
                continue

            seen_batch_keys.add(dedup_key)
            new_signals.append(signal)

        logger.info(
            "Processed %s signals → %s qualified new "
            "(known=%s old=%s empty=%s duplicate=%s low_quality=%s)",
            len(signals),
            len(new_signals),
            filtered_known,
            filtered_old,
            filtered_empty,
            filtered_duplicate,
            filtered_low_quality,
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
