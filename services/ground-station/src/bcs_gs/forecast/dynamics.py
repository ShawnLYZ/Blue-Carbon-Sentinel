"""One-year dynamics of a zone (pure)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from bcs_gs.forecast.state import ParamSet, ZoneState

# intervention -> (factor parameter, affected stressors)
INTERVENTION_EFFECTS = {
    "silt_fence": ("factor_silt_fence", ("turbidity",)),
    "reopen_channel": ("factor_reopen_channel", ("porewater_salinity", "do")),
    "stop_pollution": ("factor_stop_pollution", ("do", "ph")),
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def step_year(state: ZoneState, params: ParamSet, sigma_reduction: float, water_adjacent: bool) -> ZoneState:
    C, H, L, s = state.C, state.H, state.L, state.sigma
    growth = params.g * C * (1 - C / L) * (1 - s) if L > 0 else 0.0
    C2 = C + growth - params.m * s * C
    H2 = _clamp(H + params.h_rec * (1 - s) * (1 - H) - params.h_dec * s * H, 0.0, 1.0)
    L2 = _clamp(L - params.e * (1 - C), 0.0, 1.0) if water_adjacent else L
    C2 = _clamp(C2, 0.0, L2)
    s2 = _clamp(s + params.trend - sigma_reduction, 0.0, 1.0)
    return replace(state, C=C2, H=H2, L=L2, sigma=s2)


def sigma_reduction(
    stressors: dict[str, float],
    weights: dict[str, float],
    interventions: Iterable[Any],
    factors: dict[str, float],
) -> float:
    """sum w_i s_i (1 - factor_i) over the stressors the interventions affect (factors multiply per stressor)."""
    combined: dict[str, float] = {}
    for iv in interventions:
        kind = iv if isinstance(iv, str) else iv.kind
        effect = INTERVENTION_EFFECTS.get(kind)
        if effect is None:
            continue
        key, targets = effect
        for t in targets:
            combined[t] = combined.get(t, 1.0) * float(factors[key])
    total = 0.0
    for name, f in combined.items():
        s, w = stressors.get(name), weights.get(name)
        if s is None or w is None:
            continue
        total += w * s * (1 - f)
    return total
