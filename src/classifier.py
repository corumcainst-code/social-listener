"""Centralised signal classifier — single source of truth for all keywords.

Every scanner calls ``classify(text, platform)`` instead of maintaining its
own keyword lists.  Adding a keyword here automatically applies across
Reddit, Twitter/X, Facebook, Instagram, Discord, TikTok and Telegram.

ADR: Twitter intentionally checks only SEEKING + COST_PAIN categories.
Tweets are too short for reliable OFFERING or GROUP_FORMING detection,
so we keep the set narrow to minimise false positives.
"""

from __future__ import annotations

from src.models import SignalType


# ── Canonical keyword sets ────────────────────────────────────────────
# One place to add, remove, or tweak — no more cross-file drift.

SEEKING_KEYWORDS: list[str] = [
    "looking for roommate", "share accommodation", "share a room",
    "split hotel", "split airbnb", "split the cost", "share stay",
    "looking for someone to share", "anyone want to share",
    "need a roommate", "room share", "hostel mate",
    "share an apartment", "share housing", "split rent",
    "anyone sharing", "who wants to share", "looking to share",
    "share a place", "share accom", "splitting costs",
    "roommate",
]

OFFERING_KEYWORDS: list[str] = [
    "have a spare bed", "extra space", "room available",
    "spare room", "looking for someone to fill", "empty bed",
    "have space in", "bed available", "have room for",
    "offering a spot", "space in my airbnb", "room for",
]

COST_PAIN_KEYWORDS: list[str] = [
    "so expensive", "prices are insane", "can't afford",
    "accommodation prices", "hotel prices crazy", "airbnb too expensive",
    "ridiculous prices", "price gouging", "way too much",
    "sold out everywhere", "no affordable", "robbery",
]

GROUP_FORMING_KEYWORDS: list[str] = [
    "group chat", "whatsapp group", "discord server",
    "group of us", "anyone else going", "meet up",
    "looking for a group", "forming a group", "travel group",
    "carpool and share", "festival group", "camp together",
    "travel together",
]


# ── Per-platform category rules ──────────────────────────────────────

_ALL_CATEGORIES: list[tuple[list[str], SignalType]] = [
    (SEEKING_KEYWORDS, SignalType.SEEKING),
    (OFFERING_KEYWORDS, SignalType.OFFERING),
    (COST_PAIN_KEYWORDS, SignalType.COST_PAIN),
    (GROUP_FORMING_KEYWORDS, SignalType.GROUP_FORMING),
]

# ADR: Twitter — SEEKING + COST_PAIN only (see module docstring)
_TWITTER_CATEGORIES: list[tuple[list[str], SignalType]] = [
    (SEEKING_KEYWORDS, SignalType.SEEKING),
    (COST_PAIN_KEYWORDS, SignalType.COST_PAIN),
]

_PLATFORM_OVERRIDES: dict[str, list[tuple[list[str], SignalType]]] = {
    "twitter": _TWITTER_CATEGORIES,
}


# ── Public API ────────────────────────────────────────────────────────

def classify(text: str, platform: str | None = None) -> SignalType | None:
    """Classify *text* into a ``SignalType`` using the canonical keyword sets.

    Parameters
    ----------
    text:
        Raw text to classify (lowercased internally).
    platform:
        Optional platform name (e.g. ``"twitter"``).  Controls which
        signal-type categories are checked — see ``_PLATFORM_OVERRIDES``.

    Returns
    -------
    The first matching ``SignalType``, or ``None`` if no keywords match.
    Priority order: SEEKING → OFFERING → COST_PAIN → GROUP_FORMING.
    """
    text_lower = text.lower()
    categories = _PLATFORM_OVERRIDES.get(platform, _ALL_CATEGORIES)

    for keywords, signal_type in categories:
        if any(kw in text_lower for kw in keywords):
            return signal_type

    return None
