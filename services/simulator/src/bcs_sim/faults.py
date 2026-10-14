"""Per-node fault injection (spec section 13): shapes readings before publish and messages at publish.

Task 5 runtime contract, per node, per sample:
    readings = produce_readings(...)
    readings = faults.shape_readings(readings, now)
    msgs = faults.shape_outgoing([OutgoingMsg(...)], now, interval_s=<current sampling interval>)
    if faults.is_offline(): drop the connection WITHOUT sending DISCONNECT (last will fires), publish nothing
    else: publish msgs
Call ``shape_outgoing([], now, ...)`` on ticks with no new message so held ("late") messages are released.

``low_battery`` is only recorded here; the runtime applies it by setting the node's Battery pct to
``params["pct"]`` when the fault is injected (Battery owns the behaviour).

Fault start times come from ``clock.now()`` at inject when a clock is given, else from the first
``shape_readings`` call after inject.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from .clock import Clock
from .config import SimConfig

KINDS = frozenset(
    {"offline", "stuck", "spikes", "drift", "low_battery", "late", "duplicate", "out_of_order", "malformed"}
)
LATE_INTERVALS = 3  # default late delay = 3 x the node's current sampling interval


@dataclass(frozen=True)
class OutgoingMsg:
    node_id: str
    channel: str  # e.g. "telemetry", "health", "event"
    payload: bytes
    seq: int
    qos: int = 0
    retain: bool = False


class FaultSet:
    def __init__(self, seed: int, clock: Clock | None = None) -> None:
        self._rng = random.Random(seed)
        self._clock = clock
        self._faults: dict[str, dict[str, Any]] = {}
        self._start: dict[str, datetime | None] = {}
        self._stuck: dict[str, float] = {}
        self._next_spike: datetime | None = None
        self._held: list[tuple[datetime, OutgoingMsg]] = []
        self._malformed_n = 0

    # -- management ---------------------------------------------------------------------------
    def inject(self, kind: str, params: dict[str, Any] | None = None) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown fault kind: {kind}")
        self.clear(kind)
        self._faults[kind] = dict(params or {})
        self._start[kind] = self._clock.now() if self._clock else None

    def clear(self, kind: str) -> None:
        self._faults.pop(kind, None)
        self._start.pop(kind, None)
        if kind == "stuck":
            self._stuck.clear()
        if kind == "spikes":
            self._next_spike = None
        if kind == "late":
            self._held.clear()

    def active(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self._faults.items()}

    def is_offline(self) -> bool:
        return "offline" in self._faults

    # -- readings -----------------------------------------------------------------------------
    def _started(self, kind: str, at: datetime) -> datetime:
        start = self._start.get(kind)
        if start is None:
            start = self._start[kind] = at
        return start

    def shape_readings(self, readings: dict[str, float], at: datetime) -> dict[str, float]:
        out = dict(readings)
        if (p := self._faults.get("stuck")) is not None:
            self._started("stuck", at)
            param = p.get("parameter")
            if param in out:
                out[param] = self._stuck.setdefault(param, out[param])
        if (p := self._faults.get("drift")) is not None:
            hours = (at - self._started("drift", at)).total_seconds() / 3600
            if p.get("parameter") in out:
                out[p["parameter"]] += float(p.get("rate_per_h", 0.0)) * max(hours, 0.0)
        if (p := self._faults.get("spikes")) is not None:
            start = self._started("spikes", at)
            rate = float(p.get("rate_per_min", 1.0))
            param = p.get("parameter")
            if rate > 0 and param in out:
                nxt = self._next_spike or start + self._gap(rate)
                hit = False
                while nxt <= at:
                    hit = True
                    nxt += self._gap(rate)
                self._next_spike = nxt
                if hit:
                    sigma = float(p.get("sigma", SimConfig().noise_sigma.model_dump()[param]))
                    sign = self._rng.choice((-1.0, 1.0))
                    out[param] += sign * float(p.get("magnitude", 5.0)) * sigma
        return out

    def preview_readings(self, readings: dict[str, float], at: datetime) -> dict[str, float]:
        """What ``shape_readings`` would show for a live view, without changing any fault state: a held
        ``stuck`` value and the ``drift`` offset apply; random ``spikes`` do not."""
        out = dict(readings)
        if (p := self._faults.get("stuck")) is not None and p.get("parameter") in self._stuck:
            out[p["parameter"]] = self._stuck[p["parameter"]]
        if (p := self._faults.get("drift")) is not None and p.get("parameter") in out:
            start = self._start.get("drift") or at
            hours = max((at - start).total_seconds() / 3600, 0.0)
            out[p["parameter"]] += float(p.get("rate_per_h", 0.0)) * hours
        return out

    def _gap(self, rate_per_min: float) -> timedelta:
        return timedelta(seconds=-math.log(1.0 - self._rng.random()) * 60.0 / rate_per_min)

    # -- delivery -----------------------------------------------------------------------------
    def shape_outgoing(
        self, messages: list[OutgoingMsg], at: datetime, interval_s: float | None = None
    ) -> list[OutgoingMsg]:
        """``interval_s`` (caller-supplied current sampling interval) sets the default late delay."""
        msgs = list(messages)
        released = [m for t, m in self._held if t <= at]
        self._held = [(t, m) for t, m in self._held if t > at]
        if (p := self._faults.get("late")) is not None:
            if "delay_s" in p:
                delay = float(p["delay_s"])
            elif (iv := p.get("interval_s", interval_s)) is not None:
                delay = LATE_INTERVALS * float(iv)
            else:
                raise ValueError("late fault needs delay_s, an interval_s param, or the interval_s argument")
            self._held += [(at + timedelta(seconds=delay), m) for m in msgs]
            msgs = []
        msgs = released + msgs
        if "out_of_order" in self._faults:
            for i in range(0, len(msgs) - 1, 2):
                msgs[i], msgs[i + 1] = msgs[i + 1], msgs[i]
        if "malformed" in self._faults:
            msgs = [self._malform(m) for m in msgs]
        if "duplicate" in self._faults:
            msgs = [x for m in msgs for x in (m, m)]
        return msgs

    def _malform(self, m: OutgoingMsg) -> OutgoingMsg:
        self._malformed_n += 1
        if self._malformed_n % 2 == 1:
            return replace(m, payload=b'{"schema": "bcs.telemetry.v1", "readings": {')
        try:
            doc = json.loads(m.payload)
            doc.pop("readings", None)
            return replace(m, payload=json.dumps(doc).encode())
        except ValueError:
            return replace(m, payload=b"{}")
