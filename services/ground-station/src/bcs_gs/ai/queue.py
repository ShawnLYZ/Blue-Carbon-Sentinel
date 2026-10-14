"""Per-tier admission in priority order (operator > flagged zone > background)."""

from __future__ import annotations

import asyncio
import heapq
import itertools

from bcs_gs.ai.roles.base import Priority


class PriorityGate:
    """At most ``capacity`` requests in flight; waiting requests are admitted highest priority first
    (FIFO within a priority). With ``capacity`` > 1, background requests never take the last free slot,
    so a background backlog cannot hold up an operator or flagged-zone request."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.in_use = 0
        self._waiters: list[tuple[int, int, Priority, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    @property
    def waiting(self) -> int:
        return sum(1 for w in self._waiters if not w[3].done())

    def _admits(self, priority: Priority) -> bool:
        if self.in_use >= self.capacity:
            return False
        if priority <= Priority.BACKGROUND and self.capacity > 1:
            return self.in_use < self.capacity - 1
        return True

    async def acquire(self, priority: Priority) -> None:
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (-int(priority), next(self._seq), priority, fut))
        self._dispatch()
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():  # admitted just as we were cancelled: give it back
                self.release()
            else:
                fut.cancel()
                self._dispatch()
            raise

    def release(self) -> None:
        self.in_use = max(0, self.in_use - 1)
        self._dispatch()

    def _dispatch(self) -> None:
        while self._waiters:
            _, _, priority, fut = self._waiters[0]
            if fut.done():  # cancelled waiter
                heapq.heappop(self._waiters)
                continue
            if not self._admits(priority):
                return
            heapq.heappop(self._waiters)
            self.in_use += 1
            fut.set_result(None)
