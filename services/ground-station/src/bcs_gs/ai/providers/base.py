"""The AI provider seam (addendum M): request, provider protocol and provider errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ErrorKind = Literal["rate_limited", "overloaded", "timeout", "unavailable", "invalid_output", "error"]
ERROR_KINDS: tuple[str, ...] = (
    "rate_limited",
    "overloaded",
    "timeout",
    "unavailable",
    "invalid_output",
    "error",
)


@dataclass
class ProviderRequest:
    role: str
    system: str
    parts: list[str | bytes]  # text, or JPEG bytes <= 1024 px
    response_schema: dict  # JSON Schema of the role's output
    temperature: float
    timeout_s: float


class ProviderError(Exception):
    """A failed provider attempt. ``kind`` is one of ``ERROR_KINDS``; ``detail`` is free text that
    must never carry a key value (the gateway masks registered secrets again before logging it)."""

    def __init__(self, kind: ErrorKind, detail: str = "") -> None:
        if kind not in ERROR_KINDS:
            raise ValueError(f"unknown ProviderError kind: {kind!r}")
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind: ErrorKind = kind
        self.detail = detail


class AIProvider(Protocol):
    provider: str  # "gemini" | "ollama" | "rules" | "fake" | a future "trained"

    async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict: ...

    # raises ProviderError(kind="rate_limited"|"overloaded"|"timeout"|"unavailable"|"invalid_output"|"error")
