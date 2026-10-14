"""Simulator time source: real in production, manual in tests (mirrors ``bcs_gs.core.clock``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("ManualClock start must be timezone-aware")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
