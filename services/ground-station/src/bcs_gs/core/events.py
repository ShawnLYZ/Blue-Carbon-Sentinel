"""In-process event bus feeding /ws/events (addendum J2)."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from bcs_protocol.timefmt import to_iso

from .clock import Clock, RealClock
from .ids import uuid7


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]
    id: str
    at: str

    def envelope(self) -> dict[str, Any]:
        return {"v": 1, "type": self.type, "id": self.id, "at": self.at, "data": self.data}


class Subscription:
    """Async iterator of events. Closed (and drained) when the subscriber is too slow."""

    def __init__(self, bus: EventBus, maxsize: int) -> None:
        self._bus = bus
        self._maxsize = maxsize
        self._queue: deque[Event] = deque()
        self._wake = asyncio.Event()
        self._closed = False
        self.overflowed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _offer(self, event: Event) -> None:
        if self._closed:
            return
        if len(self._queue) >= self._maxsize:
            self.overflowed = True  # upstream closes the socket with code 1013
            self.close()
            return
        self._queue.append(event)
        self._wake.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.clear()
        self._bus._remove(self)
        self._wake.set()

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:
        while True:
            if self._queue:
                return self._queue.popleft()
            if self._closed:
                raise StopAsyncIteration
            self._wake.clear()
            await self._wake.wait()


@dataclass
class EventBus:
    clock: Clock = field(default_factory=RealClock)
    _subs: list[Subscription] = field(default_factory=list)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, type: str, data: dict[str, Any]) -> Event:
        event = Event(type=type, data=data, id=uuid7(), at=to_iso(self.clock.now()))
        for sub in list(self._subs):
            sub._offer(event)
        return event

    def subscribe(self, maxsize: int = 1000) -> Subscription:
        sub = Subscription(self, maxsize)
        self._subs.append(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)
