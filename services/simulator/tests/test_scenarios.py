import math
from datetime import UTC, datetime, timedelta

import pytest
from bcs_sim.clock import ManualClock
from bcs_sim.overrides import Overrides
from bcs_sim.scenarios import SCENARIOS, ScenarioBook, grid_zone_bounds, reach_factor

T0 = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)  # 12:00 MYT (day)
ZB = {
    f"{c}{r}": (i * 100, (r - 1) * 100, (i + 1) * 100, r * 100)
    for i, c in enumerate("ABCDE")
    for r in range(1, 6)
}


def sample_points_within(radius, of_centre):
    ce, cs = of_centre
    pts = [(ce, cs)]
    for k in range(16):
        a = 2 * math.pi * k / 16
        for r in (radius / 2, radius):
            pts.append((ce + r * math.cos(a), cs + r * math.sin(a)))
    return pts


def test_reach_inside_and_attenuated_outside():
    b3 = (100, 200, 200, 300)
    assert reach_factor("water_quality", 150, 250, b3) == 1
    assert reach_factor("water_quality", 250, 250, b3) == pytest.approx(1 - 50 / 150)
    assert reach_factor("soil_probe", 250, 250, b3) == pytest.approx(0.5)


def test_any_covering_node_gets_at_least_a_third():
    b3 = (100, 200, 200, 300)
    for e, s in sample_points_within(150, of_centre=(150, 250)):
        assert reach_factor("water_quality", e, s, b3) >= 1 / 3 - 1e-9
    for e, s in sample_points_within(100, of_centre=(150, 250)):
        assert reach_factor("soil_probe", e, s, b3) >= 0.5 - 1e-9


def test_ramp_reaches_63_percent_after_one_tau():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "sediment_runoff", ramp_s=60)
    clock.advance(60)
    off = book.offsets_for("water_quality", 150, 250, clock.now(), ZB)
    assert off["turbidity_ntu"] == pytest.approx(150 * (1 - math.e**-1), rel=0.01)


def test_recovery_decays_to_zero():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "sediment_runoff", 1)
    clock.advance(600)
    book.apply("B3", "recovery", None)
    clock.advance(1200)
    assert abs(book.offsets_for("water_quality", 150, 250, clock.now(), ZB)["turbidity_ntu"]) < 1


def test_recovery_starts_from_current_magnitude():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "sediment_runoff", 60)
    clock.advance(60)
    cur = book.offsets_for("water_quality", 150, 250, clock.now(), ZB)["turbidity_ntu"]
    book.apply("B3", "recovery", None)
    assert book.offsets_for("water_quality", 150, 250, clock.now(), ZB)["turbidity_ntu"] == pytest.approx(cur)
    clock.advance(120)
    assert book.offsets_for("water_quality", 150, 250, clock.now(), ZB)["turbidity_ntu"] == pytest.approx(
        cur / math.e
    )


def test_healthy_clears_immediately():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "heavy_rain", 1)
    clock.advance(100)
    book.apply("B3", "healthy", None)
    assert book.active() == {}
    assert book.offsets_for("tide_gauge", 0, 0, clock.now(), ZB) == {}


def test_scenario_far_from_every_node_has_no_effect():  # Review Focus 3
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("E5", "sediment_runoff", 1)
    clock.advance(600)
    assert book.offsets_for("water_quality", 50, 50, clock.now(), ZB) == {}


def test_salt_intrusion_porewater_uses_180s_tau():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "salt_intrusion", 60)
    clock.advance(180)
    off = book.offsets_for("soil_probe", 150, 250, clock.now(), ZB)
    assert off["porewater_salinity_psu"] == pytest.approx(20 * (1 - math.e**-1), rel=0.01)
    assert off["soil_moisture_pct"] == pytest.approx(-15 * (1 - math.e**-3), rel=0.01)
    assert "salinity_psu" not in off  # water-quality key, not reported by a soil probe


def test_node_types_only_get_their_own_keys_and_attenuation_applies():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "heavy_rain", 1)
    clock.advance(600)
    tg = book.offsets_for("tide_gauge", 450, 450, clock.now(), ZB)
    assert set(tg) == {"water_level_cm"} and 0 < tg["water_level_cm"] < 40
    sp = book.offsets_for("soil_probe", 250, 250, clock.now(), ZB)
    assert sp["soil_moisture_pct"] == pytest.approx(15 * 0.5, rel=0.01)


def test_offsets_from_several_zones_add_up():
    book = ScenarioBook(clock := ManualClock(T0))
    book.apply("B3", "sediment_runoff", 1)
    book.apply("C3", "sediment_runoff", 1)
    clock.advance(600)
    off = book.offsets_for("water_quality", 200, 250, clock.now(), ZB)
    assert off["turbidity_ntu"] == pytest.approx(300, rel=0.01)


def test_low_oxygen_fraction_target_day_night_and_blend():
    day, night = T0, T0 + timedelta(hours=12)  # 12:00 / 00:00 MYT
    for at, target, has_ph in ((day, 0.6, False), (night, 0.3, True)):
        book = ScenarioBook(clock := ManualClock(at))
        book.apply("B3", "low_oxygen", 1)
        clock.advance(600)
        off = book.offsets_for("water_quality", 150, 250, clock.now(), ZB)
        assert off.fraction_target == target
        assert off.fraction_strength == pytest.approx(1, abs=1e-6)
        assert off.blend_fraction(0.9) == pytest.approx(target, abs=1e-6)
        assert ("ph" in off) is has_ph
        assert off["turbidity_ntu"] == pytest.approx(20, rel=0.01)
    far = book.offsets_for("water_quality", 450, 450, clock.now(), ZB)
    assert far == {} and far.fraction_target is None and far.blend_fraction(0.9) == 0.9


def test_grid_zone_bounds():
    g = grid_zone_bounds()
    assert g["B3"] == (100, 200, 200, 300) and g["E5"] == (400, 400, 500, 500) and len(g) == 25


def test_default_offsets_verbatim():
    assert SCENARIOS["heat_stress"].offsets == {"temp_c": 4, "porewater_salinity_psu": 5}
    assert SCENARIOS["heavy_rain"].offsets["water_level_cm"] == 40


def test_hold_and_drift_overrides():
    o = Overrides(ManualClock(T0))
    o.set("WQ-01", "do_mg_l", 2.0, "hold")
    assert o.apply("WQ-01", {"do_mg_l": 6.5}, T0 + timedelta(minutes=5))["do_mg_l"] == 2.0
    o.set("WQ-01", "do_mg_l", 2.0, "drift")
    assert o.apply("WQ-01", {"do_mg_l": 6.5}, T0 + timedelta(seconds=60))["do_mg_l"] == pytest.approx(
        6.5 - 4.5 * math.e**-1, abs=0.01
    )
    assert o.apply("WQ-02", {"do_mg_l": 6.5}, T0)["do_mg_l"] == 6.5
    o.clear("WQ-01", "do_mg_l")
    assert o.apply("WQ-01", {"do_mg_l": 6.5}, T0)["do_mg_l"] == 6.5
