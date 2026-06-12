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
        """Filter and deduplicate signals. Returns only new, valid signals."""
        new_signals = []
        
        for signal in signals:
            # Skip if already known
            if self.state.is_known(signal.url):
                logger.debug(f"Skipping known signal: {signal.url}")
                continue
            
            # Skip if too old
            if signal.posted_at and signal.posted_at < self.cutoff:
                logger.debug(f"Skipping old signal ({signal.posted_at}): {signal.url}")
                continue
            
            # Skip if empty content
            if not signal.title and not signal.content:
                continue
            
            # Skip duplicate URLs within this batch
            if any(s.dedup_key() == signal.dedup_key() for s in new_signals):
                continue
            
            new_signals.append(signal)
            self.state.add_signal(signal.url)
        
        logger.info(
            f"Processed {len(signals)} signals → {len(new_signals)} new "
            f"(filtered {len(signals) - len(new_signals)} duplicates/old)"
        )
        
        return new_signals
    
    def trim_state(self, max_urls: int = 5000):
        """Keep state manageable by trimming old URLs."""
        if len(self.state.known_signal_urls) > max_urls:
            self.state.known_signal_urls = self.state.known_signal_urls[-max_urls:]
            logger.info(f"Trimmed state to {max_urls} URLs")
