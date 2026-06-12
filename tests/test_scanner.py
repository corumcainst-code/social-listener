"""Basic tests for the social listener."""

import json
from pathlib import Path

from src.models import (
    Signal, SignalType, Platform, ScanState, 
    TrustpilotReview, TrustpilotState, CountryConfig, Event,
)
from src.processor import SignalProcessor


def test_signal_dedup_key():
    """Signals with same URL should have the same dedup key."""
    s1 = Signal(
        id="test1", signal_type=SignalType.SEEKING, platform=Platform.REDDIT,
        country="spain", title="Test", content="Test", url="https://reddit.com/r/test/1"
    )
    s2 = Signal(
        id="test2", signal_type=SignalType.OFFERING, platform=Platform.REDDIT,
        country="uk", title="Other", content="Other", url="https://reddit.com/r/test/1/"
    )
    assert s1.dedup_key() == s2.dedup_key()


def test_scan_state_dedup():
    """State should correctly track known signals."""
    state = ScanState()
    assert not state.is_known("https://reddit.com/r/test/1")
    
    state.add_signal("https://reddit.com/r/test/1")
    assert state.is_known("https://reddit.com/r/test/1")
    assert state.is_known("https://reddit.com/r/test/1/")  # Trailing slash


def test_processor_filters_known():
    """Processor should filter out already-known signals."""
    state = ScanState(known_signal_urls=["https://reddit.com/r/test/1"])
    processor = SignalProcessor(state)
    
    signals = [
        Signal(
            id="known", signal_type=SignalType.SEEKING, platform=Platform.REDDIT,
            country="spain", title="Known", content="Known", url="https://reddit.com/r/test/1"
        ),
        Signal(
            id="new", signal_type=SignalType.SEEKING, platform=Platform.REDDIT,
            country="spain", title="New", content="New", url="https://reddit.com/r/test/2"
        ),
    ]
    
    result = processor.process(signals)
    assert len(result) == 1
    assert result[0].id == "new"


def test_processor_deduplicates_batch():
    """Processor should deduplicate within a batch."""
    state = ScanState()
    processor = SignalProcessor(state)
    
    signals = [
        Signal(
            id="a", signal_type=SignalType.SEEKING, platform=Platform.REDDIT,
            country="spain", title="First", content="First", url="https://reddit.com/r/test/1"
        ),
        Signal(
            id="b", signal_type=SignalType.OFFERING, platform=Platform.REDDIT,
            country="spain", title="Dupe", content="Dupe", url="https://reddit.com/r/test/1"
        ),
    ]
    
    result = processor.process(signals)
    assert len(result) == 1


def test_trustpilot_review_dedup():
    """Trustpilot state should detect known reviews."""
    state = TrustpilotState(
        known_reviews=[{
            "reviewer": "John", "date": "2026-06-01", "title": "Great service"
        }]
    )
    
    known_review = TrustpilotReview(
        reviewer="John", rating=5, title="Great service",
        content="Loved it", date="2026-06-01"
    )
    new_review = TrustpilotReview(
        reviewer="Jane", rating=4, title="Good stuff",
        content="Nice", date="2026-06-10"
    )
    
    assert state.is_known(known_review)
    assert not state.is_known(new_review)


def test_country_configs_exist():
    """All 8 country configs should exist and be valid."""
    config_dir = Path(__file__).parent.parent / "config"
    countries = ["spain", "uk", "us", "brazil", "germany", "taiwan", "china", "portugal"]
    
    for country in countries:
        path = config_dir / f"{country}.json"
        assert path.exists(), f"Missing config: {country}.json"
        
        with open(path) as f:
            data = json.load(f)
        
        config = CountryConfig(**data)
        assert config.country == country
        assert len(config.events) > 0, f"{country} has no events"
        assert config.date_range["start"] == "2026-06-12"
        assert config.date_range["end"] == "2027-06-30"


def test_signal_types():
    """All signal types should be valid."""
    assert SignalType.SEEKING.value == "SEEKING"
    assert SignalType.OFFERING.value == "OFFERING"
    assert SignalType.COST_PAIN.value == "COST_PAIN"
    assert SignalType.BRAND.value == "BRAND"
    assert SignalType.PRICE_SPIKE.value == "PRICE_SPIKE"
