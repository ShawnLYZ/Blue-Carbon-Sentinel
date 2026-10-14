import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcs_gs.vegetation import ZoneMetricsRow, evaluate_flags, vari, zone_index_image
from vegetation_helpers import (
    BROWN,
    CFG,
    GREEN,
    REGISTRY,
    WATER,
    YELLOWED,
    add_blobs,
    baseline_from,
    classify_raster,
    kinds,
    metrics_for,
    mode_of,
    px,
    quadrants,
    tile,
    zone_image,
)


def test_vari_known_colours():
    assert vari(px(GREEN))[0, 0] == pytest.approx((160 - 40) / (160 + 40 - 40), abs=1e-3)
    assert vari(px((0, 0, 0)))[0, 0] == 0  # small-denominator guard


def test_classification_of_generated_patches():
    img = tile([GREEN, BROWN, WATER, (230, 230, 230)])  # R5: (200, 200, 200) is mud under N11
    c = classify_raster(img, exg_threshold=0.05, cfg=CFG)
    assert [mode_of(c, q) for q in quadrants()] == [1, 3, 2, 4]


def test_canopy_loss_and_flags_against_baseline():
    base = zone_image(canopy_fraction=0.60)
    now = zone_image(canopy_fraction=0.45)  # in zone B3
    m = metrics_for(now, baseline_from(base))["KSL-B3"]
    assert m.canopy_loss_pp == pytest.approx(15, abs=1.0)
    assert [f.kind for f in evaluate_flags(m, None, CFG)] == ["canopy_loss"]


def test_dieback_from_yellowed_canopy():
    m = metrics_for(
        zone_image(canopy_fraction=0.6, recolour_fraction=0.3, colour=YELLOWED),
        baseline_from(zone_image(0.6)),
    )["KSL-B3"]
    assert m.dieback_pct == pytest.approx(30, abs=3) and "dieback" in kinds(evaluate_flags(m, None, CFG))


def test_new_growth_small_blobs_count_and_flag():
    m = metrics_for(add_blobs(zone_image(0.3), n=40, size_px=6), baseline_from(zone_image(0.3)))["KSL-B3"]
    assert m.new_growth_pct >= 3 and "new_growth" in kinds(evaluate_flags(m, None, CFG))


def test_discolouration_of_water():
    m = metrics_for(
        zone_image(water=True, water_colour=(120, 90, 60)), baseline_from(zone_image(water=True))
    )["KSL-B3"]
    assert m.discolouration >= 0.15 and "discolouration" in kinds(evaluate_flags(m, None, CFG))


def test_scene_without_canopy_yields_null_vari_and_no_flags():  # Review Focus 4
    m = metrics_for(np.full((512, 512, 3), 128, np.uint8), None)["KSL-B3"]
    assert m.vari_mean is None and m.canopy_loss_pp is None and evaluate_flags(m, None, CFG) == []


def test_metrics_cover_all_25_zones_and_fractions_sum_to_100():
    ms = metrics_for(tile([GREEN, BROWN, WATER, (200, 200, 200)]), None)
    assert len(ms) == 25 and all(
        abs(m.canopy_pct + m.water_pct + m.mud_pct + m.other_pct - 100) < 1e-6 for m in ms.values()
    )


# ---- beyond the brief ---------------------------------------------------------------------------
def test_zone_label_image_honours_f4_block_boundaries():
    labels, ids = zone_index_image(REGISTRY, 512)
    zone = lambda v, u: ids[labels[v, u]]
    # pixel centre 101.5 * 500/512 = 99.1 m (column A); 102.5 * 500/512 = 100.1 m (column B)
    assert (zone(0, 101), zone(0, 102), zone(101, 0), zone(102, 0)) == (
        "KSL-A1",
        "KSL-B1",
        "KSL-A1",
        "KSL-A2",
    )
    assert zone(511, 511) == "KSL-E5" and sorted(set(ids)) == sorted(z.id for z in REGISTRY.zones())


def test_index_drop_against_baseline_vari():
    paler = zone_image(0.6)
    paler[np.all(paler == GREEN, axis=2)] = (60, 160, 40)  # still canopy; VARI 0.75 -> 0.556
    base = baseline_from(zone_image(0.6))
    m = metrics_for(paler, base)["KSL-B3"]
    assert base.vari_mean["KSL-B3"] == pytest.approx(0.75, abs=1e-3)
    assert m.vari_drop == pytest.approx(0.75 - 100 / 180, abs=1e-3) and m.canopy_loss_pp == pytest.approx(0)
    assert "index_drop" in kinds(evaluate_flags(m, None, CFG))


def test_without_baseline_comparisons_are_null_and_vari_stats_are_over_canopy():
    m = metrics_for(zone_image(0.6), None)["KSL-B3"]
    assert (m.canopy_loss_pp, m.vari_drop, m.discolouration, m.dieback_pct, m.new_growth_pct) == (
        None, None, None, 0, 0,
    )  # fmt: skip
    assert m.vari_mean == m.vari_p10 == m.vari_p90 == pytest.approx(0.75, abs=1e-3)
    assert m.canopy_pct == pytest.approx(60, abs=1) and m.other_pct == pytest.approx(40, abs=1)


def test_zone_without_baseline_water_has_null_discolouration():
    m = metrics_for(zone_image(0.6), baseline_from(zone_image(0.6)))["KSL-B3"]
    assert m.discolouration is None and m.canopy_loss_pp == pytest.approx(0) and m.dieback_pct == 0


def _row(**kw) -> ZoneMetricsRow:
    base = {"zone_id": "KSL-B3", "canopy_pct": 40, "water_pct": 0, "mud_pct": 0, "other_pct": 60}
    base |= {"dieback_pct": 0, "new_growth_pct": 0}
    return ZoneMetricsRow(**{**base, **kw})


def test_flags_fire_at_threshold_in_fixed_order_with_values_and_thresholds():
    m = _row(canopy_loss_pp=10, dieback_pct=15, vari_drop=0.10, discolouration=0.15, new_growth_pct=3)
    flags = evaluate_flags(m, None, CFG)
    assert kinds(flags) == ["canopy_loss", "dieback", "index_drop", "discolouration", "new_growth"]
    assert [(f.value, f.threshold) for f in flags] == [(10, 10), (15, 15), (0.10, 0.10), (0.15, 0.15), (3, 3)]
    below = _row(
        canopy_loss_pp=9.9, dieback_pct=14.9, vari_drop=0.099, discolouration=0.149, new_growth_pct=2.9
    )
    assert evaluate_flags(below, None, CFG) == []
    assert evaluate_flags(_row(), None, CFG) == []  # every comparison None or 0: nothing fires, no crash


def test_new_growth_versus_capture_at_plan_application():
    at_app = _row(canopy_pct=40)
    grown = evaluate_flags(_row(canopy_pct=45), at_app, CFG)
    assert [(f.kind, f.value, f.threshold) for f in grown] == [("new_growth", 5, 5)]
    assert evaluate_flags(_row(canopy_pct=44.9), at_app, CFG) == []


def test_metrics_row_matches_zone_metrics_table():
    from bcs_gs.store.schema import SYNCED_TABLES

    cols = list(SYNCED_TABLES["zone_metrics"].columns)
    row = metrics_for(zone_image(0.6), baseline_from(zone_image(0.45)))["KSL-B3"].to_row("cap-1")
    assert sorted(row) == sorted(cols) and row["capture_id"] == "cap-1" and row["flags"] == []
