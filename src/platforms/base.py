"""Base scanner interface — all platform scanners implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import Event, Signal


class Scanner(ABC):
    """
    Uniform interface for all platform scanners.

    Every scanner has a ``name`` and a single ``scan()`` method with the same
    signature.  This lets ``scanner.py`` iterate over scanners without knowing
    anything about the underlying platform.

    HTTP clients (httpx, PRAW, etc.) should be created **inside** ``scan()``
    (ideally with ``async with``) so callers never need to remember to call
    ``.close()``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name shown in logs (e.g. 'Reddit', 'Twitter/X')."""
        ...

    @abstractmethod
    async def scan(
        self,
        events: list[Event],
        country: str,
        max_age_days: int = 60,
    ) -> list[Signal]:
        """
        Scan this platform for accommodation-sharing signals.

        Returns deduplicated signals found for the given events/country.
        Must not raise — catch and log errors internally, returning whatever
        was collected before the failure.
        """
        ...
