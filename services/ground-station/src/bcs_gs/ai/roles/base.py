"""The AI role seam (addendum M), call priorities and the output-rejection error."""

from __future__ import annotations

from enum import IntEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

from bcs_gs.ai.providers.base import ProviderRequest

I = TypeVar("I")  # names as in addendum M
O = TypeVar("O", bound=BaseModel)


class Priority(IntEnum):
    """Order of waiting requests: operator > flagged zone > background."""

    OPERATOR = 3
    FLAGGED = 2
    BACKGROUND = 1


class OutputRejected(Exception):
    """Raised by ``Role.check`` when an output is schema-valid but out of bounds or inconsistent;
    the gateway counts it as ``invalid_output`` and moves to the next tier."""


class Role(Protocol[I, O]):
    name: str
    schema_version: str
    prompt_version: str
    output_model: type[O]  # Pydantic model; bounds included

    def request(self, inp: I) -> ProviderRequest: ...

    def check(self, out: O, inp: I) -> O: ...  # bounds and consistency; raises OutputRejected

    def rules(self, inp: I) -> O: ...  # deterministic last tier
