"""Request budget: a token bucket per (key slot, model)."""

from __future__ import annotations

from bcs_gs.core.clock import Clock


class TokenBucket:
    """``rate_per_min`` requests per minute: starts full (capacity = rate) and refills continuously."""

    def __init__(self, rate_per_min: float, clock: Clock) -> None:
        self.capacity = float(rate_per_min)
        self._per_s = rate_per_min / 60.0
        self._clock = clock
        self._tokens = self.capacity
        self._at = clock.monotonic()

    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens

    def try_take(self) -> bool:
        self._refill()
        if self._tokens >= 1 - 1e-9:
            self._tokens = max(0.0, self._tokens - 1)
            return True
        return False

    def _refill(self) -> None:
        now = self._clock.monotonic()
        if now > self._at:
            self._tokens = min(self.capacity, self._tokens + (now - self._at) * self._per_s)
        self._at = now
