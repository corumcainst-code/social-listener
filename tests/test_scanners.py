"""Tests for the unified Scanner interface.

The key win of Fix 1: we can test the full scan → process → post pipeline
with a FakeScanner — no PRAW, httpx, or filesystem mocking needed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.models import (
    CountryConfig,
    Event,
    ScanState,
    Signal,
    SignalType,
    Platform,
)
from src.platforms.base import Scanner
from src.processor import SignalProcessor


# ------------------------------------------------------------------
# Fake scanner — plugs straight into the pipeline
# ------------------------------------------------------------------

class FakeScanner(Scanner):
    """Returns canned signals for testing."""

    def __init__(self, signals: list[Signal] | None = None):
        self._signals = signals or []

    @property
    def name(self) -> str:
        return "FakeScanner"

    async def scan(
        self,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
    ) -> list[Signal]:
        return list(self._signals)  # defensive copy


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_signal(
    id: str,
    url: str,
    signal_type: SignalType = SignalType.SEEKING,
    platform: Platform = Platform.REDDIT,
    country: str = "spain",
) -> Signal:
    return Signal(
        id=id,
        signal_type=signal_type,
        platform=platform,
        country=country,
        title=f"Signal {id}",
        content=f"Content for {id}",
        url=url,
        posted_at=datetime.now(timezone.utc),
    )


def _make_event(name: str = "Test Fest", location: str = "Barcelona") -> Event:
    return Event(
        name=name,
        location=location,
        dates="2026-07-01 – 2026-07-03",
        keywords=["test", "fest"],
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_fake_scanner_implements_interface():
    """FakeScanner should satisfy the Scanner ABC."""
    scanner = FakeScanner()
    assert isinstance(scanner, Scanner)
    assert scanner.name == "FakeScanner"


def test_fake_scanner_returns_signals():
    """scan() should return the canned signals."""
    signals = [_make_signal("s1", "https://example.com/1")]
    scanner = FakeScanner(signals)

    result = asyncio.run(
        scanner.scan([_make_event()], "spain")
    )
    assert len(result) == 1
    assert result[0].id == "s1"


def test_pipeline_with_fake_scanner():
    """Full pipeline: fake scanner → processor → new signals only."""
    known_url = "https://example.com/known"
    new_url = "https://example.com/new"

    scanner = FakeScanner([
        _make_signal("known", known_url),
        _make_signal("new", new_url),
    ])

    # State already knows one URL
    state = ScanState(known_signal_urls=[known_url])
    processor = SignalProcessor(state, max_age_days=60)

    raw = asyncio.run(scanner.scan([_make_event()], "spain"))
    new = processor.process(raw)

    assert len(new) == 1
    assert new[0].id == "new"
    assert state.is_known(new_url)  # processor added it


def test_pipeline_deduplicates_across_scanners():
    """Signals with the same URL from different scanners are deduplicated."""
    url = "https://example.com/shared"

    scanner_a = FakeScanner([_make_signal("a", url, platform=Platform.REDDIT)])
    scanner_b = FakeScanner([_make_signal("b", url, platform=Platform.TWITTER)])

    state = ScanState()
    processor = SignalProcessor(state, max_age_days=60)

    all_signals = []
    for scanner in [scanner_a, scanner_b]:
        all_signals.extend(asyncio.run(scanner.scan([_make_event()], "spain")))

    new = processor.process(all_signals)
    assert len(new) == 1  # Only the first one survives


def test_empty_scanner():
    """A scanner returning nothing shouldn't break the pipeline."""
    scanner = FakeScanner([])
    state = ScanState()
    processor = SignalProcessor(state, max_age_days=60)

    raw = asyncio.run(scanner.scan([_make_event()], "spain"))
    new = processor.process(raw)

    assert len(new) == 0


def test_web_search_scanner_rejects_unknown_platform():
    """WebSearchScanner should reject unknown platform names."""
    from src.platforms.web_search import WebSearchScanner

    try:
        WebSearchScanner("myspace")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown platform" in str(e)


def test_web_search_scanner_name():
    """WebSearchScanner.name should be the platform name, title-cased."""
    from src.platforms.web_search import WebSearchScanner

    scanner = WebSearchScanner("facebook")
    assert scanner.name == "Facebook"
    assert isinstance(scanner, Scanner)


def test_twitter_scanner_is_scanner():
    """TwitterScanner should satisfy the Scanner ABC."""
    from src.platforms.twitter import TwitterScanner

    scanner = TwitterScanner()
    assert isinstance(scanner, Scanner)
    assert scanner.name == "Twitter/X"


def test_multiple_scanners_uniform_loop():
    """Simulate the exact loop from scanner.py — works with any Scanner."""
    events = [_make_event()]
    scanners: list[Scanner] = [
        FakeScanner([_make_signal("r1", "https://reddit.com/1")]),
        FakeScanner([_make_signal("t1", "https://x.com/1")]),
        FakeScanner([]),  # Empty — some platforms return nothing
        FakeScanner([_make_signal("d1", "https://discord.gg/1")]),
    ]

    all_signals = []
    for scanner in scanners:
        signals = asyncio.run(scanner.scan(events, "spain"))
        all_signals.extend(signals)

    state = ScanState()
    processor = SignalProcessor(state, max_age_days=60)
    new = processor.process(all_signals)

    assert len(new) == 3
