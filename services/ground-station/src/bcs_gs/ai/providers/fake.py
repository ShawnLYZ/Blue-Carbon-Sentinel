"""Scripted test double for the AI provider seam."""

from __future__ import annotations

from typing import Any

from bcs_gs.ai.providers.base import ProviderError, ProviderRequest

Outcome = dict[str, Any] | ProviderError


class FakeProvider:
    """Plays ``script`` in order, one outcome per ``generate`` call: a dict is returned as the raw
    output, a ``ProviderError`` is raised (a fresh copy each time, so one instance may be repeated).

    * A scripted ``timeout`` first advances ``clock`` (when it has ``advance``, i.e. a ManualClock)
      by the request's ``timeout_s``, as a real timed-out attempt would have consumed it.
    * An exhausted script raises ``ProviderError("unavailable")``, like a provider that is not there.

    Every request is recorded in ``requests`` and ``(model, key_slot)`` in ``calls``.
    """

    def __init__(
        self, script: list[Outcome] | None = None, *, clock: Any = None, provider: str = "fake"
    ) -> None:
        self.script: list[Outcome] = list(script or [])
        self.clock = clock
        self.provider = provider
        self.requests: list[ProviderRequest] = []
        self.calls: list[tuple[str, int | None]] = []

    async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict:
        self.requests.append(req)
        self.calls.append((model, key_slot))
        if not self.script:
            raise ProviderError("unavailable", "fake script exhausted")
        outcome = self.script.pop(0)
        if isinstance(outcome, ProviderError):
            if outcome.kind == "timeout" and hasattr(self.clock, "advance"):
                self.clock.advance(req.timeout_s)
            raise ProviderError(outcome.kind, outcome.detail)
        return dict(outcome)
