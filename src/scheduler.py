"""Scheduler — runs all scans on their configured schedule."""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.scanner import scan_country
from src.brand_monitor import scan_brand_and_competitors
from src.price_monitor import scan_price_spikes
from src.trustpilot import check_trustpilot

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Schedule config — all monthly on the configured day, staggered by 10 minutes
SCAN_DAY = int(os.getenv("SCAN_CRON_DAY", "15"))
SCAN_HOUR = int(os.getenv("SCAN_CRON_HOUR", "7"))

COUNTRY_SCHEDULE = [
    ("spain", SCAN_HOUR, 0),
    ("uk", SCAN_HOUR, 10),
    ("us", SCAN_HOUR, 20),
    ("brazil", SCAN_HOUR, 30),
    ("germany", SCAN_HOUR, 40),
    ("taiwan", SCAN_HOUR, 50),
    ("china", SCAN_HOUR + 1, 0),
    ("portugal", SCAN_HOUR + 1, 10),
]


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the scheduler with all jobs."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Country scans — monthly on the configured scan day
    for country, hour, minute in COUNTRY_SCHEDULE:
        scheduler.add_job(
            scan_country,
            CronTrigger(day=SCAN_DAY, hour=hour, minute=minute),
            args=[country],
            id=f"scan_{country}",
            name=f"Scan {country.upper()}",
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(
            "Scheduled %s: day %s at %02d:%02d UTC",
            country.upper(),
            SCAN_DAY,
            hour,
            minute,
        )

    # Brand & competitor scan — monthly on the configured scan day
    scheduler.add_job(
        scan_brand_and_competitors,
        CronTrigger(day=SCAN_DAY, hour=SCAN_HOUR + 1, minute=20),
        id="scan_brand",
        name="Brand & Competitor Scan",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    logger.info(
        "Scheduled Brand scan: day %s at %02d:20 UTC",
        SCAN_DAY,
        SCAN_HOUR + 1,
    )

    # Price spike scan — monthly on the configured scan day
    scheduler.add_job(
        scan_price_spikes,
        CronTrigger(day=SCAN_DAY, hour=SCAN_HOUR + 1, minute=30),
        id="scan_prices",
        name="Price Spike Scan",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    logger.info(
        "Scheduled Price scan: day %s at %02d:30 UTC",
        SCAN_DAY,
        SCAN_HOUR + 1,
    )

    # Trustpilot — daily at 08:00 UTC
    scheduler.add_job(
        check_trustpilot,
        CronTrigger(hour=8, minute=0),
        id="trustpilot",
        name="Trustpilot Review Monitor",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    logger.info("Scheduled Trustpilot: daily at 08:00 UTC")

    return scheduler


async def main() -> None:
    """Start the scheduler and keep the same asyncio loop alive."""
    logger.info("=" * 50)
    logger.info("SplitStay Social Listener — Starting Scheduler")
    logger.info("=" * 50)

    scheduler = create_scheduler()
    scheduler.start()

    logger.info("")
    logger.info("All jobs scheduled. Next scan day: %sth of the month.", SCAN_DAY)
    logger.info("Trustpilot checks daily at 08:00 UTC.")
    logger.info("Press Ctrl+C to stop.")
    logger.info("")

    try:
        # Keep the running event loop alive for APScheduler.
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Scheduler cancellation requested.")
    finally:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    asyncio.run(main())
