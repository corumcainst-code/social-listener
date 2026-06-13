"""Smart container entrypoint.

- On Apify: run a one-off Actor scan and finish.
- Everywhere else: run the long-lived monthly scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _running_on_apify() -> bool:
    """Detect whether this container is running on Apify."""
    if os.getenv("RUN_MODE", "").strip().lower() in {"apify", "actor", "one-shot", "one_shot"}:
        return True

    apify_markers = (
        "APIFY_IS_AT_HOME",
        "APIFY_TOKEN",
        "APIFY_ACTOR_RUN_ID",
        "APIFY_DEFAULT_KEY_VALUE_STORE_ID",
        "APIFY_DEFAULT_DATASET_ID",
    )
    return any(os.getenv(name) for name in apify_markers)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if _running_on_apify():
        logger.info("Apify environment detected — running one-off Actor scan")
        from src.apify_actor import main as apify_main

        asyncio.run(apify_main())
        return

    logger.info("Standard environment detected — running scheduler")
    from src.scheduler import main as scheduler_main

    asyncio.run(scheduler_main())


if __name__ == "__main__":
    main()
