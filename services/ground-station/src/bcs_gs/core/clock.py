"""Time source: real in production, manual in tests (addendum M)."""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class ManualClock:
    """Deterministic clock; time moves only through ``advance`` and ``set``."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("ManualClock start must be timezone-aware")
        self._start = start.astimezone(UTC)
        self._now = self._start
        self._heap: list[tuple[datetime, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()
        # sleep() runs on the event loop while advance()/set() may come from a test thread.
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def monotonic(self) -> float:
        with self._lock:
            return (self._now - self._start).total_seconds()

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        with self._lock:
            heapq.heappush(self._heap, (self._now + timedelta(seconds=seconds), next(self._seq), fut))
        await fut

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)
            due = self._pop_due()
        self._wake(due)

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("ManualClock.set requires a timezone-aware datetime")
        with self._lock:
            self._now = at.astimezone(UTC)
            due = self._pop_due()
        self._wake(due)

    def reset(self) -> None:
        """Back to the start time (test reset). Every sleeper is woken so none waits on a time that
        now lies far in the future; loops simply sleep again from the new time."""
        with self._lock:
            self._now = self._start
            due = [entry[2] for entry in self._heap]
            self._heap.clear()
        self._wake(due)

    def _pop_due(self) -> list[asyncio.Future[None]]:
        due: list[asyncio.Future[None]] = []
        while self._heap and self._heap[0][0] <= self._now:
            due.append(heapq.heappop(self._heap)[2])
        return due

    @staticmethod
    def _wake(due: list[asyncio.Future[None]]) -> None:
        for fut in due:
            fut_loop = fut.get_loop()
            try:
                same_loop = asyncio.get_running_loop() is fut_loop
            except RuntimeError:
                same_loop = False
            if same_loop:
                if not fut.done():
                    fut.set_result(None)
            else:  # advanced from another thread (the seam-1 harness): wake the owning loop safely
                try:
                    fut_loop.call_soon_threadsafe(lambda f=fut: f.done() or f.set_result(None))
                except RuntimeError:  # owning loop already closed: nobody is waiting any more
                    pass
