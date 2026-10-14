"""M5 Task 2: carbon core and the pure forecast engine."""

from __future__ import annotations

import dataclasses

import pytest
from bcs_gs.api.models import ExpectedUplift, Intervention, PlanItem, PlanVersion
from bcs_gs.carbon.core import cohort_sequestration_tco2e, stock_tco2e
from bcs_gs.core.config import load_settings
from bcs_gs.forecast.cohorts import cohort_fraction
from bcs_gs.forecast.dynamics import sigma_reduction, step_year
from bcs_gs.forecast.engine import run_forecast
from bcs_gs.forecast.state import ParamSet, ZoneState, initial_state

SETTINGS = load_settings(__import__("pathlib").Path(__file__).resolve().parents[4], env_file=None)
CARBON = SETTINGS.carbon
DEFAULTS = SETTINGS.forecast.rules_defaults
PARAMS = {z: {k: dict(v) for k, v in DEFAULTS.items()} for z in ("KSL-B3", "KSL-B4")}
STRESSORS = {"turbidity": 0.8, "porewater_salinity": 0.4, "do": 0.3, "ph": 0.1, "vegetation": 0.5}
WEIGHTS = {"turbidity": 0.2, "porewater_salinity": 0.2, "do": 0.2, "ph": 0.1, "vegetation": 0.3}
STATES = {
    "KSL-B3": ZoneState(
        C=0.4, H=0.7, L=0.9, sigma=0.5, stressors=STRESSORS, weights=WEIGHTS, water_adjacent=True
    ),
    "KSL-B4": ZoneState(C=0.5, H=0.8, L=0.95, sigma=0.3, stressors=STRESSORS, weights=WEIGHTS),
}
STATES_FULL_CANOPY = {
    "KSL-B3": ZoneState(C=0.85, H=0.9, L=0.9, sigma=0.1, stressors=STRESSORS, weights=WEIGHTS)
}


def central(**over: float) -> ParamSet:
    return dataclasses.replace(ParamSet.from_bands(DEFAULTS, "central"), **over)


def _plan(*interventions: Intervention) -> PlanVersion:
    item = PlanItem(
        zone_id="KSL-B3",
        interventions=list(interventions),
        priority=1,
        rationale="t",
        expected_uplift=ExpectedUplift(canopy_pp_2035=0, tco2e_2035=0),
    )
    return PlanVersion(
        id="pv",
        plan_id="p",
        version=1,
        created_at="2026-10-12T00:00:00Z",
        source="operator",
        status="draft",
        items=[item],
    )


PLAN_SILT_FENCE_B3 = _plan(Intervention(kind="silt_fence"))
PLAN_PLANT_B3 = _plan(Intervention(kind="plant_rhizophora", planted_area_ha=0.5))


def test_bounds_respected_and_decline_under_stress():
    s = ZoneState(C=0.6, H=0.9, L=0.9, sigma=0.7, stressors={}, weights={})
    nxt = step_year(s, central(m=0.4, g=0.0, trend=0.0), 0.0, water_adjacent=False)
    assert nxt.C < s.C and 0 <= nxt.C <= nxt.L


def test_erosion_only_when_adjacent_to_water():
    s = ZoneState(C=0.2, H=1, L=0.9, sigma=0, stressors={}, weights={})
    assert step_year(s, central(e=0.05), 0, water_adjacent=True).L == pytest.approx(0.9 - 0.05 * 0.8)
    assert step_year(s, central(e=0.05), 0, water_adjacent=False).L == 0.9


def test_with_scenario_not_worse_than_without_when_interventions_reduce_stress():
    r = run_forecast(STATES, PARAMS, PLAN_SILT_FENCE_B3, CARBON)
    for y in range(10):
        w, wo = r.scenarios["with"].zones["KSL-B3"][y], r.scenarios["without"].zones["KSL-B3"][y]
        assert w.canopy.central >= wo.canopy.central and w.stock_tco2e.central >= wo.stock_tco2e.central


def test_cohort_growth_is_logistic_and_capped_at_land():
    assert cohort_fraction(0, 6) == 0 and cohort_fraction(3, 6) == pytest.approx(0.5, abs=0.02)
    assert cohort_fraction(30, 6) == pytest.approx(1, abs=1e-3)
    r = run_forecast(STATES_FULL_CANOPY, PARAMS, PLAN_PLANT_B3, CARBON)
    assert (
        max(p.canopy.high for p in r.scenarios["with"].zones["KSL-B3"])
        <= STATES_FULL_CANOPY["KSL-B3"].L + 1e-9
    )


def test_bands_ordered_low_le_central_le_high():
    r = run_forecast(STATES, PARAMS, PLAN_PLANT_B3, CARBON)
    for p in r.scenarios["with"].site:
        assert p.canopy.low <= p.canopy.central <= p.canopy.high


def test_deterministic():
    assert run_forecast(STATES, PARAMS, PLAN_PLANT_B3, CARBON) == run_forecast(
        STATES, PARAMS, PLAN_PLANT_B3, CARBON
    )


def test_stock_conversion():
    assert stock_tco2e(0.5, 1.0, 1074) == pytest.approx(0.5 * 1074 * 44 / 12)


def test_sigma_reduction_applies_once():
    """R4: the plan lowers sigma in the first step only; later years follow the trend in both scenarios."""
    p = {z: {**{k: dict(v) for k, v in DEFAULTS.items()}} for z in STATES}
    for z in p:
        for k in ("low", "central", "high"):
            p[z]["trend"][k] = 0.02
    r = run_forecast(STATES, p, PLAN_SILT_FENCE_B3, CARBON)
    w = [pt.sigma.central for pt in r.scenarios["with"].zones["KSL-B3"]]
    wo = [pt.sigma.central for pt in r.scenarios["without"].zones["KSL-B3"]]
    red = sigma_reduction(STRESSORS, WEIGHTS, [Intervention(kind="silt_fence")], {"factor_silt_fence": 0.4})
    assert red == pytest.approx(0.2 * 0.8 * 0.6)
    gap = [b - a for a, b in zip(w, wo, strict=True)]
    assert gap[0] == pytest.approx(0.0) and gap[1] == pytest.approx(red) and gap[5] == pytest.approx(red)


def test_sigma_reduction_multiplies_factors_on_shared_stressor():
    ivs = [Intervention(kind="reopen_channel"), Intervention(kind="stop_pollution")]
    f = {"factor_reopen_channel": 0.5, "factor_stop_pollution": 0.3}
    got = sigma_reduction({"do": 1.0}, {"do": 1.0}, ivs, f)
    assert got == pytest.approx(1 - 0.5 * 0.3)


def test_without_scenario_has_no_additional_carbon_and_year_points_carry_extras():
    r = run_forecast(STATES, PARAMS, PLAN_PLANT_B3, CARBON)
    assert all(p.additional_tco2e.central == 0 for p in r.scenarios["without"].zones["KSL-B3"])
    w = r.scenarios["with"].zones["KSL-B3"]
    assert w[0].year == 2026 and w[-1].year == 2035 and len(w) == 10
    assert w[0].cohort_fraction == 0 and w[-1].cohort_fraction > 0.9
    assert w[-1].additional_tco2e.central > 0 and w[-1].seq_tco2e.central > 0


def test_cohort_sequestration_uses_age_rates():
    rates = CARBON.cohort_rates.value
    assert cohort_sequestration_tco2e(0, 1.0, 0.5, rates) == pytest.approx(2.0 * 0.5 * 44 / 12)
    assert cohort_sequestration_tco2e(5, 1.0, 1.0, rates) == pytest.approx(4.0 * 44 / 12)


def test_initial_state_mapping():
    from types import SimpleNamespace as NS

    m = NS(canopy_pct=40, water_pct=10, dieback_pct=20, vari_mean=0.3)
    a = NS(stressors={"do": 0.5, "ph": None}, weights={"do": 1.0}, risk_score=55)
    s = initial_state(m, 0.6, a)
    assert (s.C, s.L, s.sigma) == (pytest.approx(0.4), pytest.approx(0.9), pytest.approx(0.55))
    assert s.H == pytest.approx(0.5 * 0.8) and s.stressors == {"do": 0.5}
    s0 = initial_state(m, None, None)
    assert s0.H == pytest.approx(0.8) and s0.sigma == 0 and s0.stressors == {}


# ---- ruling R27: the parameter cache key quantises the zone state ---------------------------------------
def _key(C=0.50, H=0.80, L=0.90, sigma=0.30, stressors=None, items=()):
    from types import SimpleNamespace

    from bcs_gs.forecast.service import cache_key

    role = SimpleNamespace(name="forecast_parameter_estimator", schema_version="1", prompt_version="v1")
    st = ZoneState(C=C, H=H, L=L, sigma=sigma, stressors=stressors or {"do": 0.40, "turbidity": 0.20})
    return cache_key(st, list(items), role)


def test_cache_key_shares_within_half_a_step():
    base = _key()
    # C, H, L step 0.02 (half 0.01); sigma and stressors step 0.05 (half 0.025): all moved by less than half
    assert _key(C=0.509, H=0.791, L=0.9099, sigma=0.324, stressors={"do": 0.424, "turbidity": 0.176}) == base
    assert _key(C=0.5 + 1e-12) == base  # float noise never changes the key


def test_cache_key_differs_a_full_step_apart():
    base = _key()
    assert _key(C=0.52) != base and _key(H=0.78) != base and _key(L=0.92) != base
    assert _key(sigma=0.35) != base
    assert _key(stressors={"do": 0.45, "turbidity": 0.20}) != base
    assert _key(stressors={"do": 0.40, "turbidity": 0.15}) != base


def test_cache_key_is_deterministic_and_keys_plan_items():
    from bcs_gs.api.models import ExpectedUplift, Intervention, PlanItem
    from bcs_gs.forecast.service import quantise

    assert (
        quantise(0.3, 0.02) == "0.30"
        and quantise(0.1 + 0.2, 0.05) == "0.30"
        and quantise(-0.004, 0.02) == "0.00"
    )
    assert quantise(0.0249, 0.05) == "0.00" and quantise(0.0251, 0.05) == "0.05"
    assert _key() == _key()
    item = PlanItem(
        zone_id="KSL-B3", interventions=[Intervention(kind="silt_fence")], priority=1, rationale="t",
        expected_uplift=ExpectedUplift(canopy_pp_2035=0.0, tco2e_2035=0.0),
    )  # fmt: skip
    assert _key(items=[item]) != _key()
