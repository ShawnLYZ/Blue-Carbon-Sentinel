"""The deterministic floor of every chain. The gateway calls ``role.rules(inp)`` itself for the rules
tier; this class is the seam-shaped equivalent.

``generate(model, req, key_slot)`` carries neither role nor input, so a RulesProvider is either used
through ``run(role, inp)`` or bound to one call with ``RulesProvider.bound(role, inp)`` (then
``generate`` returns that call's rules output as a dict). An unbound ``generate`` raises
``unavailable``: the only way this class can raise."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from bcs_gs.ai.providers.base import ProviderError, ProviderRequest

log = logging.getLogger(__name__)


class RulesProvider:
    provider = "rules"

    def __init__(self, role: Any = None, inp: Any = None) -> None:
        self._role, self._inp = role, inp

    @classmethod
    def bound(cls, role: Any, inp: Any) -> RulesProvider:
        return cls(role, inp)

    def run(self, role: Any, inp: Any) -> BaseModel | None:
        """``role.rules(inp)``; a failing rule is logged and gives ``None`` rather than raising."""
        try:
            return role.rules(inp)
        except Exception:
            log.exception("rules for role %s failed", getattr(role, "name", "?"))
            return None

    async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict:
        if self._role is None:
            raise ProviderError("unavailable", "RulesProvider is not bound to a role call")
        out = self.run(self._role, self._inp)
        if out is None:
            raise ProviderError("unavailable", "rules failed")
        return out.model_dump(mode="json")
