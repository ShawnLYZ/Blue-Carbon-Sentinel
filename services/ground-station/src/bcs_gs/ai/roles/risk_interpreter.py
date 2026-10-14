"""RiskInterpreter: multipliers in [0.5, 1.5], ranked root causes and a narrative (code owns the numbers)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from bcs_gs.ai.providers.base import ProviderRequest
from bcs_gs.ai.roles._common import (
    RoleConfig,
    default_role_config,
    dumps,
    load_prompt,
    numeric_values,
    reject_foreign_numbers,
    response_schema,
)
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.api.models import ZoneMetrics

ACTIONS = {
    "vegetation": "Re-image the zone and compare canopy against the baseline",
    "salinity": "Check water salinity at the nearest node and tidal exchange",
    "porewater_salinity": "Sample porewater salinity around the roots",
    "turbidity": "Look for upstream sediment sources or disturbance",
    "do": "Check the dissolved oxygen sensor and water stagnation",
    "temperature": "Check the water temperature trend and shading",
    "ph": "Verify pH probe calibration and look for runoff",
}


class RootCauseOut(BaseModel):
    driver: str
    rank: int = Field(ge=1)
    why: str


class RiskOutput(BaseModel):
    multipliers: dict[str, float]  # bounds enforced by RiskInterpreter.check (-> invalid_output)
    root_causes: list[RootCauseOut]
    narrative: str = Field(max_length=600)
    actions: list[str] = Field(max_length=5)


@dataclass
class RiskInput:
    zone_id: str
    stressors: dict[str, float]  # measured stressors only: name -> stress score 0-1
    metrics: ZoneMetrics | None
    readings_summary: dict[str, float]  # stressor -> representative reading (units from bands.yaml)
    context: str | dict[str, Any] = field(default="")


class RiskInterpreter:
    name = "risk_interpreter"
    schema_version = "1"
    prompt_version = "v1"
    output_model = RiskOutput

    def __init__(self, cfg: RoleConfig | None = None) -> None:
        self.cfg = cfg or default_role_config()

    def request(self, inp: RiskInput) -> ProviderRequest:
        body = dumps(
            {
                "zone_id": inp.zone_id,
                "stressors": inp.stressors,
                "weights": {k: self.cfg.weights[k] for k in inp.stressors if k in self.cfg.weights},
                "units": {k: self.cfg.units[k] for k in inp.readings_summary if k in self.cfg.units},
                "metrics": inp.metrics.model_dump() if inp.metrics else None,
                "readings_summary": inp.readings_summary,
                "context": inp.context,
            }
        )
        return ProviderRequest(
            role=self.name,
            system=load_prompt(self.name, self.prompt_version),
            parts=[body],
            response_schema=response_schema(RiskOutput),
            temperature=self.cfg.temperature,
            timeout_s=self.cfg.text_timeout_s,
        )

    def check(self, out: RiskOutput, inp: RiskInput) -> RiskOutput:
        lo, hi = self.cfg.multiplier_bounds
        for key, v in out.multipliers.items():
            if key not in inp.stressors:
                raise OutputRejected(f"multiplier for unmeasured stressor {key!r}")
            if not (lo <= v <= hi):
                raise OutputRejected(f"multiplier {key}={v} outside [{lo}, {hi}]")
        allowed = numeric_values(
            [inp.stressors, inp.readings_summary, inp.metrics, self.cfg.weights, inp.context]
        )
        texts = [out.narrative, *(c.why for c in out.root_causes), *out.actions]
        reject_foreign_numbers(texts, allowed)
        return out

    def rules(self, inp: RiskInput) -> RiskOutput:
        ranked = sorted(inp.stressors, key=lambda k: -self.cfg.weights.get(k, 0.0) * inp.stressors[k])
        top = [k for k in ranked if inp.stressors[k] > 0][:3] or ranked[:1]
        causes = [
            RootCauseOut(
                driver=k,
                rank=i + 1,
                why=f"{k} stress score {inp.stressors[k]:.2f} at weight {self.cfg.weights.get(k, 0.0):.2f}",
            )
            for i, k in enumerate(top)
        ]
        if top:
            narrative = f"Main driver: {top[0]}{self._reading(top[0], inp)}, ranked by weight times stress."
        else:
            narrative = f"No measured stressors for {inp.zone_id}; risk is unassessed."
        return RiskOutput(
            multipliers={k: 1.0 for k in inp.stressors},
            root_causes=causes,
            narrative=narrative[:600],
            actions=[ACTIONS[k] for k in top if k in ACTIONS][:5],
        )

    def _reading(self, driver: str, inp: RiskInput) -> str:
        """ " ({value} {unit})" from the readings summary; vegetation falls back to the canopy loss;
        empty when the stressor has no reading."""
        if driver in inp.readings_summary:
            unit = self.cfg.units.get(driver, "")
            return f" ({inp.readings_summary[driver]:g}{' ' + unit if unit else ''})"
        if driver == "vegetation" and inp.metrics is not None and inp.metrics.canopy_loss_pp is not None:
            return f" ({inp.metrics.canopy_loss_pp:g} pp canopy loss)"
        return ""
