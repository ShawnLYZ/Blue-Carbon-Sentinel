"""VisionAnalyst: qualitative observations on the current vs previous raster (numbers stay code's)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from bcs_gs.ai.providers.base import ProviderRequest
from bcs_gs.ai.roles._common import (
    RoleConfig,
    default_role_config,
    downscale_jpeg,
    dumps,
    load_prompt,
    numeric_values,
    reject_foreign_numbers,
    response_schema,
)
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.api.models import ZoneMetrics

Kind = Literal["dieback", "clearing", "new_growth", "discolouration", "none"]


class VisionObservation(BaseModel):
    zone_id: str
    kind: Kind
    confidence: float = Field(ge=0, le=1)
    text: str = Field(max_length=200)


class VisionOutput(BaseModel):
    observations: list[VisionObservation]
    narrative: str = Field(max_length=600)


@dataclass
class VisionInput:
    zone_ids: list[str]
    current_jpeg: bytes
    previous_jpeg: bytes
    metrics: dict[str, ZoneMetrics]


class VisionAnalyst:
    name = "vision_analyst"
    schema_version = "1"
    prompt_version = "v1"
    output_model = VisionOutput

    def __init__(self, cfg: RoleConfig | None = None) -> None:
        self.cfg = cfg or default_role_config()

    def request(self, inp: VisionInput) -> ProviderRequest:
        body = dumps(
            {"zone_ids": inp.zone_ids, "metrics": {z: m.model_dump() for z, m in sorted(inp.metrics.items())}}
        )
        return ProviderRequest(
            role=self.name,
            system=load_prompt(self.name, self.prompt_version),
            parts=[
                body,
                "Previous raster:",
                downscale_jpeg(inp.previous_jpeg, self.cfg.max_image_px),
                "Current raster:",
                downscale_jpeg(inp.current_jpeg, self.cfg.max_image_px),
            ],
            response_schema=response_schema(VisionOutput),
            temperature=self.cfg.temperature,
            timeout_s=self.cfg.vision_timeout_s,
        )

    def check(self, out: VisionOutput, inp: VisionInput) -> VisionOutput:
        for o in out.observations:
            if o.zone_id not in inp.zone_ids:
                raise OutputRejected(f"observation for unknown zone {o.zone_id!r}")
        allowed = numeric_values({z: m.model_dump(exclude={"zone_id"}) for z, m in inp.metrics.items()})
        reject_foreign_numbers([out.narrative, *(o.text for o in out.observations)], allowed)
        return out

    def rules(self, inp: VisionInput) -> VisionOutput:
        obs: list[VisionObservation] = []
        parts: list[str] = []
        for z in inp.zone_ids:
            zm = inp.metrics.get(z)
            if zm is None:
                continue
            kinds = {f.kind for f in zm.flags}
            kind: Kind
            if kinds & {"dieback", "canopy_loss", "index_drop"}:
                kind = "dieback"
            elif "discolouration" in kinds:
                kind = "discolouration"
            elif "new_growth" in kinds:
                kind = "new_growth"
            else:
                kind = "none"
            flags = ", ".join(sorted(kinds)) or "no flags"
            obs.append(
                VisionObservation(
                    zone_id=z,
                    kind=kind,
                    confidence=0.5,
                    text=f"Measured canopy {zm.canopy_pct:g}%, {flags}"[:200],
                )
            )
            parts.append(f"{z}: canopy {zm.canopy_pct:g}%" + (f" ({kind})" if kind != "none" else ""))
        narrative = ("Measured: " + "; ".join(parts) + ".") if parts else "No zone metrics available."
        return VisionOutput(observations=obs, narrative=narrative[:600])
