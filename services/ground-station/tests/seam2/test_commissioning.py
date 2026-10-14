"""Seam 2: commissioning layout, coverage model (N9) and coverage-gap advice (§12, §15) on generated masks."""

from __future__ import annotations

import itertools
import math

import numpy as np
from bcs_gs.capture.artefacts import decode_indexed_png, indexed_png
from bcs_gs.nodes.commissioning import NodePos, candidates, plan_layout
from bcs_gs.nodes.coverage import coverage, gap_suggestions, node_covers

K = 500 / 512  # metres per site-raster pixel


def estuary_mask() -> np.ndarray:
    """West third water (2), a mud band (3), canopy east (1)."""
    c = np.full((512, 512), 1, np.uint8)
    c[:, :170] = 2
    c[:, 170:230] = 3
    return c


def pairs_same_type(positions):
    for a, b in itertools.combinations(positions, 2):
        if a.node_type == b.node_type:
            yield a, b


def dist_m(a, b) -> float:
    return math.hypot(a.e_m - b.e_m, a.s_m - b.s_m)


def _pos(node_id, node_type, e, s):
    return NodePos(node_id, node_type, e, s, e / K, s / K, "")


def layout_nodes_only_west():
    return [
        _pos("TG-01", "tide_gauge", 0.0, 250.0),
        _pos("WQ-01", "water_quality", 50.0, 100.0),
        _pos("WQ-02", "water_quality", 50.0, 300.0),
        _pos("SP-01", "soil_probe", 120.0, 200.0),
    ]


# ---- brief tests ----------------------------------------------------------------------------------
def test_layout_on_generated_estuary_places_types_on_their_classes():
    classes = estuary_mask()
    lay = plan_layout(classes, seed=0)
    by = {p.node_id[:2]: p for p in lay.positions}
    assert set(by) == {"TG", "WQ", "SP"} and len(lay.positions) == 8
    assert all(
        classes[int(p.v_px), int(p.u_px)] == 2 for p in lay.positions if p.node_type == "water_quality"
    )
    assert all(classes[int(p.v_px), int(p.u_px)] == 3 for p in lay.positions if p.node_type == "soil_probe")
    assert lay.confidence == "high" and lay.method == "class_map"


def test_spacing_at_least_80m_between_same_type():
    lay = plan_layout(estuary_mask(), seed=0)
    for a, b in pairs_same_type(lay.positions):
        assert dist_m(a, b) >= 80


def test_deterministic_for_seed():
    assert plan_layout(estuary_mask(), seed=3) == plan_layout(estuary_mask(), seed=3)


def test_fallback_without_water_or_mud_is_low_confidence_with_reason():
    lay = plan_layout(np.full((512, 512), 4, np.uint8), seed=0)
    tg = next(p for p in lay.positions if p.node_type == "tide_gauge")
    assert (
        lay.confidence == "low"
        and lay.reasons == ["no water/mud visible"]
        and (tg.e_m, tg.s_m) == (0.0, 250.0)
    )


def test_gap_suggestion_for_uncovered_flagged_zone():
    nodes = layout_nodes_only_west()
    s = gap_suggestions(["KSL-E5"], estuary_mask(), nodes)[0]
    assert (
        s.zone_id == "KSL-E5"
        and "KSL-E5" in s.newly_covered
        and s.node_type in ("water_quality", "soil_probe")
    )


# ---- further checks -------------------------------------------------------------------------------
def test_candidates_follow_their_masks():
    c = estuary_mask()
    cand = candidates(c)
    assert cand.wq and all(c[v, u] == 2 and u <= 167 for u, v in cand.wq)  # eroded by 2 px
    assert cand.sp and all(c[v, u] == 3 and u >= 220 for u, v in cand.sp)  # within 10 px of canopy
    assert cand.tg and all(u == 169 for u, v in cand.tg)  # the water edge next to the mud
    # one candidate per 8 px block at most
    for lst in (cand.wq, cand.sp, cand.tg):
        blocks = [(u // 8, v // 8) for u, v in lst]
        assert len(blocks) == len(set(blocks))


def test_tg_is_the_shoreline_point_nearest_the_west_midpoint():
    lay = plan_layout(estuary_mask(), seed=0)
    tg = next(p for p in lay.positions if p.node_type == "tide_gauge")
    assert int(tg.u_px) == 169 and abs(tg.v_px - 256) <= 8


def test_fallback_without_capture_and_its_spread():
    lay = plan_layout(None, seed=0)
    assert lay.method == "fallback_spread" and lay.confidence == "low"
    assert lay.reasons == ["no capture available"]
    ids = [p.node_id for p in lay.positions]
    assert sorted(ids) == ["SP-01", "SP-02", "SP-03", "TG-01", "WQ-01", "WQ-02", "WQ-03", "WQ-04"]
    first_wq = next(p for p in lay.positions if p.node_id == "WQ-01")
    assert math.hypot(first_wq.e_m - 250, first_wq.s_m - 250) < 18  # the cell nearest the centre
    for a, b in itertools.combinations(lay.positions, 2):
        assert dist_m(a, b) >= 80
    assert all(0 <= p.e_m <= 500 and 0 <= p.s_m <= 500 for p in lay.positions)


def test_layout_covers_more_zones_than_one_node_could():
    lay = plan_layout(estuary_mask(), seed=0)
    cov = coverage(lay.positions)
    covered = [z.zone_id for z in cov.zones if z.covered]
    assert len(cov.zones) == 25 and len(covered) >= 12
    assert cov.gaps == []


def test_coverage_radii_and_tg_covers_nothing():
    nodes = [_pos("WQ-01", "water_quality", 250, 250), _pos("SP-01", "soil_probe", 50, 50),
             _pos("TG-01", "tide_gauge", 450, 450)]  # fmt: skip
    cov = {z.zone_id: z for z in coverage(nodes).zones}
    assert cov["KSL-C3"].water == ["WQ-01"] and cov["KSL-B2"].water == ["WQ-01"]  # 141 m diagonal
    assert cov["KSL-A3"].water == []  # 200 m
    assert cov["KSL-A1"].soil == ["SP-01"] and cov["KSL-B1"].soil == ["SP-01"] and cov["KSL-B2"].soil == []
    assert not cov["KSL-E5"].covered
    assert node_covers(nodes[2]) == {"water": [], "soil": []}


def test_gap_suggestion_prefers_water_quality_where_water_is_present():
    nodes = [_pos("TG-01", "tide_gauge", 0.0, 250.0)]
    s = gap_suggestions(["KSL-A1"], estuary_mask(), nodes)[0]
    assert s.node_type == "water_quality" and "KSL-A1" in s.newly_covered
    u, v = int(s.u_px), int(s.v_px)
    assert estuary_mask()[v, u] == 2 and s.e_m <= 200 and s.s_m <= 200  # inside or adjacent
    assert gap_suggestions(["KSL-A1"], estuary_mask(), [*nodes, _pos("WQ-01", "water_quality", 50, 50)]) == []


def test_class_map_png_round_trip():
    c = estuary_mask()
    assert np.array_equal(decode_indexed_png(indexed_png(c)), c)


def small_pond_mask() -> np.ndarray:
    """A 60 x 60 px pond with a 30 px mud strip below it, canopy around (water + mud just over 2%)."""
    c = np.full((512, 512), 1, np.uint8)
    c[200:260, 200:260] = 2
    c[260:290, 200:260] = 3
    return c


def test_spacing_is_never_relaxed_when_candidates_run_out():
    classes = small_pond_mask()
    assert float(np.isin(classes, (2, 3)).mean()) >= 0.02  # not the whole-map fallback
    lay = plan_layout(classes, seed=0)
    assert len(lay.positions) == 8 and lay.method == "class_map" and lay.confidence == "low"
    for a, b in pairs_same_type(lay.positions):
        assert dist_m(a, b) >= 80, (a.node_id, b.node_id)
    for a, b in itertools.combinations(lay.positions, 2):
        assert dist_m(a, b) > 1e-6, (a.node_id, b.node_id)
    assert len(lay.reasons) == len(set(lay.reasons)) and lay.reasons
