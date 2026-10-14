"""M6 Task 1: cited carbon constants, plan additionality and deductions."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from bcs_gs.api.models import ExpectedUplift, Intervention, PlanItem, PlanVersion
from bcs_gs.carbon.engine import CFG, deductions, plan_additionality, site_stock, summary, zone_stock
from bcs_gs.forecast.engine import run_forecast
from bcs_gs.forecast.state import ZoneState

ROOT = Path(__file__).resolve().parents[4]
STRESSORS = {"turbidity": 0.8, "porewater_salinity": 0.4, "do": 0.3, "ph": 0.1, "vegetation": 0.5}
WEIGHTS = {"turbidity": 0.2, "porewater_salinity": 0.2, "do": 0.2, "ph": 0.1, "vegetation": 0.3}
STATES = {
    "KSL-B3": ZoneState(C=0.4, H=0.7, L=0.9, sigma=0.5, stressors=STRESSORS, weights=WEIGHTS, water_adjacent=True),
    "KSL-B4": ZoneState(C=0.5, H=0.8, L=0.95, sigma=0.3, stressors=STRESSORS, weights=WEIGHTS),
}


def _plan(*extra: str) -> PlanVersion:
    item = PlanItem(
        zone_id="KSL-B3",
        interventions=[Intervention(kind="plant_rhizophora", planted_area_ha=0.5), *(Intervention(kind=k) for k in extra)],
        priority=1,
        rationale="t",
        expected_uplift=ExpectedUplift(canopy_pp_2035=0, tco2e_2035=0),
    )
    return PlanVersion(
        id="pv", plan_id="p", version=1, created_at="2026-10-12T00:00:00Z", source="operator",
        status="draft", items=[item],
    )  # fmt: skip


def _forecast(soil_density_factor: float = 1.0, *extra: str):
    from bcs_gs.core.config import load_settings

    s = load_settings(ROOT, env_file=None)
    params = {z: {k: dict(v) for k, v in s.forecast.rules_defaults.items()} for z in STATES}
    eco = s.carbon.ecosystem_density_mg_c_ha  # the whole-ecosystem (soil included) density
    carbon = s.carbon.model_copy(
        update={"ecosystem_density_mg_c_ha": eco.model_copy(update={"value": eco.value * soil_density_factor})}
    )
    return run_forecast(STATES, params, _plan(*extra), carbon)


FORECAST_WITH_PLANT_B3 = _forecast()


def test_deductions_buffer_then_uncertainty():
    d = deductions(Decimal("100.000"), Decimal("0.8500"))
    assert d.buffer_tco2e == Decimal("15.000") and d.uncertainty_fraction == Decimal("0.0500")
    assert d.uncertainty_tco2e == Decimal("4.250") and d.net_tco2e == Decimal("80.750")


def test_uncertainty_clamped_between_zero_and_half():
    assert deductions(Decimal(10), Decimal("0.95")).uncertainty_fraction == Decimal("0.0000")
    assert deductions(Decimal(10), Decimal("0.20")).uncertainty_fraction == Decimal("0.5000")


def test_deductions_use_config_buffer_by_default_and_round_half_even():
    assert CFG.buffer_pct.value == 15
    d = deductions(Decimal("0.005"), Decimal(1))  # buffer 0.00075, net 0.00425 -> 0.004
    assert d.buffer_tco2e == Decimal("0.001") and d.net_tco2e == Decimal("0.004")


def test_stock_uses_cited_density():
    assert zone_stock(0.5) == pytest.approx(0.5 * CFG.ecosystem_density_mg_c_ha.value * 44 / 12)
    assert site_stock([0.5, 0.25]) == pytest.approx(0.75 * CFG.ecosystem_density_mg_c_ha.value * 44 / 12)


def test_additionality_excludes_soil_and_matches_forecast():
    add = plan_additionality(FORECAST_WITH_PLANT_B3, ["KSL-B3"])
    point = FORECAST_WITH_PLANT_B3.zone("with", "KSL-B3", 2035)
    assert add["KSL-B3"] == Decimal(str(round(point.additional_tco2e.central, 3)))
    assert add["KSL-B3"] > 0


def test_additionality_does_not_depend_on_the_soil_inclusive_ecosystem_density():
    """Soil carbon is in the standing stock only: scaling the ecosystem density 10x moves the stock but
    must leave additionality untouched. The silt fence makes the avoided-loss term non-zero, so a leak of
    soil carbon into it (ecosystem instead of biomass density) would change the result."""
    base_fc, scaled_fc = _forecast(1.0, "silt_fence"), _forecast(10.0, "silt_fence")
    base = plan_additionality(base_fc, ["KSL-B3", "KSL-B4"])
    assert base["KSL-B3"] > plan_additionality(FORECAST_WITH_PLANT_B3, ["KSL-B3"])["KSL-B3"]  # avoided term live
    assert plan_additionality(scaled_fc, ["KSL-B3", "KSL-B4"]) == base
    stock = lambda f: f.zone("with", "KSL-B3", 2035).stock_tco2e.central
    assert stock(scaled_fc) == pytest.approx(10 * stock(base_fc))  # the knob is live


def test_additionality_is_far_below_standing_stock():
    """Stock is a standing ecosystem stock; additionality is extra sequestration over 2026-2035 (R6)."""
    add = plan_additionality(FORECAST_WITH_PLANT_B3, ["KSL-B3"])["KSL-B3"]
    assert float(add) < zone_stock(0.4) / 10


def test_summary_sums_ledger_records(tmp_path):

    import json

    contents = [  # totals read the canonical content (never the display columns)
        {"type": "projected", "quantity_tco2e": "9.000", "evidence": {"plan_id": "P1"}},
        {"type": "projected", "quantity_tco2e": "12.500", "evidence": {"plan_id": "P1"}},
        {"type": "projected", "quantity_tco2e": "1.000", "evidence": {"plan_id": "P2"}},
        {"type": "verified", "quantity_tco2e": "3.250", "zone_ids": ["KSL-B3"], "evidence": {"plan_id": "P1"}},
        {"type": "verified", "quantity_tco2e": "1.000", "zone_ids": ["KSL-B4"], "evidence": {"plan_id": "P1"}},
        # a second Verified for (P1, KSL-B3), e.g. after a re-apply: never counted twice (ruling)
        {"type": "verified", "quantity_tco2e": "7.000", "zone_ids": ["KSL-B3"], "evidence": {"plan_id": "P1"}},
    ]

    class _Repo:
        def query(self, sql, params=(), *, table=None):
            return [{"chain_index": i, "canonical": json.dumps(c).encode()} for i, c in enumerate(contents)]

    s = summary(_Repo(), {"KSL-B3": 0.4, "KSL-B4": 0.2})
    assert s.projected_tco2e == pytest.approx(13.5) and s.verified_tco2e == pytest.approx(4.25)
    assert set(s.per_zone) == {"KSL-B3", "KSL-B4"}
    assert s.stock_tco2e == pytest.approx(sum(s.per_zone.values()))
    assert {c.name for c in s.constants} >= {"ecosystem_density_mg_c_ha", "buffer_pct"}
    assert all(c.citation for c in s.constants)
