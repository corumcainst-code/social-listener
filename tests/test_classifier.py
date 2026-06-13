"""Tests for the centralised classifier module.

Verifies that:
1. Each signal type matches on its canonical keywords
2. Twitter only returns SEEKING or COST_PAIN (ADR)
3. Unknown text returns None
4. Classification is case-insensitive
5. Adding keywords in one place affects all platforms
"""

from src.classifier import (
    classify,
    SEEKING_KEYWORDS,
    OFFERING_KEYWORDS,
    COST_PAIN_KEYWORDS,
    GROUP_FORMING_KEYWORDS,
)
from src.models import SignalType


# ── Basic classification ──────────────────────────────────────────────

def test_classify_seeking():
    """Text with seeking keywords should return SEEKING."""
    assert classify("I'm looking for roommate for Primavera") == SignalType.SEEKING
    assert classify("Anyone want to share a room at Sonar?") == SignalType.SEEKING
    assert classify("Need to split hotel costs") == SignalType.SEEKING


def test_classify_offering():
    """Text with offering keywords should return OFFERING."""
    assert classify("I have a spare bed in my Airbnb") == SignalType.OFFERING
    assert classify("Room available near the venue") == SignalType.OFFERING
    assert classify("Bed available for 2 nights") == SignalType.OFFERING


def test_classify_cost_pain():
    """Text with cost-pain keywords should return COST_PAIN."""
    assert classify("Hotel prices are insane for this weekend") == SignalType.COST_PAIN
    assert classify("I can't afford accommodation any more") == SignalType.COST_PAIN
    assert classify("Airbnb too expensive near the stadium") == SignalType.COST_PAIN


def test_classify_group_forming():
    """Text with group-forming keywords should return GROUP_FORMING."""
    assert classify("Started a whatsapp group for the festival") == SignalType.GROUP_FORMING
    assert classify("Anyone else going? Let's meet up") == SignalType.GROUP_FORMING
    assert classify("We should camp together this year") == SignalType.GROUP_FORMING


def test_classify_no_match():
    """Unrelated text should return None."""
    assert classify("The weather is nice today") is None
    assert classify("Check out this new restaurant") is None
    assert classify("") is None


# ── Case insensitivity ────────────────────────────────────────────────

def test_classify_case_insensitive():
    """Keywords should match regardless of case."""
    assert classify("LOOKING FOR ROOMMATE") == SignalType.SEEKING
    assert classify("Prices Are Insane") == SignalType.COST_PAIN
    assert classify("Spare Room available") == SignalType.OFFERING


# ── Priority order ────────────────────────────────────────────────────

def test_classify_priority_seeking_over_cost():
    """When text matches both SEEKING and COST_PAIN, SEEKING wins (first in list)."""
    text = "Looking for roommate because prices are insane"
    assert classify(text) == SignalType.SEEKING


def test_classify_priority_offering_over_group():
    """When text matches both OFFERING and GROUP_FORMING, OFFERING wins."""
    text = "Spare room in our festival group"
    assert classify(text) == SignalType.OFFERING


# ── Twitter ADR ───────────────────────────────────────────────────────

def test_twitter_seeking():
    """Twitter should detect SEEKING signals."""
    assert classify("Looking for roommate for Glastonbury", platform="twitter") == SignalType.SEEKING


def test_twitter_cost_pain():
    """Twitter should detect COST_PAIN signals."""
    assert classify("Hotel prices are insane for F1 weekend", platform="twitter") == SignalType.COST_PAIN


def test_twitter_no_offering():
    """Twitter should NOT return OFFERING (ADR: too noisy for short text)."""
    assert classify("I have a spare bed in my Airbnb", platform="twitter") is None


def test_twitter_no_group_forming():
    """Twitter should NOT return GROUP_FORMING (ADR: too noisy for short text)."""
    assert classify("Started a whatsapp group for the festival", platform="twitter") is None


# ── Platform passthrough ──────────────────────────────────────────────

def test_reddit_uses_full_categories():
    """Reddit (and any non-twitter platform) should check all 4 categories."""
    assert classify("Spare room available", platform="reddit") == SignalType.OFFERING
    assert classify("Whatsapp group for festival", platform="reddit") == SignalType.GROUP_FORMING


def test_facebook_uses_full_categories():
    """Facebook should check all 4 categories."""
    assert classify("Spare room available", platform="facebook") == SignalType.OFFERING


def test_unknown_platform_uses_full():
    """An unknown platform should default to full categories."""
    assert classify("Spare room available", platform="unknown_platform") == SignalType.OFFERING


def test_none_platform_uses_full():
    """platform=None should use full categories."""
    assert classify("Spare room available", platform=None) == SignalType.OFFERING


# ── Keyword set sanity ────────────────────────────────────────────────

def test_keyword_sets_not_empty():
    """All keyword sets should have entries."""
    assert len(SEEKING_KEYWORDS) > 0
    assert len(OFFERING_KEYWORDS) > 0
    assert len(COST_PAIN_KEYWORDS) > 0
    assert len(GROUP_FORMING_KEYWORDS) > 0


def test_no_duplicate_keywords_within_sets():
    """No keyword set should contain duplicates."""
    for name, keywords in [
        ("SEEKING", SEEKING_KEYWORDS),
        ("OFFERING", OFFERING_KEYWORDS),
        ("COST_PAIN", COST_PAIN_KEYWORDS),
        ("GROUP_FORMING", GROUP_FORMING_KEYWORDS),
    ]:
        assert len(keywords) == len(set(keywords)), f"Duplicates in {name}"
