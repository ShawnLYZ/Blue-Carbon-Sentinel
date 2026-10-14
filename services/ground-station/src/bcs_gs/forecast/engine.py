"""Deterministic forecast engine: 2026-2035, without / with a plan, low / central / high runs (pure)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bcs_gs.carbon.core import C_TO_CO2E, cohort_sequestration_tco2e, stock_tco2e
from bcs_gs.forecast.cohorts import ZONE_AREA_HA, build_cohorts, cohort_fraction
from bcs_gs.forecast.dynamics import sigma_reduction, step_year
from bcs_gs.forecast.state import Band, ParamBands, ParamSet, ZoneState
from bcs_gs.fusion.risk import risk_class

START_YEAR = 2026
N_YEARS = 10
RUNS = ("low", "central", "high")


@dataclass(frozen=True)
class YearPoint:
    year: int
    canopy: Band
    health: Band
    land: Band
    risk_class: str
    stock_tco2e: Band
    seq_tco2e: Band
    additional_tco2e: Band
    sigma: Band  # ruling R6
    cohort_fraction: float  # central run, max over the zone's cohorts (ruling R6)


@dataclass(frozen=True)
class ScenarioSeries:
    site: list[YearPoint] = field(default_factory=list)
    zones: dict[str, list[YearPoint]] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastResult:
    years: list[int]
    scenarios: dict[str, ScenarioSeries]

    def zone(self, scenario: str, zone: str, year: int) -> YearPoint:
        """The zone's point for a calendar year (KeyError for an unknown scenario, zone or year)."""
        return self.scenarios[scenario].zones[zone][self.years.index(year)]


def _interventions(plan: Any, zone: str) -> list[Any]:
    if plan is None:
        return []
    return [iv for item in plan.items if item.zone_id == zone for iv in item.interventions]


def _trajectory(state: ZoneState, params: ParamSet, reduction: float) -> list[ZoneState]:
    """Natural dynamics for 10 yearly states; ``reduction`` lowers sigma once, in the first step (ruling R4)."""
    out = [state]
    for t in range(N_YEARS - 1):
        out.append(step_year(out[-1], params, reduction if t == 0 else 0.0, state.water_adjacent))
    return out


def _zone_run(
    state: ZoneState, params: ParamSet, ivs: list[Any], carbon_cfg: Any
) -> dict[str, list[dict[str, float]]]:
    """One run of one zone: per-year raw values for both scenarios."""
    rates = carbon_cfg.cohort_rates.value
    density = carbon_cfg.ecosystem_density_mg_c_ha.value
    biomass = carbon_cfg.biomass_density_mg_c_ha.value
    area = ZONE_AREA_HA
    red = sigma_reduction(state.stressors, state.weights, ivs, params.factors())
    cohorts = build_cohorts(ivs, params)
    without = _trajectory(state, params, 0.0)
    nat_with = _trajectory(state, params, red)

    def point(s: ZoneState, c: float, seq: float, add: float, frac: float) -> dict[str, float]:
        return {
            "canopy": c, "health": s.H, "land": s.L, "sigma": s.sigma, "stock": stock_tco2e(c, area, density),
            "seq": seq, "add": add, "frac": frac,
        }  # fmt: skip

    wo = [point(s, s.C, 0.0, 0.0, 0.0) for s in without]
    wi: list[dict[str, float]] = []
    cum_seq = 0.0
    for t, s in enumerate(nat_with):
        cs = sum(c.area_ha / area * c.survival * cohort_fraction(t, c.tau) for c in cohorts)
        canopy = min(s.L, s.C + cs)
        seq = (
            sum(cohort_sequestration_tco2e(t - 1, c.area_ha, c.survival, rates) for c in cohorts)
            if t > 0
            else 0.0
        )
        cum_seq += seq
        avoided = max(0.0, (s.C - without[t].C) * biomass * C_TO_CO2E * area)
        frac = max((cohort_fraction(t, c.tau) for c in cohorts), default=0.0)
        wi.append(point(s, canopy, seq, cum_seq + avoided, frac))
    return {"without": wo, "with": wi}


def _band(vals: list[float]) -> Band:
    return Band(low=min(vals), central=vals[1], high=max(vals))


def _year_point(t: int, runs: list[dict[str, float]]) -> YearPoint:
    b = {k: _band([r[k] for r in runs]) for k in ("canopy", "health", "land", "sigma", "stock", "seq", "add")}
    return YearPoint(
        year=START_YEAR + t,
        canopy=b["canopy"],
        health=b["health"],
        land=b["land"],
        risk_class=risk_class(runs[1]["sigma"] * 100),
        stock_tco2e=b["stock"],
        seq_tco2e=b["seq"],
        additional_tco2e=b["add"],
        sigma=b["sigma"],
        cohort_fraction=runs[1]["frac"],
    )


def _site(zone_runs: list[list[list[dict[str, float]]]]) -> list[YearPoint]:
    """Site points from per-zone [run][year] raw values: sums for carbon, means for C/H/L/sigma."""
    n = len(zone_runs)
    out = []
    for t in range(N_YEARS):
        runs = []
        for r in range(3):
            pts = [z[r][t] for z in zone_runs]
            agg = {k: sum(p[k] for p in pts) for k in ("stock", "seq", "add")}
            agg.update({k: sum(p[k] for p in pts) / n for k in ("canopy", "health", "land", "sigma")})
            agg["frac"] = max(p["frac"] for p in pts)
            runs.append(agg)
        out.append(_year_point(t, runs))
    return out


def run_forecast(
    states: dict[str, ZoneState], params: dict[str, ParamBands], plan: Any | None, carbon_cfg: Any
) -> ForecastResult:
    scenarios: dict[str, ScenarioSeries] = {}
    raw: dict[str, dict[str, list[list[dict[str, float]]]]] = {"without": {}, "with": {}}
    for zone in sorted(states):
        ivs = _interventions(plan, zone)
        runs = [_zone_run(states[zone], ParamSet.from_bands(params[zone], w), ivs, carbon_cfg) for w in RUNS]
        for sc, by_zone in raw.items():
            by_zone[zone] = [r[sc] for r in runs]
    for sc, by_zone in raw.items():
        zones = {z: [_year_point(t, [r[t] for r in zr]) for t in range(N_YEARS)] for z, zr in by_zone.items()}
        site = _site(list(by_zone.values())) if by_zone else []
        scenarios[sc] = ScenarioSeries(site=site, zones=zones)
    return ForecastResult(years=[START_YEAR + t for t in range(N_YEARS)], scenarios=scenarios)
