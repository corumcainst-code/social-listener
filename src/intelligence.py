"""Lead intelligence helpers for feedback-loop learning.

This module keeps lightweight, human-in-the-loop intelligence separate from
scanner logic. The first version does not auto-learn from Slack clicks; it gives
all posted leads a stable Lead ID, readable lead tags, and clear feedback
instructions so the team can rate lead quality in the feedback tracker.
"""

from __future__ import annotations

import hashlib
import re

from src.models import Event, Signal
from src.qualifier import SignalQualification


def _clean_code(value: str, fallback: str = "LEAD", max_len: int = 10) -> str:
    """Return a short uppercase code safe for Lead IDs."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value or "")[:max_len].upper()
    return cleaned or fallback


def _combined_text(signal: Signal, event: Event | None = None) -> str:
    parts = [
        signal.event or "",
        signal.title or "",
        signal.content or "",
        signal.author or "",
        event.name if event else "",
        event.location if event else "",
        event.type if event else "",
        " ".join(event.keywords) if event else "",
    ]
    return " ".join(part for part in parts if part).lower()


def build_lead_id(
    signal: Signal,
    qualification: SignalQualification,
    event: Event | None = None,
    country: str | None = None,
) -> str:
    """Build a stable, human-readable Lead ID for Slack + feedback tracker.

    Example: UK-HYROX-A82F1C
    """
    country_code = _clean_code(country or signal.country or "XX", fallback="XX", max_len=4)
    vertical_code = _clean_code(qualification.vertical or (event.type if event else "LEAD"), max_len=8)
    seed = "|".join(
        [
            signal.url or "",
            signal.title or "",
            signal.content or "",
            signal.event or "",
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6].upper()
    return f"{country_code}-{vertical_code}-{digest}"


def build_lead_tags(
    signal: Signal,
    qualification: SignalQualification,
    event: Event | None = None,
) -> list[str]:
    """Return readable tags that explain why the lead was flagged."""
    text = _combined_text(signal, event=event)
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    vertical = (qualification.vertical or "").upper()
    if "hyrox" in text or vertical == "HYROX":
        add("HYROX")

    if qualification.future_event is True:
        add("Future event")
    elif qualification.future_event is None:
        add("Date TBC")

    if any(term in text for term in ["accommodation", "accomodation", "hotel", "airbnb", "hostel", "room", "place to stay", "somewhere to stay", "stay near"]):
        add("Accommodation intent")

    if any(term in text for term in ["room share", "share room", "share a room", "share accommodation", "share hotel", "split hotel", "split airbnb", "split the cost", "roommate", "room mate"]):
        add("Room-share intent")

    if any(term in text for term in ["too expensive", "so expensive", "hotel prices", "accommodation prices", "sold out", "budget", "cheap", "cheaper"]):
        add("Cost pain")

    if any(term in text for term in ["group", "group chat", "whatsapp", "telegram", "discord", "facebook group", "community", "join"]):
        add("Group/community signal")

    if any(term in text for term in ["looking for", "need", "anyone have", "anyone got", "does anyone", "can anyone", "in search of", "recommend"]):
        add("Seeking signal")

    platform = signal.platform.value.title()
    add(platform)

    return tags or ["General lead"]


def source_context_label(signal: Signal) -> str:
    """Explain the likely source context in a human-friendly way."""
    platform = signal.platform.value.lower()
    url = (signal.url or "").lower()

    if platform == "facebook":
        if "/events" in url:
            return "Facebook event page"
        if "/groups" in url:
            return "Facebook group/community"
        return "Facebook public/searchable result"

    if platform == "instagram":
        return "Instagram public/searchable post or caption"

    if platform == "tiktok":
        return "TikTok public/searchable post or caption"

    if platform == "telegram":
        return "Telegram public channel/group result"

    if platform == "discord":
        return "Discord public community/invite result"

    if platform == "twitter":
        return "Twitter/X public post"

    if platform == "reddit":
        return "Reddit public post/comment"

    return f"{signal.platform.value.title()} public/searchable result"


def feedback_instruction(lead_id: str) -> str:
    """Instruction shown in Slack so humans can close the feedback loop."""
    return (
        "Please add this Lead ID to the *SplitStay Lead Intelligence Feedback Tracker* "
        "and rate it as: High quality / Medium quality / Low quality / Not relevant."
    )
