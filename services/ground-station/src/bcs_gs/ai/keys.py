"""Gemini key rotation: round-robin over the key slots with per-(slot, model) cool-downs.

Only slot numbers (1-3) live here; key values stay inside the providers."""

from __future__ import annotations

from collections.abc import Collection

from bcs_gs.core.clock import Clock


class KeyRing:
    """Round-robin over ``slots`` per model, skipping slots in cool-down.

    A cool-down (after a 429, a 503 or a timeout) lasts ``cooldown_s`` and doubles on every further
    strike up to ``cooldown_max_s``; ``reset`` (on success) clears the strikes."""

    def __init__(
        self,
        slots: list[int],
        clock: Clock,
        *,
        cooldown_s: float = 60,
        cooldown_max_s: float = 600,
        backoff: float = 2,
    ) -> None:
        self.slots = list(slots)
        self._clock = clock
        self._cooldown_s = cooldown_s
        self._cooldown_max_s = cooldown_max_s
        self._backoff = backoff
        self._next: dict[str, int] = {}  # model -> index into slots of the next slot to offer
        self._until: dict[tuple[int, str], float] = {}  # (slot, model) -> monotonic end of cool-down
        self._strikes: dict[tuple[int, str], int] = {}

    def next_available(self, model: str, exclude: Collection[int] = ()) -> int | None:
        """The next slot (round-robin) that is not cooling down and not in ``exclude``; None when
        there is none. Never waits."""
        n = len(self.slots)
        start = self._next.get(model, 0)
        for i in range(n):
            idx = (start + i) % n
            slot = self.slots[idx]
            if slot in exclude or self.in_cooldown(slot, model):
                continue
            self._next[model] = (idx + 1) % n
            return slot
        return None

    def cooldown(self, slot: int, model: str) -> float:
        """Start (or extend) the cool-down of ``slot`` for ``model``; returns its length in seconds."""
        key = (slot, model)
        strikes = self._strikes.get(key, 0)
        length = min(self._cooldown_s * self._backoff**strikes, self._cooldown_max_s)
        self._strikes[key] = strikes + 1
        self._until[key] = self._clock.monotonic() + length
        return length

    def reset(self, slot: int, model: str) -> None:
        key = (slot, model)
        self._strikes.pop(key, None)
        self._until.pop(key, None)

    def in_cooldown(self, slot: int, model: str) -> bool:
        return self.cooldown_remaining(slot, model) > 0

    def cooldown_remaining(self, slot: int, model: str) -> float:
        until = self._until.get((slot, model))
        return 0.0 if until is None else max(0.0, until - self._clock.monotonic())
