"""Battery model (design spec 13): drain per sample and per transmission; low below 15 %."""

from __future__ import annotations

LOW_PCT = 15.0


class Battery:
    def __init__(self, start_pct: float = 100.0, per_sample: float = 0.02, per_tx: float = 0.01) -> None:
        self.pct = float(start_pct)
        self.per_sample = per_sample
        self.per_tx = per_tx

    def drain(self, samples: int = 1, tx: int = 1) -> float:
        self.pct = max(0.0, self.pct - samples * self.per_sample - tx * self.per_tx)
        return self.pct

    def set(self, pct: float) -> None:
        self.pct = min(max(float(pct), 0.0), 100.0)

    @property
    def low(self) -> bool:
        return self.pct < LOW_PCT
