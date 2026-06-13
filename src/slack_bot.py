"""Slack integration — formats and posts qualified signals to #social-listening-tool."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.models import Event, Signal, SignalType, TrustpilotReview
from src.qualifier import SignalQualification, build_event_lookup, qualify_signal

logger = logging.getLogger(__name__)

# Signal type display config
SIGNAL_DISPLAY = {
    SignalType.OFFERING: {"emoji": "🏠", "label": "OFFERING"},
    SignalType.SEEKING: {"emoji": "🔍", "label": "SEEKING"},
    SignalType.COST_PAIN: {"emoji": "💸", "label": "COST PAIN"},
    SignalType.GROUP_FORMING: {"emoji": "👥", "label": "GROUP FORMING"},
    SignalType.BRAND: {"emoji": "🏷️", "label": "BRAND MENTION"},
    SignalType.COMPETITOR: {"emoji": "🔍", "label": "COMPETITOR"},
    SignalType.TIKTOK: {"emoji": "🎥", "label": "TIKTOK"},
    SignalType.TELEGRAM: {"emoji": "💬", "label": "TELEGRAM"},
    SignalType.PRICE_SPIKE: {"emoji": "💰", "label": "PRICE SPIKE"},
}


class SlackPoster:
    """Posts qualified signals and reviews to the Slack channel."""

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        darwin_slack_id: str | None = None,
    ):
        self.client = WebClient(token=bot_token)
        self.channel_id = channel_id
        self.darwin_slack_id = darwin_slack_id

    def post_signal(
        self,
        signal: Signal,
        country_emoji: str = "🌍",
        event: Event | None = None,
        qualification: SignalQualification | None = None,
    ) -> bool:
        """Post a single qualified signal to the Slack channel."""
        qualification = qualification or qualify_signal(signal, event=event)

        display = SIGNAL_DISPLAY.get(
            signal.signal_type,
            {"emoji": "📡", "label": signal.signal_type.value},
        )

        # Darwin should only be tagged on qualified high-priority action items.
        tag = ""
        if qualification.tag_darwin and self.darwin_slack_id:
            tag = f" <@{self.darwin_slack_id}>"

        event_line = f"*Event:* {signal.event}\n" if signal.event else ""
        event_date_line = (
            f"*Event date:* {qualification.event_date}\n"
            if qualification.event_date
            else ""
        )
        author_line = f"*Author:* {signal.author}\n" if signal.author else ""
        future_line = ""
        if qualification.future_event is True:
            future_line = "*Date check:* Future/current event ✅\n"
        elif qualification.future_event is None:
            future_line = "*Date check:* Unknown/TBC date ⚠️\n"

        excerpt = signal.content.strip()
        if len(excerpt) > 500:
            excerpt = excerpt[:497] + "..."

        text = (
            f"{display['emoji']} *{qualification.label}* {country_emoji}{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{event_line}"
            f"{event_date_line}"
            f"{future_line}"
            f"*Platform:* {signal.platform.value.title()}\n"
            f"*Signal type:* {display['label']}\n"
            f"*Priority vertical:* {qualification.vertical}\n"
            f"*Lead type:* {qualification.lead_type}\n"
            f"*Score:* {qualification.score}/100\n"
            f"{author_line}"
            f"\n"
            f"*Why Darwin should care:*\n{qualification.reason}\n"
            f"\n"
            f"*Suggested action:*\n{qualification.action}\n"
            f"\n"
            f"*Signal:*\n*{signal.title}*\n"
            f"{excerpt}\n"
            f"\n"
            f"🔗 <{signal.url}|View original post>"
        )

        try:
            self.client.chat_postMessage(
                channel=self.channel_id,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            logger.info(
                "Posted qualified signal: score=%s type=%s title=%s",
                qualification.score,
                signal.signal_type.value,
                signal.title[:50],
            )
            return True
        except SlackApiError as e:
            logger.error(f"Failed to post signal to Slack: {e}")
            return False

    def post_signals_batch(
        self,
        signals: list[Signal],
        country: str,
        country_emoji: str,
        events: list[Event] | None = None,
    ) -> int:
        """Post a batch of qualified signals with a header."""
        if not signals:
            return 0

        event_lookup = build_event_lookup(events or [])
        qualifications: list[tuple[Signal, Event | None, SignalQualification]] = []

        for signal in signals:
            event = event_lookup.get((signal.event or "").lower().strip())
            qualification = qualify_signal(signal, event=event)
            if qualification.should_post:
                qualifications.append((signal, event, qualification))

        if not qualifications:
            logger.info("No qualified signals to post after Slack-side qualification")
            return 0

        # Post header
        header = (
            f"{'━' * 30}\n"
            f"{country_emoji} *{country.upper()} QUALIFIED SCAN — "
            f"{datetime.now(timezone.utc).strftime('%B %d, %Y')}*\n"
            f"Found *{len(qualifications)}* qualified signals for Darwin\n"
            f"_Low-quality, past-event and generic signals were held back._\n"
            f"{'━' * 30}"
        )

        try:
            self.client.chat_postMessage(
                channel=self.channel_id,
                text=header,
            )
        except SlackApiError as e:
            logger.error(f"Failed to post header: {e}")

        # Post each signal
        posted = 0
        for signal, event, qualification in qualifications:
            if self.post_signal(signal, country_emoji, event=event, qualification=qualification):
                posted += 1

        return posted

    def post_trustpilot_review(self, review: TrustpilotReview) -> bool:
        """Post a Trustpilot review to the channel. No one is tagged."""
        stars = "⭐" * review.rating

        text = (
            f"⭐ *New Trustpilot Review*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*Rating:* {stars} ({review.rating}/5)\n"
            f"*Reviewer:* {review.reviewer}\n"
            f"*Date:* {review.date}\n"
            f"*Title:* \"{review.title}\"\n"
            f"\n"
            f"\"{review.content}\"\n"
            f"\n"
            f"🔗 <{review.url}|View on Trustpilot>"
        )

        try:
            self.client.chat_postMessage(
                channel=self.channel_id,
                text=text,
                unfurl_links=False,
            )
            logger.info(f"Posted Trustpilot review from {review.reviewer}")
            return True
        except SlackApiError as e:
            logger.error(f"Failed to post Trustpilot review: {e}")
            return False

    def post_price_alert(
        self,
        event_name: str,
        location: str,
        country_emoji: str,
        avg_price: str,
        spike_pct: str,
        source_url: str,
    ) -> bool:
        """Post a price spike alert."""
        tag = f" <@{self.darwin_slack_id}>" if self.darwin_slack_id else ""

        text = (
            f"💰 *PRICE SPIKE ALERT* {country_emoji}{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*Event:* {event_name}\n"
            f"*Location:* {location}\n"
            f"*Avg Price:* {avg_price}\n"
            f"*Spike:* {spike_pct}\n"
            f"\n"
            f"🔗 <{source_url}|View prices>"
        )

        try:
            self.client.chat_postMessage(
                channel=self.channel_id,
                text=text,
                unfurl_links=False,
            )
            return True
        except SlackApiError as e:
            logger.error(f"Failed to post price alert: {e}")
            return False
