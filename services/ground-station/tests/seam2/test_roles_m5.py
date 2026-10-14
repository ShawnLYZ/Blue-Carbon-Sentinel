"""M5 Task 1: ForecastParameterEstimator and RestorationPlanner roles (checks, rules tiers, prompts)."""

from __future__ import annotations

import pytest
from bcs_gs.ai.roles import PROMPTS
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.ai.roles.forecast_parameter_estimator import (
    ForecastParameterEstimator as FPE,
)
from bcs_gs.ai.roles.forecast_parameter_estimator import FpeInput
from bcs_gs.ai.roles.restoration_planner import (
    PlannerInput,
    PlannerOutput,
    PlannerZone,
)
from bcs_gs.ai.roles.restoration_planner import RestorationPlanner as RP
from bcs_gs.api.models import ExpectedUplift, Intervention, PlanItem


def fin(**kw) -> FpeInput:
    base = {
        "zone_id": "KSL-B3",
        "state": {"C": 0.5, "H": 0.7, "L": 0.1, "sigma": 0.3},
        "stressors": {"turbidity": 0.4},
        "plan_items": [],
        "water_adjacent": True,
    }
    return FpeInput(**{**base, **kw})


FIN = fin()


def params(**override):
    out = FPE().rules(FIN)
    p = {k: v.model_dump() for k, v in out.params.items()}
    p.update(override)
    return type(out)(params=p, justification=out.justification)


def zone(zone_id="KSL-B3", risk="high", top="turbidity", mud=0.3, porewater=45.0, covered=True) -> PlannerZone:
    return PlannerZone(
        zone_id=zone_id,
        risk_class=risk,
        stressors={top: 0.8, "ph": 0.1},
        class_fractions={"canopy": 0.4, "water": 0.2, "mud": mud, "other": 0.1},
        porewater_psu=porewater,
        covered=covered,
    )


def rin(zones) -> PlannerInput:
    return PlannerInput(zones=zones)


def test_estimator_rejects_out_of_bounds_and_unordered():
    with pytest.raises(OutputRejected):
        FPE().check(params(g={"low": 0.1, "central": 0.05, "high": 0.2}), FIN)
    with pytest.raises(OutputRejected):
        FPE().check(params(m={"low": 0.1, "central": 0.2, "high": 0.5}), FIN)


def test_estimator_rejects_factor_outside_half_of_default():
    with pytest.raises(OutputRejected):
        FPE().check(params(factor_silt_fence={"low": 0.7, "central": 0.4, "high": 0.2}), FIN)


def test_estimator_rejects_tau_outside_species_range():
    with pytest.raises(OutputRejected):
        FPE().check(params(tau_avicennia={"low": 6.5, "central": 5, "high": 4}), FIN)


def test_estimator_rules_zero_erosion_away_from_water():
    assert FPE().rules(fin(water_adjacent=False)).params["e"].model_dump() == {"low": 0, "central": 0, "high": 0}


def test_estimator_rules_pass_own_check_and_match_table():
    for adj in (True, False):
        i = fin(water_adjacent=adj)
        out = FPE().check(FPE().rules(i), i)
        assert set(out.justification) == set(out.params)
    p = FPE().rules(FIN).params
    assert (p["g"].central, p["g"].low, p["g"].high) == (0.06, 0.03, 0.09)
    assert (p["tau_rhizophora"].central, p["tau_rhizophora"].low, p["tau_rhizophora"].high) == (6, 7, 5)


def test_estimator_request_carries_prompt_and_schema():
    req = FPE().request(FIN)
    assert req.role == "forecast_parameter_estimator" and "KSL-B3" in req.parts[0]
    assert (PROMPTS / "forecast_parameter_estimator.v1.md").exists()


def test_planner_rules_follow_section_20():
    out = RP().rules(rin([zone("KSL-B3", "high", top="turbidity", mud=0.3, porewater=45)]))
    kinds = {i.kind for i in out.items[0].interventions}
    assert kinds == {"plant_avicennia", "silt_fence"} and out.items[0].interventions[0].sapling_count == 1320


def test_planner_rules_species_channel_and_skips():
    out = RP().rules(
        rin(
            [
                zone("KSL-A1", "critical", top="porewater_salinity", mud=0.8, porewater=20),
                zone("KSL-A2", "low", top="do"),
                zone("KSL-A3", "high", top="do", mud=0.0),
            ]
        )
    )
    by = {it.zone_id: it for it in out.items}
    a1 = by["KSL-A1"].interventions
    assert [i.kind for i in a1] == ["plant_rhizophora", "reopen_channel"]
    assert a1[0].planted_area_ha == 0.5 and a1[0].sapling_count == 2200
    assert "KSL-A2" not in by
    assert [i.kind for i in by["KSL-A3"].interventions] == ["reopen_channel"]


def test_planner_rules_pass_own_check():
    i = rin([zone("KSL-B3"), zone("KSL-B4", "critical", top="do", mud=0.9, porewater=10)])
    RP().check(RP().rules(i), i)


def item(zone_id="KSL-B3", priority=1, **iv) -> PlanItem:
    return PlanItem(
        zone_id=zone_id,
        interventions=[Intervention(**iv)],
        priority=priority,
        rationale="x",
        expected_uplift=ExpectedUplift(canopy_pp_2035=0, tco2e_2035=0),
    )


def test_planner_check_rejects_bad_items():
    i = rin([zone("KSL-B3")])
    bad = [
        item("NOPE", kind="silt_fence"),
        item(kind="plant_avicennia", planted_area_ha=0.1, sapling_count=441),
        item(kind="plant_avicennia", sapling_count=-1, planted_area_ha=0.1),
    ]
    for b in bad:
        with pytest.raises(OutputRejected):
            RP().check(PlannerOutput(items=[b]), i)
    ok = item(kind="plant_avicennia", planted_area_ha=0.1, sapling_count=440)
    assert RP().check(PlannerOutput(items=[ok]), i).items == [ok]
