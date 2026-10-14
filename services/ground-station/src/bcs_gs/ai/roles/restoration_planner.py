"""RestorationPlanner: per-zone intervention items from the F5 catalogue (product spec section 20)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from bcs_gs.ai.providers.base import ProviderRequest
from bcs_gs.ai.roles._common import (
    RoleConfig,
    default_role_config,
    dumps,
    load_prompt,
    response_schema,
)
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.api.models import ExpectedUplift, Intervention, PlanItem, RiskClass

DENSITY_PER_HA = 4400
MAX_PLANTED_HA = 0.5
AVICENNIA_ABOVE_PSU = 40.0
PRIORITY = {"critical": 1, "high": 2}
PLANT_KINDS = ("plant_rhizophora", "plant_avicennia")
EPS = 1e-6


class PlannerOutput(BaseModel):
    items: list[PlanItem]


class PlannerZone(BaseModel):
    zone_id: str
    risk_class: RiskClass
    stressors: dict[str, float]  # stressor name -> stress score 0-1 (names as in the risk engine)
    class_fractions: dict[str, float]  # canopy / water / mud / other, fractions of the zone
    porewater_psu: float | None = None
    covered: bool = True


@dataclass
class PlannerInput:
    zones: list[PlannerZone]


class RestorationPlanner:
    name = "restoration_planner"
    schema_version = "1"
    prompt_version = "v1"
    output_model = PlannerOutput

    def __init__(self, cfg: RoleConfig | None = None) -> None:
        self.cfg = cfg or default_role_config()

    def request(self, inp: PlannerInput) -> ProviderRequest:
        body = dumps({"zones": [z.model_dump() for z in inp.zones], "planting_density_per_ha": DENSITY_PER_HA})
        return ProviderRequest(
            role=self.name,
            system=load_prompt(self.name, self.prompt_version),
            parts=[body],
            response_schema=response_schema(PlannerOutput),
            temperature=self.cfg.temperature,
            timeout_s=self.cfg.text_timeout_s,
        )

    def check(self, out: PlannerOutput, inp: PlannerInput) -> PlannerOutput:
        known = {z.zone_id for z in inp.zones}
        for it in out.items:
            if it.zone_id not in known:
                raise OutputRejected(f"unknown zone {it.zone_id!r}")
            for iv in it.interventions:  # kinds and priority 1-5 are enforced by the Literal types
                if iv.kind not in PLANT_KINDS:
                    continue
                n = iv.sapling_count or 0
                area = iv.planted_area_ha if iv.planted_area_ha is not None else n / DENSITY_PER_HA
                if n < 0 or area < 0 or n > DENSITY_PER_HA * area + EPS:
                    raise OutputRejected(f"{it.zone_id}: {n} saplings exceed {DENSITY_PER_HA}/ha over {area:g} ha")
        return out

    def rules(self, inp: PlannerInput) -> PlannerOutput:
        items: list[PlanItem] = []
        for z in inp.zones:
            if z.risk_class not in PRIORITY:
                continue
            top = max(sorted(z.stressors), key=lambda k: z.stressors[k], default=None)
            mud = z.class_fractions.get("mud", 0.0)
            ivs: list[Intervention] = []
            if mud > 0:
                area = min(mud, MAX_PLANTED_HA)
                kind = "plant_avicennia" if (z.porewater_psu or 0) > AVICENNIA_ABOVE_PSU else "plant_rhizophora"
                ivs.append(Intervention(kind=kind, planted_area_ha=area, sapling_count=round(area * DENSITY_PER_HA)))
            if top == "turbidity":
                ivs.append(Intervention(kind="silt_fence"))
            elif top in ("porewater_salinity", "do"):
                ivs.append(Intervention(kind="reopen_channel"))
            if not ivs:
                continue
            items.append(
                PlanItem(
                    zone_id=z.zone_id,
                    interventions=ivs,
                    priority=PRIORITY[z.risk_class],
                    rationale=f"{z.risk_class} risk; top stressor {top or 'none'}; mud fraction {mud:g}",
                    # Placeholder: the forecast engine computes the real uplift (M5 Task 4 onwards).
                    expected_uplift=ExpectedUplift(canopy_pp_2035=0.0, tco2e_2035=0.0),
                )
            )
        return PlannerOutput(items=items)
