"""HistorySynthesizer: a 2016-2025 stand-in series per zone (seeded random walk as rules)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from pydantic import BaseModel, Field

from bcs_gs.ai.providers.base import ProviderRequest
from bcs_gs.ai.roles._common import RoleConfig, default_role_config, dumps, load_prompt, response_schema
from bcs_gs.ai.roles.base import OutputRejected

YEARS = list(range(2016, 2026))
END_TOLERANCE_PP = 10.0
RULES_SIGMA_PP = 2.0
VARI_PER_PP = 0.01  # rules: vari_equiv slope against canopy change


class HistoryPoint(BaseModel):
    year: int = Field(ge=2016, le=2025)
    canopy_pct: float = Field(ge=0, le=100)
    vari_equiv: float = Field(ge=-1, le=1)
    note: str | None = None


class HistoryOutput(BaseModel):
    series: dict[str, list[HistoryPoint]]


@dataclass
class HistoryInput:
    zones: dict[str, dict[str, float | None]]  # zone -> {canopy_pct, vari_mean}
    site_context: str
    seed: int


class HistorySynthesizer:
    name = "history_synthesizer"
    schema_version = "1"
    prompt_version = "v1"
    output_model = HistoryOutput

    def __init__(self, cfg: RoleConfig | None = None) -> None:
        self.cfg = cfg or default_role_config()

    def request(self, inp: HistoryInput) -> ProviderRequest:
        body = dumps({"zones": inp.zones, "site_context": inp.site_context, "seed": inp.seed})
        return ProviderRequest(
            role=self.name,
            system=load_prompt(self.name, self.prompt_version),
            parts=[body],
            response_schema=response_schema(HistoryOutput),
            temperature=self.cfg.temperature,
            timeout_s=self.cfg.text_timeout_s,
        )

    def check(self, out: HistoryOutput, inp: HistoryInput) -> HistoryOutput:
        if set(out.series) != set(inp.zones):
            raise OutputRejected("series zones differ from the input zones")
        for zone, pts in out.series.items():
            if sorted(p.year for p in pts) != YEARS:
                raise OutputRejected(f"{zone}: need exactly one point per year 2016-2025")
            last = next(p for p in pts if p.year == 2025)
            if abs(last.canopy_pct - float(inp.zones[zone]["canopy_pct"] or 0.0)) > END_TOLERANCE_PP:
                raise OutputRejected(f"{zone}: 2025 canopy is not within 10 pp of the measured value")
        return out

    def rules(self, inp: HistoryInput) -> HistoryOutput:
        series: dict[str, list[HistoryPoint]] = {}
        for zone, cur in inp.zones.items():
            rng = random.Random(f"{inp.seed}:{zone}")
            now = float(cur["canopy_pct"] or 0.0)
            vari_now = float(cur.get("vari_mean") or 0.0)
            vals = [now]
            for _ in YEARS[:-1]:  # walk back from the measured 2025 value
                vals.append(min(100.0, max(0.0, vals[-1] + rng.gauss(0.0, RULES_SIGMA_PP))))
            vals.reverse()
            series[zone] = [
                HistoryPoint(
                    year=y,
                    canopy_pct=round(v, 2),
                    vari_equiv=round(min(1.0, max(-1.0, vari_now + (v - now) * VARI_PER_PP)), 3),
                )
                for y, v in zip(YEARS, vals, strict=True)
            ]
        return HistoryOutput(series=series)
