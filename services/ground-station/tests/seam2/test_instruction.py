"""FLUX illustration instruction and the changed-zone threshold (M5 Task 6): pure, generated inputs."""

from __future__ import annotations

from types import SimpleNamespace

from bcs_gs.futures.instruction import (
    SUFFIX,
    ChangeThreshold,
    build_instruction,
    changed_zones,
    position_words,
)
from bcs_gs.futures.repaint import ZoneChange


def test_instruction_uses_spatial_language_and_fixed_suffix():
    s = build_instruction(
        {"KSL-B2": ZoneChange(dieback_frac=0.5), "KSL-E5": ZoneChange(sapling_fill=0.6)}, "with", 2035
    )
    assert "north-west" in s and "south-east" in s
    assert s.endswith("Keep everything else identical; top-down view of a handmade clay mangrove model.")


def test_position_words_per_row_and_column():
    assert position_words("KSL-C3") == "centre"  # "central central" collapses
    assert position_words("KSL-A1") == "north-west"
    assert position_words("KSL-C1") == "north-central"
    assert position_words("KSL-A3") == "central-west"
    assert position_words("KSL-D4") == "south-east"
    assert SUFFIX == "Keep everything else identical; top-down view of a handmade clay mangrove model."


def test_instruction_has_one_sentence_per_changed_zone_and_names_the_change():
    s = build_instruction(
        {
            "KSL-A1": ZoneChange(canopy_loss_frac=0.4),
            "KSL-C3": ZoneChange(eroded_strip_m=6.0, turbidity_stress=0.7),
        },
        "without",
        2030,
    )
    body = s[: -len(SUFFIX)].strip()
    assert body.count(".") == 2  # one sentence per zone
    assert "2030" in body and "centre" in body and "north-west" in body
    assert "mud" in body and "erod" in body and "murk" in body
    assert build_instruction({"KSL-A1": ZoneChange(dieback_frac=0.3)}, "with", 2035) == build_instruction(
        {"KSL-A1": ZoneChange(dieback_frac=0.3)}, "with", 2035
    )  # deterministic


def _pt(year, c, h=0.8, land=0.9, sigma=0.5, cohort=0.0):
    band = lambda v: {"low": v, "central": v, "high": v}
    return {
        "year": year, "canopy": band(c), "health": band(h), "land": band(land), "sigma": band(sigma),
        "cohort_fraction": cohort,
    }  # fmt: skip


def _forecast(zones):
    return {"keyframes": {"with": {"site": [], "zones": zones}}}


def test_changed_zones_applies_each_threshold_between_2026_and_the_year():
    f = _forecast({
        "KSL-A1": [_pt(2026, 0.50), _pt(2035, 0.46)],                  # dC 0.04: unchanged
        "KSL-A2": [_pt(2026, 0.50), _pt(2035, 0.44)],                  # dC 0.06: changed
        "KSL-A3": [_pt(2026, 0.5, land=0.9), _pt(2035, 0.5, land=0.875)],  # dL 0.025: changed
        "KSL-A4": [_pt(2026, 0.5), _pt(2035, 0.5, cohort=0.12)],       # cohort 0.12: changed
        "KSL-A5": [_pt(2026, 0.5, sigma=0.5), _pt(2035, 0.5, sigma=0.7)],  # turbidity 0.4 -> 0.56
        "KSL-B1": [_pt(2026, 0.5, sigma=0.5), _pt(2035, 0.5, sigma=0.9)],  # turbidity 0.4 -> 0.72
        "KSL-B2": [_pt(2026, 0.5)],                                    # no keyframe for the year
    })  # fmt: skip
    state = {
        "KSL-A5": SimpleNamespace(stressors={"turbidity": 0.4}),
        "KSL-B1": SimpleNamespace(stressors={"turbidity": 0.4}),
    }
    got = changed_zones(f, "with", 2035, ChangeThreshold(), base_state=state)
    assert got == ["KSL-A2", "KSL-A3", "KSL-A4", "KSL-B1"]


def test_land_gain_does_not_count_only_land_loss():  # ruling R24
    f = _forecast({
        "KSL-A1": [_pt(2026, 0.5, land=0.90), _pt(2035, 0.5, land=0.95)],  # gain 0.05: unchanged
        "KSL-A2": [_pt(2026, 0.5, land=0.90), _pt(2035, 0.5, land=0.88)],  # loss 0.02: changed
    })  # fmt: skip
    assert changed_zones(f, "with", 2035) == ["KSL-A2"]


def test_changed_zones_cap_at_6_by_change_score():  # ruling R24
    from bcs_gs.futures.instruction import change_scores

    # Canopy losses 0.06 .. 0.15 over ten zones (scores 1.2 .. 3.0); KSL-C1 has the largest score via its
    # cohort (0.5 / 0.1 = 5.0) despite a small canopy change.
    ids = ["KSL-A1", "KSL-A2", "KSL-A3", "KSL-A4", "KSL-A5", "KSL-B1", "KSL-B2", "KSL-B3", "KSL-B4", "KSL-B5"]
    zones = {z: [_pt(2026, 0.5), _pt(2035, 0.5 - 0.06 - 0.01 * i)] for i, z in enumerate(ids)}
    zones["KSL-C1"] = [_pt(2026, 0.5), _pt(2035, 0.49, cohort=0.5)]
    f = _forecast(zones)
    scores = change_scores(f, "with", 2035)
    assert len(scores) == 11 and abs(scores["KSL-C1"] - 5.0) < 1e-9 and abs(scores["KSL-A1"] - 1.2) < 1e-9
    got = changed_zones(f, "with", 2035)
    assert got == sorted(["KSL-C1", "KSL-B5", "KSL-B4", "KSL-B3", "KSL-B2", "KSL-B1"])
    assert changed_zones(f, "with", 2035, max_zones=2) == ["KSL-B5", "KSL-C1"]
