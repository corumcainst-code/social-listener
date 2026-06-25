"""Apify Actor runner for one-off Social Listener scans.

Recommended UK test input:
{
  "country": "uk",
  "notify_slack": true,
  "max_events": 2,
  "platforms": ["twitter"],
  "scanner_timeout_seconds": 90
}

Recommended all-country test input:
{
  "country": "all",
  "notify_slack": true,
  "max_events": 1,
  "platforms": ["twitter", "facebook", "instagram"],
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

from src.scanner import scan_country_diagnostics

try:
    from apify import Actor
except Exception:
    Actor = None  # type: ignore[assignment]


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

COUNTRY_ORDER = ["spain", "uk", "us", "brazil", "germany", "taiwan", "china", "portugal"]
SUPPORTED_COUNTRIES = set(COUNTRY_ORDER)
ALL_COUNTRY_ALIASES = {"all", "*", "8", "all8", "all_8", "all-countries", "all countries"}
COUNTRY_ALIASES = {
    "gb": "uk",
    "great britain": "uk",
    "united kingdom": "uk",
    "england": "uk",
    "usa": "us",
    "u.s.": "us",
    "u.s.a.": "us",
    "united states": "us",
    "united states of america": "us",
    "brasil": "brazil",
    "de": "germany",
    "deutschland": "germany",
    "es": "spain",
    "espana": "spain",
    "españa": "spain",
    "pt": "portugal",
    "tw": "taiwan",
    "cn": "china",
}


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


def _as_text(value: Any, default: str = "") -> str:
    if value in (None, ""):
        return default
    text = str(value).strip()
    return text or default


def _slack_line(label: str, value: str, *, code: bool = False) -> str:
    if not value:
        return ""
    if code:
        return f"*{label}:* `{value}`\n"
    return f"*{label}:* {value}\n"


def _as_platforms(value: Any, default: list[str]) -> list[str]:
    if value in (None, ""):
        return default
    if isinstance(value, list):
        platforms = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        platforms = [item.strip().lower() for item in str(value).replace(";", ",").split(",") if item.strip()]
    return platforms or default


def _normalise_country_name(value: Any) -> str:
    country = str(value or "uk").strip().lower()
    country = COUNTRY_ALIASES.get(country, country)
    if country not in SUPPORTED_COUNTRIES:
        raise ValueError(f"Unsupported country '{value}'. Use one of: {', '.join(COUNTRY_ORDER)}, or 'all'")
    return country


def _normalise_countries(actor_input: dict[str, Any]) -> list[str]:
    """Accept either country='uk', country='all', country='uk,spain', or countries=[...]."""
    raw = actor_input.get("countries")
    if raw in (None, ""):
        raw = actor_input.get("country", "uk")

    if isinstance(raw, list):
        raw_values = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        raw_string = str(raw or "uk").strip().lower()
        if raw_string in ALL_COUNTRY_ALIASES:
            return COUNTRY_ORDER.copy()
        raw_values = [item.strip().lower() for item in raw_string.replace(";", ",").split(",") if item.strip()]

    if not raw_values:
        return ["uk"]

    if any(value in ALL_COUNTRY_ALIASES for value in raw_values):
        return COUNTRY_ORDER.copy()

    countries: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        country = _normalise_country_name(value)
        if country not in seen:
            countries.append(country)
            seen.add(country)

    return countries or ["uk"]


def _countries_label(countries: list[str]) -> str:
    if countries == COUNTRY_ORDER:
        return "all 8 countries"
    return ", ".join(countries)


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




def _diagnostic_totals(scan_diagnostics: dict[str, dict[str, Any]]) -> dict[str, int]:
    totals = {
        "events_scanned": 0,
        "scanners_attempted": 0,
        "scanners_succeeded": 0,
        "raw_signals_found": 0,
        "qualified_new_signals": 0,
        "signals_posted": 0,
        "scanner_timeouts": 0,
        "scanner_errors": 0,
        "scored_candidates": 0,
        "hot_leads": 0,
        "warm_leads": 0,
        "low_quality_leads": 0,
        "filtered_known": 0,
        "filtered_old": 0,
        "filtered_empty": 0,
        "filtered_duplicate": 0,
        "filtered_low_quality": 0,
    }
    for details in scan_diagnostics.values():
        totals["events_scanned"] += int(details.get("events_scanned", 0) or 0)
        totals["scanners_attempted"] += int(details.get("scanners_attempted", 0) or 0)
        totals["scanners_succeeded"] += int(details.get("scanners_succeeded", 0) or 0)
        totals["raw_signals_found"] += int(details.get("raw_signals_found", 0) or 0)
        totals["qualified_new_signals"] += int(details.get("qualified_new_signals", 0) or 0)
        totals["signals_posted"] += int(details.get("signals_posted", 0) or 0)
        totals["scanner_timeouts"] += len(details.get("scanners_timed_out", []) or [])
        totals["scanner_errors"] += len(details.get("scanners_failed", {}) or {})
        processing_stats = details.get("processing_stats", {}) or {}
        totals["scored_candidates"] += int(processing_stats.get("scored_candidates", 0) or 0)
        totals["hot_leads"] += int(processing_stats.get("hot_leads", 0) or 0)
        totals["warm_leads"] += int(processing_stats.get("warm_leads", 0) or 0)
        totals["low_quality_leads"] += int(processing_stats.get("low_quality_leads", 0) or 0)
        totals["filtered_known"] += int(processing_stats.get("filtered_known", 0) or 0)
        totals["filtered_old"] += int(processing_stats.get("filtered_old", 0) or 0)
        totals["filtered_empty"] += int(processing_stats.get("filtered_empty", 0) or 0)
        totals["filtered_duplicate"] += int(processing_stats.get("filtered_duplicate", 0) or 0)
        totals["filtered_low_quality"] += int(processing_stats.get("filtered_low_quality", 0) or 0)
    return totals


def _diagnostic_item_summary(scan_diagnostics: dict[str, dict[str, Any]], key: str) -> str:
    items: list[str] = []
    for country, details in scan_diagnostics.items():
        if key == "scanners_timed_out":
            for scanner_name in details.get("scanners_timed_out", []) or []:
                items.append(f"{country}: {scanner_name}")
        elif key == "scanners_failed":
            for scanner_name in (details.get("scanners_failed", {}) or {}).keys():
                items.append(f"{country}: {scanner_name}")
    return ", ".join(items) if items else "none"


def _diagnostic_result_line(totals: dict[str, int]) -> str:
    if totals["raw_signals_found"] == 0:
        return "Scan completed; no raw public lead candidates were found."
    if totals["qualified_new_signals"] == 0:
        return "Scan completed; raw candidates were found, but none passed qualification."
    if totals["signals_posted"] == 0:
        return "Scan completed; qualified candidates were found, but none were posted to Slack."
    return "Scan completed; qualified signals were posted to Slack."


def _format_scan_diagnostics(scan_diagnostics: dict[str, dict[str, Any]]) -> tuple[str, dict[str, int]]:
    if not scan_diagnostics:
        return "", _diagnostic_totals(scan_diagnostics)

    totals = _diagnostic_totals(scan_diagnostics)
    timed_out_line = _diagnostic_item_summary(scan_diagnostics, "scanners_timed_out")
    failed_line = _diagnostic_item_summary(scan_diagnostics, "scanners_failed")
    result_line = _diagnostic_result_line(totals)

    message = (
        "\n*Scan diagnostics:*\n"
        f"• Events scanned: `{totals['events_scanned']}`\n"
        f"• Platform scanners attempted: `{totals['scanners_attempted']}` (`{totals['scanners_succeeded']}` succeeded)\n"
        f"• Raw candidates found: `{totals['raw_signals_found']}`\n"
        f"• Qualified new signals: `{totals['qualified_new_signals']}`\n"
        f"• Scanner timeouts: `{timed_out_line}`\n"
        f"• Scanner errors: `{failed_line}`\n"
        f"• Result: {result_line}\n"
    )
    return message, totals

async def _run_from_input(actor_input: dict[str, Any]) -> dict[str, Any]:
    countries = _normalise_countries(actor_input)
    notify_slack = _as_bool(actor_input.get("notify_slack"), default=True)

    # Safe defaults for Apify proof-of-life runs.
    max_events = _as_int(actor_input.get("max_events"), default=2)
    scanner_timeout = _as_int(actor_input.get("scanner_timeout_seconds"), default=90)
    platforms = _as_platforms(actor_input.get("platforms"), default=["twitter"])
    smart_source_scanning = _as_bool(actor_input.get("smart_source_scanning"), default=False)
    campaign_name = _as_text(actor_input.get("campaign_name") or actor_input.get("campaign"))
    campaign_focus = _as_text(actor_input.get("campaign_focus"))
    run_type = _as_text(actor_input.get("run_type"), default="Scan")

    # v0.14.1 light smart scan defaults.
    # These keep smart scanning useful without letting a daily batch explode into
    # hundreds of web-search requests.
    smart_base_queries = _as_int(actor_input.get("smart_source_base_queries_per_event"), default=1)
    smart_extra_queries = _as_int(actor_input.get("smart_source_extra_queries_per_event"), default=2)
    web_search_http_timeout = _as_int(actor_input.get("web_search_http_timeout_seconds"), default=12)

    os.environ["SCAN_MAX_EVENTS"] = str(max_events)
    os.environ["SCANNER_TIMEOUT_SECONDS"] = str(scanner_timeout)
    os.environ["SCAN_PLATFORMS"] = ",".join(platforms)
    os.environ["SMART_SOURCE_SCANNING"] = "1" if smart_source_scanning else ""
    os.environ["SMART_SOURCE_BASE_QUERIES_PER_EVENT"] = str(smart_base_queries)
    os.environ["SMART_SOURCE_EXTRA_QUERIES_PER_EVENT"] = str(smart_extra_queries)
    os.environ["WEB_SEARCH_HTTP_TIMEOUT_SECONDS"] = str(web_search_http_timeout)

    country_label = _countries_label(countries)

    logger.info("=" * 50)
    logger.info("Apify Social Listener — one-off scan")
    if campaign_name:
        logger.info("Campaign: %s", campaign_name)
    if campaign_focus:
        logger.info("Campaign focus: %s", campaign_focus)
    logger.info("Run type: %s", run_type)
    logger.info("Countries: %s", country_label)
    logger.info("Max events per country: %s", max_events)
    logger.info("Platforms: %s", ", ".join(platforms))
    logger.info("Per-scanner timeout: %s seconds", scanner_timeout)
    logger.info("Smart source scanning: %s", "enabled" if smart_source_scanning else "disabled")
    logger.info(
        "Smart source light controls: %s base + %s smart queries per platform/event; HTTP timeout %ss",
        smart_base_queries,
        smart_extra_queries,
        web_search_http_timeout,
    )
    logger.info("=" * 50)

    started_at = datetime.now(timezone.utc)

    if notify_slack:
        smart_line = "Enabled" if smart_source_scanning else "Disabled"
        _post_slack_status(
            "🚀 *Apify Social Listener run started*\n"
            f"{_slack_line('Campaign', campaign_name, code=True)}"
            f"{_slack_line('Focus', campaign_focus)}"
            f"{_slack_line('Run type', run_type, code=True)}"
            f"*Countries:* `{country_label}`\n"
            f"*Platforms:* `{', '.join(platforms)}`\n"
            f"*Max events per country:* `{max_events}`\n"
            f"*Smart source scanning:* `{smart_line}`\n"
            f"*Smart scan mode:* `Light ({smart_base_queries}+{smart_extra_queries} queries, {web_search_http_timeout}s HTTP timeout)`\n"
            "_Running scan now._"
        )

    posted_by_country: dict[str, int] = {}
    scan_diagnostics: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    for index, country in enumerate(countries, start=1):
        logger.info("Starting country %s/%s: %s", index, len(countries), country.upper())
        try:
            country_diagnostics = await scan_country_diagnostics(country)
            scan_diagnostics[country] = country_diagnostics.to_dict()
            posted_by_country[country] = country_diagnostics.signals_posted
        except Exception as exc:
            error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            errors[country] = error_text
            logger.exception("Apify Social Listener country scan failed: %s", country)
            if notify_slack:
                _post_slack_status(
                    "⚠️ *Apify Social Listener country scan failed*\n"
                    f"*Country:* `{country}`\n"
                    f"*Error:* `{error_text}`\n"
                    "_Continuing with the remaining countries._"
                )

    if errors and not posted_by_country:
        raise RuntimeError(f"All country scans failed: {errors}")

    finished_at = datetime.now(timezone.utc)
    duration_seconds = round((finished_at - started_at).total_seconds(), 2)
    total_posted = sum(posted_by_country.values())
    reddit_enabled = bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))
    diagnostics_message, diagnostic_totals = _format_scan_diagnostics(scan_diagnostics)

    result = {
        "status": "partial_failed" if errors else "succeeded",
        "campaign_name": campaign_name,
        "campaign_focus": campaign_focus,
        "run_type": run_type,
        "country": countries[0] if len(countries) == 1 else "all",
        "countries": countries,
        "platforms": platforms,
        "max_events_per_country": max_events,
        "scanner_timeout_seconds": scanner_timeout,
        "smart_source_scanning": smart_source_scanning,
        "smart_source_base_queries_per_event": smart_base_queries,
        "smart_source_extra_queries_per_event": smart_extra_queries,
        "web_search_http_timeout_seconds": web_search_http_timeout,
        "signals_posted_to_slack": total_posted,
        "signals_posted_by_country": posted_by_country,
        "scan_diagnostics": scan_diagnostics,
        "diagnostic_totals": diagnostic_totals,
        "errors": errors,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "reddit_enabled": reddit_enabled,
    }

    if notify_slack:
        reddit_line = "Enabled" if reddit_enabled else "Skipped until Reddit credentials are added"
        smart_line = "Enabled" if smart_source_scanning else "Disabled"
        per_country_line = ", ".join(f"{country}: {count}" for country, count in posted_by_country.items()) or "none"
        message = (
            "✅ *Apify Social Listener run completed*\n"
            f"{_slack_line('Campaign', campaign_name, code=True)}"
            f"{_slack_line('Focus', campaign_focus)}"
            f"{_slack_line('Run type', run_type, code=True)}"
            f"*Countries:* `{country_label}`\n"
            f"*Platforms:* `{', '.join(platforms)}`\n"
            f"*Max events per country:* `{max_events}`\n"
            f"*Smart source scanning:* `{smart_line}`\n"
            f"*Smart scan mode:* `Light ({smart_base_queries}+{smart_extra_queries} queries, {web_search_http_timeout}s HTTP timeout)`\n"
            f"*Signals posted:* `{total_posted}`\n"
            f"*Per country:* `{per_country_line}`\n"
            f"{diagnostics_message}"
            f"*Reddit:* {reddit_line}\n"
            f"*Duration:* `{duration_seconds}s`"
        )
        if errors:
            error_line = ", ".join(f"{country}: {error}" for country, error in errors.items())
            message += f"\n*Errors:* `{error_line}`"
        _post_slack_status(message)

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
