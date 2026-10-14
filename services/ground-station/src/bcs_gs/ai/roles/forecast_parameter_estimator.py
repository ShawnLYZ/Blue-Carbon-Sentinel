"""ForecastParameterEstimator: per-zone forecast parameters as pessimistic / central / optimistic bands.

Bands are outcome-ordered (ruling R1): ``low`` is the pessimistic value and ``high`` the optimistic one, so
"higher is better" parameters satisfy low <= central <= high and "higher is worse" ones low >= central >= high.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import BaseModel

from bcs_gs.ai.providers.base import ProviderRequest
from bcs_gs.ai.roles._common import (
    RoleConfig,
    _repo_root,
    default_role_config,
    dumps,
    load_prompt,
    response_schema,
)
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.api.models import PlanItem
from bcs_gs.core.config import Forecast, load_settings

HIGHER_IS_BETTER = ("g", "h_rec", "survival_rhizophora", "survival_avicennia")
HIGHER_IS_WORSE = (
    "m", "h_dec", "e", "trend", "tau_rhizophora", "tau_avicennia",
    "factor_silt_fence", "factor_reopen_channel", "factor_stop_pollution",
)  # fmt: skip
PARAM_KEYS = (*HIGHER_IS_BETTER, *HIGHER_IS_WORSE)
FACTOR_DEFAULTS = {
    "factor_silt_fence": ("silt_fence", "turbidity"),
    "factor_reopen_channel": ("reopen_channel", "porewater_salinity"),
    "factor_stop_pollution": ("stop_pollution", "do"),
}
EPS = 1e-9


class Band(BaseModel):
    low: float  # pessimistic
    central: float
    high: float  # optimistic


class ZoneStateIn(BaseModel):
    C: float
    H: float
    L: float
    sigma: float


class FpeOutput(BaseModel):
    params: dict[str, Band]  # bounds and ordering enforced by check (-> invalid_output)
    justification: dict[str, str]


@dataclass
class FpeInput:
    zone_id: str
    state: ZoneStateIn | dict[str, float]
    stressors: dict[str, float]
    plan_items: list[PlanItem] = field(default_factory=list)
    water_adjacent: bool = False  # water >= 5 % in the zone or a 4-neighbour (ruling R2)

    def __post_init__(self) -> None:
        if isinstance(self.state, dict):
            self.state = ZoneStateIn(**self.state)


@lru_cache(maxsize=1)
def _forecast_config() -> Forecast:
    return load_settings(_repo_root(), env_file=None).forecast


def bounds(fc: Forecast) -> dict[str, tuple[float, float]]:
    """Allowed [min, max] for every output parameter key (section 19)."""
    b = fc.bounds
    tau = fc.cohorts["time_constant_yr"]
    out: dict[str, tuple[float, float]] = {
        "g": b["g"], "m": b["m"], "h_rec": b["h_rec"], "h_dec": b["h_dec"], "e": b["e"],
        "trend": b["stress_trend"],
        "survival_rhizophora": b["survival"], "survival_avicennia": b["survival"],
        "tau_rhizophora": tuple(tau["plant_rhizophora"]), "tau_avicennia": tuple(tau["plant_avicennia"]),
    }  # fmt: skip
    frac = float(fc.intervention_effects["adjust_fraction"])
    for key, (effect, stressor) in FACTOR_DEFAULTS.items():
        d = float(fc.intervention_effects[effect][stressor])
        out[key] = (d * (1 - frac), d * (1 + frac))
    return out


class ForecastParameterEstimator:
    name = "forecast_parameter_estimator"
    schema_version = "1"
    prompt_version = "v1"
    output_model = FpeOutput

    def __init__(self, cfg: RoleConfig | None = None, forecast: Forecast | None = None) -> None:
        self.cfg = cfg or default_role_config()
        self.fc = forecast or _forecast_config()

    def request(self, inp: FpeInput) -> ProviderRequest:
        body = dumps(
            {
                "zone_id": inp.zone_id,
                "state": inp.state.model_dump() if isinstance(inp.state, BaseModel) else inp.state,
                "stressors": inp.stressors,
                "plan_items": [p.model_dump() for p in inp.plan_items],
                "water_adjacent": inp.water_adjacent,
                "bounds": bounds(self.fc),
            }
        )
        return ProviderRequest(
            role=self.name,
            system=load_prompt(self.name, self.prompt_version),
            parts=[body],
            response_schema=response_schema(FpeOutput),
            temperature=self.cfg.temperature,
            timeout_s=self.cfg.text_timeout_s,
        )

    def check(self, out: FpeOutput, inp: FpeInput) -> FpeOutput:
        allowed = bounds(self.fc)
        if set(out.params) != set(PARAM_KEYS):
            raise OutputRejected(f"params must be exactly {sorted(PARAM_KEYS)}")
        for key in PARAM_KEYS:
            band = out.params[key]
            lo, hi = allowed[key]
            for label, v in (("low", band.low), ("central", band.central), ("high", band.high)):
                if not (lo - EPS <= v <= hi + EPS):
                    raise OutputRejected(f"{key}.{label}={v} outside [{lo:g}, {hi:g}]")
            if key in HIGHER_IS_BETTER:
                ordered = band.low <= band.central + EPS and band.central <= band.high + EPS
            else:
                ordered = band.low >= band.central - EPS and band.central >= band.high - EPS
            if not ordered:
                raise OutputRejected(f"{key} band not ordered pessimistic to optimistic")
        return out

    def rules(self, inp: FpeInput) -> FpeOutput:
        params: dict[str, Band] = {}
        for key in PARAM_KEYS:
            d = self.fc.rules_defaults[key]
            params[key] = Band(low=d["low"], central=d["central"], high=d["high"])
        justification = {k: "Rules-tier default from config/forecast.yaml" for k in PARAM_KEYS}
        if not inp.water_adjacent:
            params["e"] = Band(low=0, central=0, high=0)
            justification["e"] = "No erosion: the zone and its neighbours have under 5% water"
        return FpeOutput(params=params, justification=justification)
