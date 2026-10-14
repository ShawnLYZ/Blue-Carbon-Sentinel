"""Packet inspector tap (addendum K2 ``inspector.packet``).

Every node transport calls ``emit`` for each message it sends ("up": node -> Ground Station) and each
message it receives ("down": Ground Station -> node, as received by that node). The packet is
validated with the same parser the Ground Station uses (``bcs_protocol.validate.parse_message``),
kept in a bounded buffer for ``drain()`` and pushed to listeners (the simulator ``/ws`` hub, the
session recorder). ``emit`` may be called from any thread; listeners run on the caller's thread and
must not block.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from bcs_protocol.timefmt import to_iso
from bcs_protocol.validate import ProtocolError, parse_message

from .clock import Clock

log = logging.getLogger("bcs_sim.inspector")
BUFFER = 2000

Direction = Literal["up", "down"]


@dataclass(frozen=True)
class InspectorPacket:
    at: datetime
    direction: Direction
    node_id: str
    channel: str
    topic: str
    raw: bytes = field(repr=False)
    payload: Any  # parsed JSON when the bytes are JSON, else the text
    valid: bool
    errors: list[str]

    def data(self) -> dict[str, Any]:
        return {
            "at": to_iso(self.at),
            "direction": self.direction,
            "node_id": self.node_id,
            "channel": self.channel,
            "topic": self.topic,
            "payload": self.payload,
            "valid": self.valid,
            "errors": list(self.errors),
        }

    def message(self) -> dict[str, Any]:
        """The K2 ``/ws`` message."""
        return {"type": "inspector.packet", "data": self.data()}


def _decode(payload: bytes) -> Any:
    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


class InspectorTap:
    def __init__(self, clock: Clock, buffer: int = BUFFER) -> None:
        self.clock = clock
        self._buf: deque[InspectorPacket] = deque(maxlen=buffer)
        self._lock = threading.Lock()
        self._listeners: list[Callable[[InspectorPacket], None]] = []

    def add_listener(self, fn: Callable[[InspectorPacket], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[InspectorPacket], None]) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def emit(
        self, direction: Direction, node_id: str, channel: str, topic: str, payload: bytes
    ) -> InspectorPacket:
        try:
            parse_message(channel, payload)
            valid, errors = True, []
        except ProtocolError as exc:
            valid, errors = False, list(exc.errors)
        pkt = InspectorPacket(
            self.clock.now(),
            direction,
            node_id,
            channel,
            topic,
            bytes(payload),
            _decode(payload),
            valid,
            errors,
        )
        with self._lock:
            self._buf.append(pkt)
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(pkt)
            except Exception:
                log.exception("inspector listener failed")
        return pkt

    def drain(self) -> list[InspectorPacket]:
        with self._lock:
            out = list(self._buf)
            self._buf.clear()
        return out
