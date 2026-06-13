"""Signal qualification and priority scoring before Slack posting.

This module is the quality gate between raw social listening results and Slack.
It keeps the scanner broad, but ensures Darwin only sees structured, future-event
opportunities that are likely to matter for SplitStay.

Main goals:
- ignore known-past events
- reject signals that mention an explicitly past event date
- prioritise HYROX and other large event/community opportunities
- require accommodation, group-forming, community, cost-pain, brand or competitor intent
- score signals before Slack
"""

from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.models import Event, Signal, SignalType


MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

HYROX_KEYWORDS = [
    "hyrox",
    "hyrox london",
    "hyrox manchester",
    "hyrox birmingham",
    "hyrox glasgow",
    "hyrox madrid",
    "hyrox barcelona",
    "hyrox valencia",
    "hyrox lisbon",
    "hyrox porto",
    "hyrox hamburg",
    "hyrox berlin",
    "hyrox munich",
    "hyrox frankfurt",
    "hyrox taipei",
    "hyrox shanghai",
    "hyrox beijing",
    "hyrox hong kong",
    "hyrox sao paulo",
    "hyrox rio",
    "hyrox miami",
    "hyrox new york",
    "hyrox chicago",
    "hyrox houston",
    "hyrox dallas",
    "fitness race",
    "hybrid fitness race",
    "world series of fitness racing",
]

ACCOMMODATION_KEYWORDS = [
    "accommodation",
    "accomodation",
    "hotel",
    "airbnb",
    "hostel",
    "room",
    "rooms",
    "roommate",
    "room mate",
    "room share",
    "share room",
    "share a room",
    "share accommodation",
    "share accom",
    "share hotel",
    "split hotel",
    "split airbnb",
    "split the cost",
    "place to stay",
    "somewhere to stay",
    "stay near",
    "stay in",
    "bed",
    "spare bed",
    "apartment",
    "flat",
    "house",
    "sofa",
    "couch",
    "lodging",
    "booking",
    "near the venue",
    "near venue",
    "walking distance",
]

SEEKING_KEYWORDS = [
    "looking for",
    "need",
    "needed",
    "anyone have",
    "anyone got",
    "anyone know",
    "does anyone",
    "can anyone",
    "in search of",
    "iso",
    "wanted",
    "trying to find",
    "recommend",
    "recommendations",
    "available from",
    "availability",
]

COMMUNITY_KEYWORDS = [
    "group",
    "group chat",
    "whatsapp",
    "telegram",
    "discord",
    "facebook group",
    "community",
    "members",
    "join",
    "athlete group",
    "race group",
    "travel group",
]

COST_PAIN_KEYWORDS = [
    "too expensive",
    "so expensive",
    "prices are insane",
    "hotel prices",
    "accommodation prices",
    "airbnb too expensive",
    "sold out",
    "sold out everywhere",
    "no affordable",
    "price gouging",
    "budget",
    "cheap",
    "cheaper",
]

BRAND_KEYWORDS = [
    "splitstay",
    "split stay",
    "splitstay.travel",
]

COMPETITOR_KEYWORDS = [
    "airbnb",
    "booking.com",
    "hostelworld",
    "couchsurfing",
    "spare room",
    "spareroom",
    "vrbo",
]

NOISE_KEYWORDS = [
    "training plan",
    "workout",
    "gym session",
    "race report",
    "recap",
    "results",
    "leaderboard",
    "medal",
    "personal best",
    " pb ",
    "photo dump",
    "highlights",
    "nutrition",
    "shoes",
    "coaching",
    "ticket only",
    "bib only",
    "selling ticket",
    "ticket for sale",
]

PAST_CONTEXT_KEYWORDS = [
    "last year",
    "yesterday",
    "already happened",
    "has ended",
    "ended yesterday",
    "event recap",
    "race recap",
    "throwback",
    "memories from",
    "after movie",
    "aftermovie",
    "highlights from",
    "what a weekend",
    "was amazing",
    "was incredible",
    "post event",
    "post-event",
]


@dataclass(frozen=True)
class SignalQualification:
    """The posting decision for one signal."""

    should_post: bool
    score: int
    label: str
    vertical: str
    lead_type: str
    event_date: str | None
    future_event: bool | None
    tag_darwin: bool
    reason: str
    action: str


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _contains_any(text: str, keywords: list[str]) -> bool:
    text_lower = f" {text.lower()} "
    return any(keyword.lower() in text_lower for keyword in keywords)


def _contains_hyrox(text: str) -> bool:
    return _contains_any(text, HYROX_KEYWORDS)


def _normalise_date_text(text: str) -> str:
    """Normalise ordinal day suffixes so date regexes are easier."""
    text = text.lower()
    text = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text)
    return text


def signal_mentions_past_date(text: str, today: date | None = None) -> tuple[bool, str | None]:
    """Detect when a raw signal is about an event/date that has already passed.

    The event config can be broad, for example "HYROX UK 2026-2027 Season".
    Search results can still contain old posts, for example "October 22-26, 2025".
    This function blocks those before Slack, even if the configured season is future.
    """
    if os.getenv("ENABLE_SIGNAL_DATE_SAFETY", "true").lower() in {"0", "false", "no", "off"}:
        return False, None

    today = today or _today()
    cleaned = _normalise_date_text(text)

    if any(term in cleaned for term in PAST_CONTEXT_KEYWORDS):
        return True, "Signal text contains past-event language."

    # Explicit old years are a strong signal that the post is stale.
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", cleaned)]
    old_years = [y for y in years if y < today.year]
    if old_years:
        return True, f"Signal text mentions a past year: {min(old_years)}."

    # Month + optional day/range + year, e.g. "October 22 - 26, 2025".
    month_names = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))
    month_year_pattern = re.compile(
        rf"\b(?P<month>{month_names})\b[^\n\r]{{0,45}}?\b(?P<year>20\d{{2}})\b",
        re.IGNORECASE,
    )

    for match in month_year_pattern.finditer(cleaned):
        month = MONTHS[match.group("month").lower()]
        year = int(match.group("year"))
        if year < today.year:
            return True, f"Signal text mentions a past event date: {match.group(0).strip()}."
        if year == today.year:
            last_day = calendar.monthrange(year, month)[1]
            possible_date = date(year, month, last_day)
            if possible_date < today:
                return True, f"Signal text mentions a past event month: {match.group(0).strip()}."

    # Year-month-day formats, e.g. "2025-10-26".
    iso_pattern = re.compile(r"\b(?P<year>20\d{2})[-/](?P<month>\d{1,2})(?:[-/](?P<day>\d{1,2}))?\b")
    for match in iso_pattern.finditer(cleaned):
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day") or calendar.monthrange(year, month)[1])
        try:
            found_date = date(year, month, min(day, calendar.monthrange(year, month)[1]))
        except ValueError:
            continue
        if found_date < today:
            return True, f"Signal text mentions a past date: {match.group(0)}."

    return False, None


def event_end_date(event: Event | None) -> date | None:
    """Best-effort parser for event end dates from the existing config.

    Supports strings such as:
    - "June 24-28, 2026"
    - "June 29 - July 12, 2026"
    - "June-July 2027 (TBC)"
    - "May 2027"
    - "2026-2027 Season"

    If only a month is present, the end date is the last day of that month.
    If only a year is present, the end date is 31 Dec of the last year.
    """
    if event is None or not event.dates:
        return None

    raw = event.dates.lower()
    cleaned = re.sub(r"\([^)]*\)", "", raw).replace("–", "-").strip()

    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", cleaned)]
    if not years:
        return None

    year = max(years)

    month_hits: list[tuple[int, int]] = []
    for match in re.finditer(r"\b([a-z]+)\b", cleaned):
        word = match.group(1)
        if word in MONTHS:
            month_hits.append((match.start(), MONTHS[word]))

    if not month_hits:
        return date(year, 12, 31)

    # Use the last month mentioned as the end month for ranges.
    end_month_pos, end_month = month_hits[-1]

    # Look for days after the last month. If none exist, use month end.
    tail = cleaned[end_month_pos:]
    day_candidates = [
        int(d)
        for d in re.findall(r"\b([0-3]?\d)\b", tail)
        if 1 <= int(d) <= 31
    ]

    if day_candidates:
        end_day = max(day_candidates)
    else:
        end_day = calendar.monthrange(year, end_month)[1]

    last_day = calendar.monthrange(year, end_month)[1]
    return date(year, end_month, min(end_day, last_day))


def is_future_event(event: Event | None, today: date | None = None) -> bool | None:
    """Return True for future/current, False for known past, None for unknown."""
    end_date = event_end_date(event)
    if end_date is None:
        return None
    return end_date >= (today or _today())


def build_event_lookup(events: list[Event]) -> dict[str, Event]:
    """Map event names to Event objects for qualification and Slack formatting."""
    return {event.name.lower().strip(): event for event in events}


def filter_future_events(events: list[Event]) -> list[Event]:
    """Remove events whose configured end date is definitely in the past."""
    future_events: list[Event] = []
    today = _today()

    for event in events:
        future = is_future_event(event, today=today)
        if future is False:
            continue
        future_events.append(event)

    return future_events


def qualify_signal(
    signal: Signal,
    event: Event | None = None,
    min_score: int | None = None,
) -> SignalQualification:
    """Score and classify a signal before Slack posting."""
    text = " ".join(
        part
        for part in [
            signal.event or "",
            signal.title or "",
            signal.content or "",
            signal.author or "",
            event.name if event else "",
            event.location if event else "",
            event.type if event else "",
            " ".join(event.keywords) if event else "",
        ]
        if part
    )

    event_type = (event.type if event else "").lower()

    has_hyrox = _contains_hyrox(text) or event_type == "hyrox"
    has_accommodation = _contains_any(text, ACCOMMODATION_KEYWORDS)
    has_seeking = _contains_any(text, SEEKING_KEYWORDS)
    has_community = _contains_any(text, COMMUNITY_KEYWORDS)
    has_cost_pain = _contains_any(text, COST_PAIN_KEYWORDS)
    has_brand = _contains_any(text, BRAND_KEYWORDS) or signal.signal_type == SignalType.BRAND
    has_competitor = _contains_any(text, COMPETITOR_KEYWORDS) or signal.signal_type == SignalType.COMPETITOR
    has_noise = _contains_any(text, NOISE_KEYWORDS)

    future = is_future_event(event)
    event_date_label = event.dates if event else None

    # Signal-level date safety: block stale search results even when the broad
    # configured event/season is future.
    signal_is_past, signal_past_reason = signal_mentions_past_date(text)
    vertical_for_rejection = "HYROX" if has_hyrox else (event_type.upper() if event_type else "GENERAL")
    if signal_is_past:
        return SignalQualification(
            should_post=False,
            score=0,
            label="Ignored — past date in signal",
            vertical=vertical_for_rejection,
            lead_type="past_signal",
            event_date=event_date_label,
            future_event=False,
            tag_darwin=False,
            reason=signal_past_reason or "Signal text appears to describe a past event.",
            action="Hold back from Slack and do not action.",
        )

    score = 0

    # Priority vertical / event relevance.
    vertical = "HYROX" if has_hyrox else (event_type.upper() if event_type else "GENERAL")
    if has_hyrox:
        score += 30
    elif event_type in {"festival", "music", "sports", "conference", "arts", "entertainment"}:
        score += 12

    # Future/current event is required when date is known.
    if future is True:
        score += 20
    elif future is False:
        return SignalQualification(
            should_post=False,
            score=0,
            label="Ignored — past event",
            vertical=vertical,
            lead_type="past_event",
            event_date=event_date_label,
            future_event=False,
            tag_darwin=False,
            reason="Configured event date is in the past.",
            action="Do not action.",
        )
    else:
        # Unknown dates are allowed but score lower.
        score += 5

    # Intent scoring.
    if signal.signal_type == SignalType.SEEKING or has_seeking:
        score += 22
    if signal.signal_type == SignalType.OFFERING:
        score += 16
    if signal.signal_type == SignalType.COST_PAIN or has_cost_pain:
        score += 18
    if signal.signal_type == SignalType.GROUP_FORMING or has_community:
        score += 16
    if has_accommodation:
        score += 30
    if has_brand or has_competitor:
        score += 10

    # Direct combinations Darwin cares about.
    if has_hyrox and has_accommodation:
        score += 15
    if has_hyrox and has_community:
        score += 10
    if has_hyrox and has_cost_pain:
        score += 10

    # Penalise obvious noise unless it still has accommodation/community intent.
    if has_noise and not (has_accommodation or has_community or has_cost_pain):
        score -= 30

    # Keep score bounded.
    score = max(0, min(100, score))

    if has_hyrox and has_accommodation:
        label = "🔥 HYROX ACCOMMODATION LEAD"
        lead_type = "Accommodation seeking / sharing"
        reason = "HYROX priority event with clear accommodation or stay intent."
        action = "Darwin to review, join the thread/community, and engage where appropriate."
    elif has_hyrox and has_community:
        label = "📍 HYROX COMMUNITY OPPORTUNITY"
        lead_type = "Community / group discovery"
        reason = "HYROX community or group where accommodation pain may appear."
        action = "Darwin to monitor/join and watch for room-share or travel-stay pain."
    elif has_accommodation and (has_seeking or signal.signal_type == SignalType.SEEKING):
        label = "🔥 ACCOMMODATION LEAD"
        lead_type = "Accommodation seeking"
        reason = "Clear accommodation-seeking language around a future event."
        action = "Review the original post and engage if it fits SplitStay."
    elif has_cost_pain:
        label = "💸 ACCOMMODATION COST PAIN"
        lead_type = "Cost pain"
        reason = "Accommodation cost or availability pressure detected."
        action = "Review whether SplitStay can provide a cheaper/group-stay option."
    elif has_community:
        label = "📍 COMMUNITY OPPORTUNITY"
        lead_type = "Community"
        reason = "Active community/group signal around a future event."
        action = "Darwin to monitor the community before posting/engaging."
    elif has_brand:
        label = "🏷️ BRAND MENTION"
        lead_type = "Brand mention"
        reason = "SplitStay or brand-related mention detected."
        action = "Review for sentiment and reply if useful."
    elif has_competitor:
        label = "🔍 COMPETITOR MENTION"
        lead_type = "Competitor activity"
        reason = "Competitor or adjacent accommodation platform detected."
        action = "Review for positioning, pricing, and user pain."
    else:
        label = "📡 LOW-QUALITY SIGNAL"
        lead_type = "Unclear"
        reason = "Signal does not clearly show accommodation, community, cost pain, brand or competitor intent."
        action = "Hold back from Slack."

    threshold = min_score
    if threshold is None:
        threshold = int(os.getenv("QUALIFY_MIN_SCORE", "60"))

    if has_hyrox:
        threshold = int(os.getenv("QUALIFY_MIN_SCORE_HYROX", str(min(threshold, 55))))

    should_post = score >= threshold

    # Darwin should only be tagged on high-priority leads, not every generic signal.
    tag_darwin = should_post and (
        score >= 80
        or (has_hyrox and (has_accommodation or has_community or has_cost_pain))
        or label in {"🔥 ACCOMMODATION LEAD", "💸 ACCOMMODATION COST PAIN"}
    )

    return SignalQualification(
        should_post=should_post,
        score=score,
        label=label,
        vertical=vertical,
        lead_type=lead_type,
        event_date=event_date_label,
        future_event=future,
        tag_darwin=tag_darwin,
        reason=reason,
        action=action,
    )
