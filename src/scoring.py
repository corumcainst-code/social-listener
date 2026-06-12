"""
Lead Scoring Engine for SplitStay Social Listener
Phase 2: Score signals on intent, urgency, actionability, and group dynamics.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Priority(Enum):
    HOT = "hot"       # Score 8-10 or (6+ with urgent/high urgency)
    WARM = "warm"     # Score 5-7
    COLD = "cold"     # Score 1-4


class Urgency(Enum):
    URGENT = "urgent"   # Event < 1 week, post < 1 week
    HIGH = "high"       # Event 1-2 weeks, post < 2 weeks
    MEDIUM = "medium"   # Event 2-8 weeks
    LOW = "low"         # Event 2-6 months
    FUTURE = "future"   # Event 6+ months


@dataclass
class ScoreBreakdown:
    intent: int = 0          # 0-3
    proximity: int = 0       # 0-3
    actionability: int = 0   # 0-2
    group_signal: int = 0    # 0-2

    @property
    def total(self) -> int:
        return self.intent + self.proximity + self.actionability + self.group_signal

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "proximity": self.proximity,
            "actionability": self.actionability,
            "group_signal": self.group_signal,
        }


@dataclass
class LeadScore:
    score: int              # 1-10
    urgency: Urgency
    priority: Priority
    breakdown: ScoreBreakdown
    label: str              # Human-readable: "🔥 HOT LEAD", "🟡 WARM LEAD", "❄️ COLD LEAD"

    def to_dict(self) -> dict:
        return {
            "lead_score": self.score,
            "urgency": self.urgency.value,
            "priority": self.priority.value,
            "score_breakdown": self.breakdown.to_dict(),
        }


# ── Intent Keywords ──────────────────────────────────────────────────────────

EXPLICIT_INTENT_KEYWORDS = [
    "looking for roommate", "need a roommate", "anyone want to share",
    "have a spare bed", "spare room", "extra space", "room available",
    "spot available", "room for one more", "extra bed",
    "anyone want to split", "split accommodation", "split the cost",
    "share my hotel", "share my airbnb", "share my apartment",
    "booked a room", "booked apartment", "looking for someone to share",
]

STRONG_INTENT_KEYWORDS = [
    "share accommodation", "travel buddy", "travel companion",
    "going alone", "by myself", "can't afford hotel alone",
    "share hotel", "share airbnb", "split hotel",
    "solo traveler", "solo festival",
]

MODERATE_INTENT_KEYWORDS = [
    "where to stay", "accommodation advice", "hotel recommendations",
    "too expensive", "so expensive", "crazy prices", "overpriced",
    "budget accommodation", "cheap hotel", "hostel",
]


def _score_intent(text: str) -> int:
    """Score intent clarity (0-3)."""
    text_lower = text.lower()

    for kw in EXPLICIT_INTENT_KEYWORDS:
        if kw in text_lower:
            return 3

    for kw in STRONG_INTENT_KEYWORDS:
        if kw in text_lower:
            return 2

    for kw in MODERATE_INTENT_KEYWORDS:
        if kw in text_lower:
            return 1

    return 0


def _score_proximity(event_date: Optional[datetime], now: Optional[datetime] = None) -> int:
    """Score event proximity (0-3)."""
    if event_date is None:
        return 1  # Default for unknown dates

    now = now or datetime.utcnow()
    days_until = (event_date - now).days

    if days_until < 0:
        return 0  # Event already passed
    elif days_until <= 14:
        return 3
    elif days_until <= 28:
        return 2
    elif days_until <= 90:
        return 1
    else:
        return 0


def _score_actionability(
    platform: str,
    has_active_comments: bool = False,
    has_group_link: bool = False,
    is_recent: bool = True,
) -> int:
    """Score actionability (0-2)."""
    high_action_platforms = {"reddit", "discord", "facebook", "whatsapp", "telegram"}
    medium_action_platforms = {"x", "twitter", "tiktok", "forum"}

    score = 0
    platform_lower = platform.lower()

    if platform_lower in high_action_platforms:
        score = 1
        if has_active_comments or has_group_link:
            score = 2
    elif platform_lower in medium_action_platforms:
        score = 1
    else:
        score = 0

    # Reduce score for old/closed posts
    if not is_recent:
        score = max(0, score - 1)

    return score


def _score_group_signal(text: str, comment_count: int = 0) -> int:
    """Score group signal (0-2)."""
    text_lower = text.lower()

    group_keywords_strong = [
        "group of", "3 people", "4 people", "5 people",
        "organizing a group", "group booking", "whatsapp group",
        "discord server", "telegram group", "several of us",
        "a few of us", "our group", "we need",
    ]

    pair_keywords = [
        "2 people", "my friend and i", "me and my",
        "travel buddy", "solo", "going alone", "by myself",
        "looking for someone", "anyone else",
    ]

    for kw in group_keywords_strong:
        if kw in text_lower:
            return 2

    # Multiple comments can indicate group forming
    if comment_count >= 10:
        return 2

    for kw in pair_keywords:
        if kw in text_lower:
            return 1

    if comment_count >= 3:
        return 1

    return 0


def _determine_urgency(
    event_date: Optional[datetime],
    post_date: Optional[datetime],
    now: Optional[datetime] = None,
) -> Urgency:
    """Determine urgency level."""
    now = now or datetime.utcnow()

    if event_date is None:
        return Urgency.MEDIUM

    days_until_event = (event_date - now).days
    post_age_days = (now - post_date).days if post_date else 30

    if days_until_event < 0:
        return Urgency.LOW  # Past event

    if days_until_event <= 7 and post_age_days <= 7:
        return Urgency.URGENT
    elif days_until_event <= 14 and post_age_days <= 14:
        return Urgency.HIGH
    elif days_until_event <= 56:  # ~8 weeks
        return Urgency.MEDIUM
    elif days_until_event <= 180:  # ~6 months
        return Urgency.LOW
    else:
        return Urgency.FUTURE


def _determine_priority(score: int, urgency: Urgency) -> Priority:
    """Determine priority classification."""
    if score >= 8:
        return Priority.HOT
    if score >= 6 and urgency in (Urgency.URGENT, Urgency.HIGH):
        return Priority.HOT
    if score >= 5:
        return Priority.WARM
    return Priority.COLD


PRIORITY_LABELS = {
    Priority.HOT: "🔥 HOT LEAD",
    Priority.WARM: "🟡 WARM LEAD",
    Priority.COLD: "❄️ COLD LEAD",
}

URGENCY_EMOJIS = {
    Urgency.URGENT: "🔴",
    Urgency.HIGH: "🟠",
    Urgency.MEDIUM: "🟡",
    Urgency.LOW: "🟢",
    Urgency.FUTURE: "⚪",
}


def score_signal(
    text: str,
    platform: str = "reddit",
    event_date: Optional[datetime] = None,
    post_date: Optional[datetime] = None,
    comment_count: int = 0,
    has_group_link: bool = False,
    now: Optional[datetime] = None,
) -> LeadScore:
    """
    Score a social listening signal.

    Args:
        text: The post title + body/summary
        platform: Source platform (reddit, x, facebook, discord, tiktok, telegram, web)
        event_date: When the related event starts
        post_date: When the post was created
        comment_count: Number of comments/replies
        has_group_link: Whether the post contains a group link (WhatsApp, Discord, etc.)
        now: Current time override for testing

    Returns:
        LeadScore with score (1-10), urgency, priority, and breakdown
    """
    now = now or datetime.utcnow()

    # Calculate each factor
    intent = _score_intent(text)
    proximity = _score_proximity(event_date, now)
    actionability = _score_actionability(
        platform,
        has_active_comments=comment_count >= 3,
        has_group_link=has_group_link,
        is_recent=(now - post_date).days <= 30 if post_date else True,
    )
    group = _score_group_signal(text, comment_count)

    breakdown = ScoreBreakdown(
        intent=intent,
        proximity=proximity,
        actionability=actionability,
        group_signal=group,
    )

    # Clamp total to 1-10
    total = max(1, min(10, breakdown.total))

    urgency = _determine_urgency(event_date, post_date, now)
    priority = _determine_priority(total, urgency)
    label = PRIORITY_LABELS[priority]

    return LeadScore(
        score=total,
        urgency=urgency,
        priority=priority,
        breakdown=breakdown,
        label=label,
    )


def format_signal_slack(
    signal: dict,
    lead: LeadScore,
) -> str:
    """Format a scored signal for Slack output."""
    urgency_emoji = URGENCY_EMOJIS.get(lead.urgency, "")
    urgency_label = lead.urgency.value.upper()
    side_emoji = {
        "seeking": "🔍 SEEKING",
        "offering": "🏠 OFFERING",
        "cost_pain": "💸 COST PAIN",
        "group_forming": "👥 GROUP",
        "tiktok": "🎥 TIKTOK",
        "telegram": "💬 TELEGRAM",
    }.get(signal.get("side", ""), "📡")

    event_name = signal.get("event", "Unknown")
    event_dates = signal.get("event_dates", "")
    summary = signal.get("summary", "")
    platform = signal.get("platform", "")
    url = signal.get("url", "")

    lines = [
        f"🎯 *{event_name}*{' — ' + event_dates if event_dates else ''} — {urgency_emoji} {urgency_label}",
        f"┃ Lead Score: *{lead.score}/10* | {side_emoji}",
        f'┃ "{summary}"',
        f"┃ 📍 {platform.title()}",
        f"┃ 🔗 {url}",
    ]
    return "\n".join(lines)


# ── Price Signal Scoring ─────────────────────────────────────────────────────

def score_price_signal(
    severity: str,  # "sold_out", "3x", "2x", "1.5x", "slight", "normal"
    event_date: Optional[datetime] = None,
    estimated_attendees: int = 0,
    now: Optional[datetime] = None,
) -> LeadScore:
    """Score a price spike signal."""
    now = now or datetime.utcnow()

    # Severity (0-4 → scaled to 0-3 for consistency)
    severity_scores = {
        "sold_out": 3, "3x": 3, "2x": 2, "1.5x": 1, "slight": 1, "normal": 0
    }
    intent = severity_scores.get(severity, 1)

    proximity = _score_proximity(event_date, now)

    # Market size
    if estimated_attendees >= 50000:
        group = 2
    elif estimated_attendees >= 10000:
        group = 1
    else:
        group = 0

    # Actionability for price signals is always moderate
    actionability = 1

    breakdown = ScoreBreakdown(
        intent=intent,
        proximity=proximity,
        actionability=actionability,
        group_signal=group,
    )

    total = max(1, min(10, breakdown.total))
    urgency = _determine_urgency(event_date, now, now)
    priority = _determine_priority(total, urgency)

    return LeadScore(
        score=total,
        urgency=urgency,
        priority=priority,
        breakdown=breakdown,
        label=PRIORITY_LABELS[priority],
    )


# ── Brand Signal Scoring ─────────────────────────────────────────────────────

def score_brand_signal(
    text: str,
    is_splitstay_mention: bool = False,
    sentiment: str = "neutral",  # positive, negative, neutral
    comment_count: int = 0,
    post_date: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> LeadScore:
    """Score a brand/competitor signal."""
    now = now or datetime.utcnow()

    # Relevance (0-3)
    if is_splitstay_mention:
        intent = 3
    elif any(kw in text.lower() for kw in ["accommodation sharing", "share stay", "split cost"]):
        intent = 2
    else:
        intent = 1

    # Sentiment/Opportunity (0-3) → using proximity slot
    sentiment_scores = {"negative": 3, "neutral": 1, "positive": 2}
    if is_splitstay_mention and sentiment == "positive":
        proximity = 3  # Amplify positive SplitStay mentions
    elif not is_splitstay_mention and sentiment == "negative":
        proximity = 3  # Competitor complaints = opportunity
    else:
        proximity = sentiment_scores.get(sentiment, 1)

    # Reach
    if comment_count >= 10:
        actionability = 2
    elif comment_count >= 3:
        actionability = 1
    else:
        actionability = 0

    # Recency
    if post_date:
        days_old = (now - post_date).days
        group = 2 if days_old <= 7 else (1 if days_old <= 30 else 0)
    else:
        group = 1

    breakdown = ScoreBreakdown(
        intent=intent,
        proximity=proximity,
        actionability=actionability,
        group_signal=group,
    )

    total = max(1, min(10, breakdown.total))
    urgency = Urgency.HIGH if total >= 7 else Urgency.MEDIUM
    priority = _determine_priority(total, urgency)

    return LeadScore(
        score=total,
        urgency=urgency,
        priority=priority,
        breakdown=breakdown,
        label=PRIORITY_LABELS[priority],
    )
