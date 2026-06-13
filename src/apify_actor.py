"""Apify Actor runner for one-off Social Listener scans.

Recommended test input:
{
  "country": "uk",
  "notify_slack": true,
  "max_events": 2,
  "platforms": ["twitter"],
  "scanner_timeout_seconds": 90
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
except Exception:
    Actor = None  # type: ignore[assignment]


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = {"spain", "uk", "us", "brazil", "germany", "taiwan", "china", "portugal"}


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def _as_platforms(value: Any, default: list[str]) -> list[str]:
    if value in (None, ""):
        return default
    if isinstance(value, list):
        platforms = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        platforms = [item.strip().lower() for item in str(value).replace(";", ",").split(",") if item.strip()]
    return platforms or default


def _normalise_country(value: Any) -> str:
    country = str(value or "uk").strip().lower()
    if country not in SUPPORTED_COUNTRIES:
        raise ValueError(f"Unsupported country '{country}'. Use one of: {', '.join(sorted(SUPPORTED_COUNTRIES))}")
    return country


def _post_slack_status(message: str) -> bool:
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
    country = _normalise_country(actor_input.get("country", "uk"))
    notify_slack = _as_bool(actor_input.get("notify_slack"), default=True)

    # Safe defaults for Apify proof-of-life runs.
    max_events = _as_int(actor_input.get("max_events"), default=2)
    scanner_timeout = _as_int(actor_input.get("scanner_timeout_seconds"), default=90)
    platforms = _as_platforms(actor_input.get("platforms"), default=["twitter"])

    os.environ["SCAN_MAX_EVENTS"] = str(max_events)
    os.environ["SCANNER_TIMEOUT_SECONDS"] = str(scanner_timeout)
    os.environ["SCAN_PLATFORMS"] = ",".join(platforms)

    logger.info("=" * 50)
    logger.info("Apify Social Listener — one-off scan")
    logger.info("Country: %s", country.upper())
    logger.info("Max events: %s", max_events)
    logger.info("Platforms: %s", ", ".join(platforms))
    logger.info("Per-scanner timeout: %s seconds", scanner_timeout)
    logger.info("=" * 50)

    started_at = datetime.now(timezone.utc)

    if notify_slack:
        _post_slack_status(
            "🚀 *Apify Social Listener run started*\n"
            f"*Country:* `{country}`\n"
            f"*Platforms:* `{', '.join(platforms)}`\n"
            f"*Max events:* `{max_events}`\n"
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
        "platforms": platforms,
        "max_events": max_events,
        "scanner_timeout_seconds": scanner_timeout,
        "signals_posted_to_slack": posted,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "reddit_enabled": bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET")),
    }

    if notify_slack:
        reddit_line = "Enabled" if result["reddit_enabled"] else "Skipped until Reddit credentials are added"
        _post_slack_status(
            "✅ *Apify Social Listener run completed*\n"
            f"*Country:* `{country}`\n"
            f"*Platforms:* `{', '.join(platforms)}`\n"
            f"*Signals posted:* `{posted}`\n"
            f"*Reddit:* {reddit_line}\n"
            f"*Duration:* `{duration_seconds}s`"
        )

    logger.info("Apify run result: %s", result)
    return result


async def main() -> None:
    if Actor is None:
        country = os.getenv("COUNTRY", "uk")
        await _run_from_input({"country": country, "notify_slack": True})
        return

    async with Actor:
        actor_input = await Actor.get_input() or {}
        result = await _run_from_input(actor_input)
        await Actor.push_data(result)


if __name__ == "__main__":
    asyncio.run(main())
