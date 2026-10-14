"""Fusion maths (addendum N1-N5): breakpoints, vegetation, weights, risk, confidence, early warning."""

from __future__ import annotations

import pytest
from bcs_gs.fusion.bands import BAND_KEY, band_points, sensor_stress, stress_from_breakpoints
from bcs_gs.fusion.confidence import (
    TIER_FACTOR,
    NodeHealthView,
    camera_confidence,
    overall,
    sensor_confidence,
)
from bcs_gs.fusion.early_warning import EarlyWarning
from bcs_gs.fusion.risk import effective_weights, risk
from bcs_gs.fusion.stressors import sensor_composite, vegetation_decline

BASE = {
    "vegetation": 0.35,
    "salinity": 0.10,
    "porewater_salinity": 0.15,
    "turbidity": 0.15,
    "do": 0.15,
    "temperature": 0.05,
    "ph": 0.05,
}


def test_do_and_ph_breakpoints():
    do = [(0.5, 1.0), (2.0, 0.6), (5.0, 0.0)]
    assert stress_from_breakpoints(5.5, do) == 0 and stress_from_breakpoints(2.0, do) == 0.6
    assert stress_from_breakpoints(3.5, do) == pytest.approx(0.3)
    ph = [(6.0, 1.0), (6.5, 0.6), (7.0, 0.0), (8.5, 0.0), (9.0, 0.6), (9.5, 1.0)]
    assert stress_from_breakpoints(7.8, ph) == 0 and stress_from_breakpoints(9.25, ph) == pytest.approx(0.8)


def test_committed_bands_match_the_spec_and_single_mapping():
    assert band_points("do")[0] == (0.5, 1.0)
    assert sensor_stress("turbidity", 100) == pytest.approx(0.6)
    assert sensor_stress("porewater_salinity", 100) == 1.0
    assert set(BAND_KEY) == set(BASE) - {"vegetation"}


def test_vegetation_decline_is_max_of_three_terms():
    assert vegetation_decline(15, 10, 0.03) == pytest.approx(0.5) and vegetation_decline(None, None, None) is None
    assert vegetation_decline(90, None, None) == 1.0 and vegetation_decline(-5, None, None) == 0.0


def test_risk_classes_and_weights_sum():
    w = effective_weights(BASE, {}, set(BASE))
    assert sum(w.values()) == pytest.approx(1)
    assert risk({k: 0.8 for k in BASE}, w) == (pytest.approx(80.0), "critical")
    assert risk({k: 0.2 for k in BASE}, w)[1] == "low"
    assert risk({k: 0.5 for k in BASE}, w)[1] == "medium"
    assert risk({k: 0.7 for k in BASE}, w)[1] == "high"


def test_class_taken_from_unrounded_score():
    w = {"do": 1.0}
    assert risk({"do": 0.7996}, w)[1] == "high"  # displays 80.0 but is below 80


def test_risk_with_no_measured_stressor_raises():
    with pytest.raises(ValueError):
        risk({"do": None}, {"do": 1.0})


def test_renormalisation_without_vegetation():  # Review Focus 4
    w = effective_weights(BASE, {}, set(BASE) - {"vegetation"})
    assert "vegetation" not in w and w["porewater_salinity"] == pytest.approx(0.15 / 0.65)


def test_multipliers_bounded_and_renormalised():
    w = effective_weights(BASE, {"turbidity": 1.5, "do": 0.5}, set(BASE))
    assert sum(w.values()) == pytest.approx(1)
    assert w["turbidity"] / w["do"] == pytest.approx((0.15 * 1.5) / (0.15 * 0.5))
    clamped = effective_weights(BASE, {"turbidity": 9.0, "do": 0.0}, set(BASE))
    assert clamped["turbidity"] / clamped["do"] == pytest.approx(3.0)


def test_confidence_matches_worked_example():
    assert overall(0.9, 1.0, 0.8) == pytest.approx(0.917, abs=0.001)
    assert overall(0.9, 0.77, 0.8) == pytest.approx(0.826, abs=0.001)


def test_camera_confidence_components():
    assert camera_confidence(True, 30, True, True, False, True) == pytest.approx(0.9)
    assert camera_confidence(False, 30, True, False, True, True) == pytest.approx(0.6 * 0.85)
    assert camera_confidence(True, 600, True, True, True, True) == pytest.approx(0.5)
    assert camera_confidence(True, 30, False, True, True, True) <= 0.5
    assert camera_confidence(False, 0, False, False, False, False) == 0.1
    assert camera_confidence(True, 5000, True, True, True, True) == pytest.approx(0.3)
    assert camera_confidence(True, 1200, True, True, True, True) == pytest.approx(0.4)


def test_sensor_confidence_factors():
    ok = NodeHealthView(online=True, battery_pct=80, last_sample_age_s=5, interval_s=10)
    assert sensor_confidence(0.65, [ok], False) == pytest.approx(1.0)
    assert sensor_confidence(0.65, [], False) == 0.1
    assert sensor_confidence(0.325, [ok], False) == pytest.approx(0.5)
    assert sensor_confidence(0.65, [ok], True) == pytest.approx(0.8)
    spiky = NodeHealthView(True, 80, 5, 10, stuck_or_spike=True)
    assert sensor_confidence(0.65, [spiky], False) == pytest.approx(0.8)
    stale_low = NodeHealthView(True, 10, 100, 10)  # phi 0.5, eta 0.8
    assert sensor_confidence(0.65, [stale_low], False) == pytest.approx(0.4)
    offline = NodeHealthView(False, 80, 5, 10)
    assert sensor_confidence(0.65, [offline], False) == 0.1  # floor
    assert sensor_confidence(0.65, [ok, offline], False) == pytest.approx(0.5)


def test_tier_factors_match_the_spec():
    from bcs_gs.fusion.confidence import tier_factor

    assert TIER_FACTOR == {"gemini_primary": 0.95, "gemini_secondary": 0.90, "gemma_local": 0.80, "rules": 0.75}
    assert {t: tier_factor(t) for t in TIER_FACTOR} == TIER_FACTOR


def test_sensor_composite_excludes_vegetation_and_unmeasured():
    assert sensor_composite({"vegetation": 1.0}, BASE) is None
    c = sensor_composite({"vegetation": 1.0, "do": 1.0, "ph": 0.0, "salinity": None}, BASE)
    assert c == pytest.approx(0.15 / 0.20)


def test_early_warning_needs_three_investigation_or_two_baseline_samples():
    ew = EarlyWarning()
    assert [ew.observe("KSL-B3", 0.1, 0.6, True) for _ in range(3)] == [False, False, True]
    ew2 = EarlyWarning()
    assert [ew2.observe("KSL-B3", 0.1, 0.6, False) for _ in range(2)] == [False, True]
    assert ew.observe("KSL-B3", 0.1, 0.4, True) is False and ew.observe("KSL-B3", 0.1, 0.6, True) is False  # reset


def test_early_warning_fires_once_per_streak_and_resets_on_none():
    ew = EarlyWarning()
    assert [ew.observe("z", 0.1, 0.6, False) for _ in range(5)] == [False, True, False, False, False]
    assert ew.observe("z", None, 0.6, False) is False
    assert [ew.observe("z", 0.1, 0.6, False) for _ in range(2)] == [False, True]
    assert ew.observe("z", 0.2, 0.6, False) is False  # vegetation must be < 0.2
    assert ew.observe("y", 0.1, 0.6, False) is False  # zones are independent


def test_early_warning_mode_switch_does_not_fire_twice_in_a_streak():
    ew = EarlyWarning()
    assert [ew.observe("z", 0.1, 0.6, False) for _ in range(2)] == [False, True]
    assert ew.observe("z", 0.1, 0.6, True) is False  # n=3 in investigation: same streak, already fired
    assert ew.observe("z", 0.1, 0.4, True) is False  # reset
    assert [ew.observe("z", 0.1, 0.6, True) for _ in range(3)] == [False, False, True]


def test_risk_rejects_weights_for_unmeasured_stressors():
    w = effective_weights(BASE, {}, set(BASE))
    with pytest.raises(ValueError):
        risk({**{k: 0.5 for k in BASE}, "do": None}, w)
    with pytest.raises(ValueError):
        risk({"do": 0.5}, w)


# ---- final review fixes ---------------------------------------------------------------------------
def _engine_for_confidence():
    from bcs_gs.fusion.bands import default_settings
    from bcs_gs.fusion.engine import FusionRiskEngine

    eng = FusionRiskEngine.__new__(FusionRiskEngine)  # _confidence reads only the settings and weights
    eng._settings = default_settings()
    eng._base = dict(eng._settings.risk.weights)
    return eng


def _snapshot(*, baseline_ok: bool, metrics: dict):
    from datetime import UTC, datetime

    from bcs_gs.fusion.engine import _Snapshot
    from bcs_protocol.timefmt import to_iso

    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    cap = {"id": "c1", "taken_at": to_iso(now), "evidence_grade": True, "quality": {"exposure_locked": True}}
    eng = _engine_for_confidence()
    return eng, _Snapshot(
        at=now, cover={"KSL-B3": []}, nodes={}, readings={}, latest={}, capture=cap, metrics=metrics,
        baseline_ok=baseline_ok, four_corner=False, camera_online=True, cfg=eng._settings,
    )  # fmt: skip


def test_camera_confidence_low_with_a_capture_but_no_baseline():  # Review Focus 4
    eng, snap = _snapshot(baseline_ok=False, metrics={"KSL-B3": object()})
    no_capture = float(eng._settings.risk.confidence["camera"]["no_capture"])
    assert eng._confidence(snap, "KSL-B3", {"salinity"}, "rules").camera == no_capture
    eng, snap = _snapshot(baseline_ok=True, metrics={})  # baseline, but no metrics for this zone
    assert eng._confidence(snap, "KSL-B3", {"salinity"}, "rules").camera == no_capture
    eng, snap = _snapshot(baseline_ok=True, metrics={"KSL-B3": object()})
    assert eng._confidence(snap, "KSL-B3", {"vegetation"}, "rules").camera > no_capture
