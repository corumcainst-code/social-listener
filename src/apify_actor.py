"""Apify Actor runner for one-off Social Listener scans.

This module is intentionally different from ``src.scheduler``.
The scheduler is designed to stay alive and wait for monthly jobs.
Apify runs should normally do one job, write output, and finish.

Input example:
{
  "country": "uk",
  "notify_slack": true
}
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.scanner import scan_country

try:
    from apify import Actor
except Exception:  # pragma: no cover - useful for local fallback
    Actor = None  # type: ignore[assignment]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = {
    "spain",
    "uk",
    "us",
    "brazil",
    "germany",
    "taiwan",
    "china",
    "portugal",
}


def _as_bool(value: Any, default: bool = True) -> bool:
    """Parse a flexible boolean input."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalise_country(value: Any) -> str:
    """Return a supported country code, defaulting to UK."""
    country = str(value or "uk").strip().lower()
    if country not in SUPPORTED_COUNTRIES:
        raise ValueError(
            f"Unsupported country '{country}'. "
            f"Use one of: {', '.join(sorted(SUPPORTED_COUNTRIES))}"
        )
    return country


def _post_slack_status(message: str) -> bool:
    """Post a simple status message to Slack if Slack credentials exist."""
    token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID")

    if not token or not channel_id:
        logger.warning("Slack status skipped — SLACK_BOT_TOKEN or SLACK_CHANNEL_ID missing")
        return False

    try:
        WebClient(token=token).chat_postMessage(
            channel=channel_id,
            text=message,
            unfurl_links=False,
            unfurl_media=False,
        )
        return True
    except SlackApiError as exc:
        logger.error("Failed to post Slack status: %s", exc)
        return False


async def _run_from_input(actor_input: dict[str, Any]) -> dict[str, Any]:
    """Run one country scan from Apify input."""
    country = _normalise_country(actor_input.get("country", "uk"))
    notify_slack = _as_bool(actor_input.get("notify_slack"), default=True)

    logger.info("=" * 50)
    logger.info("Apify Social Listener — one-off scan")
    logger.info("Country: %s", country.upper())
    logger.info("=" * 50)

    started_at = datetime.now(timezone.utc)

    if notify_slack:
        _post_slack_status(
            "🚀 *Apify Social Listener run started*\n"
            f"*Country:* `{country}`\n"
            "_Running one-off scan now._"
        )

    try:
        posted = await scan_country(country)
    except Exception as exc:
        error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        logger.exception("Apify Social Listener run failed")

        if notify_slack:
            _post_slack_status(
                "❌ *Apify Social Listener run failed*\n"
                f"*Country:* `{country}`\n"
                f"*Error:* `{error_text}`"
            )
        raise

    finished_at = datetime.now(timezone.utc)
    duration_seconds = round((finished_at - started_at).total_seconds(), 2)

    result = {
        "status": "succeeded",
        "country": country,
        "signals_posted_to_slack": posted,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "reddit_enabled": bool(
            os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET")
        ),
    }

    if notify_slack:
        reddit_line = (
            "Enabled"
            if result["reddit_enabled"]
            else "Skipped until Reddit credentials are added"
        )
        _post_slack_status(
            "✅ *Apify Social Listener run completed*\n"
            f"*Country:* `{country}`\n"
            f"*Signals posted:* `{posted}`\n"
            f"*Reddit:* {reddit_line}\n"
            f"*Duration:* `{duration_seconds}s`"
        )

    logger.info("Apify run result: %s", result)
    return result


async def main() -> None:
    """Main entrypoint used by Apify."""
    if Actor is None:
        # Local fallback, useful if someone runs this without the Apify SDK context.
        country = os.getenv("COUNTRY", "uk")
        await _run_from_input({"country": country, "notify_slack": True})
        return

    async with Actor:
        actor_input = await Actor.get_input() or {}
        result = await _run_from_input(actor_input)
        await Actor.push_data(result)


if __name__ == "__main__":
    asyncio.run(main())
