"""Slack integration — formats and posts signals to #social-listening-tool."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.models import Signal, SignalType, TrustpilotReview

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
    """Posts signals and reviews to the Slack channel."""
    
    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        darwin_slack_id: str | None = None,
    ):
        self.client = WebClient(token=bot_token)
        self.channel_id = channel_id
        self.darwin_slack_id = darwin_slack_id
    
    def post_signal(self, signal: Signal, country_emoji: str = "🌍") -> bool:
        """Post a single signal to the Slack channel."""
        display = SIGNAL_DISPLAY.get(
            signal.signal_type,
            {"emoji": "📡", "label": signal.signal_type.value},
        )
        
        # Build the message
        tag = f" <@{self.darwin_slack_id}>" if self.darwin_slack_id else ""
        
        event_line = f"*Event:* {signal.event}\n" if signal.event else ""
        author_line = f"*Author:* {signal.author}\n" if signal.author else ""
        
        text = (
            f"{display['emoji']} *{display['label']}* {country_emoji}{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{event_line}"
            f"*Platform:* {signal.platform.value.title()}\n"
            f"{author_line}"
            f"\n"
            f"*{signal.title}*\n"
            f"{signal.content}\n"
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
            logger.info(f"Posted signal: {signal.signal_type.value} - {signal.title[:50]}")
            return True
        except SlackApiError as e:
            logger.error(f"Failed to post signal to Slack: {e}")
            return False
    
    def post_signals_batch(
        self,
        signals: list[Signal],
        country: str,
        country_emoji: str,
    ) -> int:
        """Post a batch of signals with a header."""
        if not signals:
            return 0
        
        # Post header
        header = (
            f"{'━' * 30}\n"
            f"{country_emoji} *{country.upper()} SCAN — "
            f"{datetime.now(timezone.utc).strftime('%B %d, %Y')}*\n"
            f"Found *{len(signals)}* new signals\n"
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
        for signal in signals:
            if self.post_signal(signal, country_emoji):
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
