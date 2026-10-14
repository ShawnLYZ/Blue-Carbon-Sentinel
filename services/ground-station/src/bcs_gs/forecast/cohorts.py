"""Planted cohorts: normalised logistic canopy growth (pure)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from bcs_gs.forecast.state import ParamSet

DEFAULT_DENSITY_PER_HA = 4400
ZONE_AREA_HA = 1.0


def _logistic(t: float, tau: float) -> float:
    return 1.0 / (1.0 + math.exp(-(8.0 / tau) * (t - tau / 2.0)))


def cohort_fraction(t_years: float, tau: float) -> float:
    """Logistic with midpoint tau/2 and steepness 8/tau, rescaled so f(0)=0 and f(inf)=1."""
    lo = _logistic(0.0, tau)
    return (_logistic(t_years, tau) - lo) / (1.0 - lo)


@dataclass(frozen=True)
class Cohort:
    species: str  # rhizophora | avicennia
    area_ha: float
    survival: float
    tau: float


def build_cohorts(
    interventions: Iterable[Any], params: ParamSet, density_per_ha: int = DEFAULT_DENSITY_PER_HA
) -> list[Cohort]:
    out = []
    for iv in interventions:
        if iv.kind not in ("plant_rhizophora", "plant_avicennia"):
            continue
        sp = iv.kind.removeprefix("plant_")
        if iv.planted_area_ha is not None:
            area = iv.planted_area_ha
        elif iv.sapling_count is not None:
            area = iv.sapling_count / density_per_ha
        else:
            area = ZONE_AREA_HA
        area = min(max(area, 0.0), ZONE_AREA_HA)
        out.append(Cohort(sp, area, getattr(params, f"survival_{sp}"), getattr(params, f"tau_{sp}")))
    return out
