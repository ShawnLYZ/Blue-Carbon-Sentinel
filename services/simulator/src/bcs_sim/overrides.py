"""Per-node slider overrides: ``hold`` pins a value, ``drift`` decays it back to natural (tau 60 s)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .clock import Clock

DRIFT_TAU_S = 60.0


@dataclass(frozen=True)
class Override:
    value: float
    behaviour: Literal["hold", "drift"]
    set_at: datetime


class Overrides:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._o: dict[tuple[str, str], Override] = {}

    def set(self, node_id: str, parameter: str, value: float, behaviour: Literal["hold", "drift"]) -> None:
        if behaviour not in ("hold", "drift"):
            raise ValueError(f"unknown behaviour: {behaviour}")
        self._o[(node_id, parameter)] = Override(float(value), behaviour, self.clock.now())

    def clear(self, node_id: str, parameter: str | None = None) -> None:
        if parameter is None:
            for k in [k for k in self._o if k[0] == node_id]:
                del self._o[k]
        else:
            self._o.pop((node_id, parameter), None)

    def active(self, node_id: str | None = None) -> dict[tuple[str, str], Override]:
        return {k: v for k, v in self._o.items() if node_id is None or k[0] == node_id}

    def apply(self, node_id: str, natural: dict[str, float], at: datetime) -> dict[str, float]:
        out = dict(natural)
        for (nid, param), o in self._o.items():
            if nid != node_id or param not in natural:
                continue
            if o.behaviour == "hold":
                out[param] = o.value
            else:
                dt = max((at - o.set_at).total_seconds(), 0.0)
                out[param] = natural[param] + (o.value - natural[param]) * math.exp(-dt / DRIFT_TAU_S)
        return out
