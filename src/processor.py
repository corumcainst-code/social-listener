"""Signal processor — deduplication, classification, qualification and filtering."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from src.models import Event, Signal, ScanState
from src.qualifier import SignalQualification, build_event_lookup, qualify_signal

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStats:
    """Human-readable lead scoring stats for Slack diagnostics."""

    input_signals: int = 0
    scored_candidates: int = 0
    hot_leads: int = 0
    warm_leads: int = 0
    low_quality_leads: int = 0
    qualified_new_signals: int = 0
    filtered_known: int = 0
    filtered_old: int = 0
    filtered_empty: int = 0
    filtered_duplicate: int = 0
    filtered_low_quality: int = 0
    lead_type_counts: dict[str, int] = field(default_factory=dict)
    suggested_owner_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_signals": self.input_signals,
            "scored_candidates": self.scored_candidates,
            "hot_leads": self.hot_leads,
            "warm_leads": self.warm_leads,
            "low_quality_leads": self.low_quality_leads,
            "qualified_new_signals": self.qualified_new_signals,
            "filtered_known": self.filtered_known,
            "filtered_old": self.filtered_old,
            "filtered_empty": self.filtered_empty,
            "filtered_duplicate": self.filtered_duplicate,
            "filtered_low_quality": self.filtered_low_quality,
            "lead_type_counts": self.lead_type_counts,
            "suggested_owner_counts": self.suggested_owner_counts,
        }


def lead_heat(score: int) -> str:
    """Convert a 0-100 score into a simple human lead heat label."""
    if score >= 80:
        return "Hot"
    if score >= 60:
        return "Warm"
    return "Low"


def suggested_owner_for_qualification(qualification: SignalQualification) -> str:
    """Suggest who should review a qualified lead first."""
    label = (qualification.label or "").lower()
    lead_type = (qualification.lead_type or "").lower()
    vertical = (qualification.vertical or "").lower()

    if any(term in lead_type for term in ["community", "group"]):
        return "Darwin"
    if any(term in lead_type for term in ["accommodation", "cost pain", "seeking"]):
        return "Darwin"
    if any(term in label for term in ["brand", "competitor"]):
        return "Corum/Ruben"
    if vertical == "hyrox" and qualification.score >= 80:
        return "Darwin"
    if qualification.score >= 80:
        return "Corum/Ruben"
    return "Review"


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


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
        self.last_stats = ProcessingStats()

    def process(self, signals: list[Signal]) -> list[Signal]:
        """
        Filter, qualify and deduplicate signals.

        Important: this method does not add URLs to state.
        State is updated only after Slack confirms that every signal was posted,
        so a temporary Slack failure does not silently lose leads.
        """
        self.last_stats = ProcessingStats(input_signals=len(signals))
        new_signals: list[Signal] = []
        seen_batch_keys: set[str] = set()

        for signal in signals:
            # Skip if already known from a previous successful Slack post.
            if self.state.is_known(signal.url):
                self.last_stats.filtered_known += 1
                logger.debug("Skipping known signal: %s", signal.url)
                continue

            # Skip if too old.
            if signal.posted_at and signal.posted_at < self.cutoff:
                self.last_stats.filtered_old += 1
                logger.debug("Skipping old signal (%s): %s", signal.posted_at, signal.url)
                continue

            # Skip if empty content.
            if not signal.title and not signal.content:
                self.last_stats.filtered_empty += 1
                continue

            # Skip duplicate URLs within this batch.
            dedup_key = signal.dedup_key()
            if dedup_key in seen_batch_keys:
                self.last_stats.filtered_duplicate += 1
                continue

            event = self.event_lookup.get((signal.event or "").lower().strip())
            qualification = qualify_signal(signal, event=event, min_score=self.min_score)
            self.last_stats.scored_candidates += 1
            _increment(self.last_stats.lead_type_counts, qualification.lead_type or "Unclear")
            _increment(self.last_stats.suggested_owner_counts, suggested_owner_for_qualification(qualification))

            heat = lead_heat(qualification.score)
            if heat == "Hot":
                self.last_stats.hot_leads += 1
            elif heat == "Warm":
                self.last_stats.warm_leads += 1
            else:
                self.last_stats.low_quality_leads += 1

            if not qualification.should_post:
                self.last_stats.filtered_low_quality += 1
                logger.info(
                    "Holding back signal score=%s heat=%s label=%s title=%s",
                    qualification.score,
                    heat,
                    qualification.label,
                    signal.title[:80],
                )
                continue

            seen_batch_keys.add(dedup_key)
            self.last_stats.qualified_new_signals += 1
            new_signals.append(signal)

        logger.info(
            "Processed %s signals → %s qualified new "
            "(known=%s old=%s empty=%s duplicate=%s low_quality=%s scored=%s hot=%s warm=%s)",
            self.last_stats.input_signals,
            len(new_signals),
            self.last_stats.filtered_known,
            self.last_stats.filtered_old,
            self.last_stats.filtered_empty,
            self.last_stats.filtered_duplicate,
            self.last_stats.filtered_low_quality,
            self.last_stats.scored_candidates,
            self.last_stats.hot_leads,
            self.last_stats.warm_leads,
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
