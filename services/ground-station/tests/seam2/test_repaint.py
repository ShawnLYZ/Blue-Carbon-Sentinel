"""Code-only future repaint and heights (Task 5): generated arrays, NumPy only."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bcs_gs.futures.heights import future_heights, zone_changes_for
from bcs_gs.futures.repaint import ZoneChange, ZoneGrid, repaint
from bcs_gs.vegetation.metrics import zone_index_image
from vegetation_helpers import REGISTRY, N

LABELS, IDS = zone_index_image(REGISTRY, N)
GRID = ZoneGrid(LABELS, IDS, 500.0 / N)
GREEN, MUD_RGB, WATER_RGB, GREY = (40, 160, 40), (139, 101, 60), (30, 100, 200), (230, 230, 230)


def zone_mask(zone: str) -> np.ndarray:
    return LABELS == IDS.index(zone)


def paint(classes: np.ndarray, region: np.ndarray, code: int, rgb: tuple[int, int, int], img: np.ndarray):
    classes[region] = code
    img[region] = rgb


def generated_scene() -> tuple[np.ndarray, np.ndarray]:
    """Canopy over zones B3 and C3, some mud and water in each."""
    img = np.empty((N, N, 3), np.uint8)
    img[:] = GREY
    cls = np.full((N, N), 4, np.uint8)
    for z in ("KSL-B3", "KSL-C3"):
        m = zone_mask(z)
        paint(cls, m, 1, GREEN, img)
        ys, xs = np.nonzero(m)
        mud = m.copy()
        mud[:] = False
        mud[ys[: len(ys) // 5], xs[: len(ys) // 5]] = True
        paint(cls, mud, 3, MUD_RGB, img)
    return img, cls


def generated_scene_with_shore() -> tuple[np.ndarray, np.ndarray]:
    """Water for u < 50, mud for u >= 50, across the rows of zone A3 (column 0, row 2)."""
    img = np.empty((N, N, 3), np.uint8)
    img[:] = GREY
    cls = np.full((N, N), 4, np.uint8)
    a3 = zone_mask("KSL-A3")
    cols = np.arange(N)[None, :] * np.ones((N, 1), int)
    paint(cls, a3 & (cols < 50), 2, WATER_RGB, img)
    paint(cls, a3 & (cols >= 50), 3, MUD_RGB, img)
    return img, cls


def generated_heights(cls: np.ndarray) -> np.ndarray:
    h = np.full(cls.shape, 20000, np.uint16)
    h[cls == 2] = 1000
    h[cls == 1] = 40000
    return h


def mean_rgb(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return img[mask].astype(float).mean(axis=0)


def colour_dist(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))


def test_dieback_browns_only_canopy_in_that_zone():
    img, cls = generated_scene()
    out = repaint(img, cls, {"KSL-B3": ZoneChange(dieback_frac=1.0)}, grid=GRID)
    b3 = zone_mask("KSL-B3")
    assert colour_dist(mean_rgb(out, b3 & (cls == 1)), (120, 100, 80)) < 15
    assert (out[b3 & (cls == 3)] == img[b3 & (cls == 3)]).all()  # mud in the zone is untouched
    c3 = zone_mask("KSL-C3")
    assert (out[c3] == img[c3]).all()
    assert (out[~b3] == img[~b3]).all()


def test_erosion_turns_edge_strip_into_water_and_lowers_heights():
    img, cls = generated_scene_with_shore()
    h = generated_heights(cls)
    ch = {"KSL-A3": ZoneChange(eroded_strip_m=10)}
    out_img, out_h = repaint(img, cls, ch, grid=GRID), future_heights(h, cls, ch, grid=GRID)
    px = round(10 / GRID.m_per_px)
    cols = np.arange(N)[None, :] * np.ones((N, 1), int)
    strip = zone_mask("KSL-A3") & (cols >= 50) & (cols < 50 + px)
    assert strip.any()
    assert colour_dist(mean_rgb(out_img, strip), mean_rgb(img, zone_mask("KSL-A3") & (cls == 2))) < 10
    assert out_h[strip].max() <= np.percentile(h[cls == 2], 5) + 1
    beyond = zone_mask("KSL-A3") & (cols >= 50 + px)
    assert (out_img[beyond] == img[beyond]).all() and (out_h[beyond] == h[beyond]).all()


def test_repaint_is_deterministic():
    img, cls = generated_scene()
    ch = {"KSL-B3": ZoneChange(canopy_loss_frac=0.4)}
    assert (repaint(img, cls, ch, grid=GRID) == repaint(img, cls, ch, grid=GRID)).all()


def test_canopy_loss_converts_the_share_to_mud_colour_and_lowers_heights():
    img, cls = generated_scene()
    ch = {"KSL-B3": ZoneChange(canopy_loss_frac=0.4)}
    out = repaint(img, cls, ch, grid=GRID)
    canopy = zone_mask("KSL-B3") & (cls == 1)
    lost = canopy & (out == np.array(MUD_RGB, np.uint8)).all(axis=2)
    assert abs(lost.sum() - round(0.4 * canopy.sum())) <= 1
    h = generated_heights(cls)
    out_h = future_heights(h, cls, ch, grid=GRID)
    assert out_h[canopy].max() == round(40000 * 0.6)
    assert (out_h[~zone_mask("KSL-B3")] == h[~zone_mask("KSL-B3")]).all()


def test_turbidity_tints_water_and_saplings_speckle_mud():
    img, cls = generated_scene_with_shore()
    ch = {"KSL-A3": ZoneChange(turbidity_stress=1.0, sapling_fill=0.25)}
    out = repaint(img, cls, ch, grid=GRID)
    a3 = zone_mask("KSL-A3")
    expected = np.array(WATER_RGB) * 0.4 + np.array((140, 110, 70)) * 0.6
    assert colour_dist(mean_rgb(out, a3 & (cls == 2)), expected) < 2
    mud = a3 & (cls == 3)
    share = (out[mud] == np.array((60, 140, 60), np.uint8)).all(axis=1).mean()
    assert 0.2 < share < 0.3


def test_zone_changes_from_keyframes():
    def pt(year, c, h, l, s, f=0.0):
        band = lambda v: {"low": v, "central": v, "high": v}
        return {"year": year, "canopy": band(c), "health": band(h), "land": band(l), "sigma": band(s),
                "cohort_fraction": f}  # fmt: skip

    fc = {
        "keyframes": {
            "without": {
                "zones": {"KSL-B3": [pt(2026, 0.5, 0.8, 0.9, 0.2), pt(2035, 0.3, 0.4, 0.8, 0.4, 0.5)]}
            }
        }
    }
    state = {"KSL-B3": type("S", (), {"stressors": {"turbidity": 0.4}})()}
    ch = zone_changes_for(fc, "without", 2035, state)["KSL-B3"]
    assert (ch.dieback_frac, ch.canopy_loss_frac, ch.sapling_fill) == pytest.approx((0.5, 0.4, 0.5))
    assert ch.turbidity_stress == pytest.approx(0.8)  # 0.4 x 0.4 / 0.2
    assert abs(ch.eroded_strip_m - 10.0) < 1e-9
    zero = zone_changes_for(fc, "without", 2026, state)["KSL-B3"]
    assert zero.is_zero()
    assert zone_changes_for(fc, "without", 2035, {})["KSL-B3"].turbidity_stress == 0.0  # no stressor
