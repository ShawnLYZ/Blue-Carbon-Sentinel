"""Zone-masked compositing of a FLUX illustration over the real capture (M5 Task 6): generated arrays."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bcs_gs.futures.composite import composite, zone_masks_1024
from bcs_gs.futures.repaint import ZoneGrid
from bcs_gs.vegetation.metrics import zone_index_image
from vegetation_helpers import REGISTRY, N

LABELS, IDS = zone_index_image(REGISTRY, N)
GRID = ZoneGrid(LABELS, IDS, 500.0 / N)


def gen_rgb(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (1024, 1024, 3), dtype=np.uint8)


def zone_mask_1024(zone: str) -> np.ndarray:
    return zone_masks_1024(GRID, [zone])[0]


def _morph(m: np.ndarray, px: int, op) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return op(m.astype(np.uint8), k).astype(bool)


def dilate(m: np.ndarray, px: int) -> np.ndarray:
    return _morph(m, px, cv2.dilate)


def erode(m: np.ndarray, px: int) -> np.ndarray:
    return _morph(m, px, cv2.erode)


def test_composite_keeps_real_pixels_outside_changed_zones():
    real = gen_rgb(1)
    ill = gen_rgb(2)
    m = zone_mask_1024("KSL-B3")
    out = composite(real, ill, [m])
    assert (out[~dilate(m, 9)] == real[~dilate(m, 9)]).all() and (out[erode(m, 9)] == ill[erode(m, 9)]).all()


def test_composite_feathers_only_inside_the_union_and_is_exact_outside():
    real, ill = gen_rgb(3), gen_rgb(4)
    a, b = zone_mask_1024("KSL-B3"), zone_mask_1024("KSL-C3")  # neighbours: one union, no seam
    out = composite(real, ill, [a, b])
    union = a | b
    assert (out[~union] == real[~union]).all()  # weight is exactly 0 outside the union
    edge = union & ~erode(union, 8)
    blended = (out[edge] != real[edge]) & (out[edge] != ill[edge])
    assert blended.any()  # a feathered band just inside the edge
    seam = erode(union, 9) & dilate(a, 1) & dilate(b, 1)
    assert seam.any() and (out[seam] == ill[seam]).all()  # no feather along the shared border
    assert out.dtype == np.uint8 and out.shape == real.shape


def test_composite_with_no_masks_is_the_real_image():
    real, ill = gen_rgb(5), gen_rgb(6)
    assert (composite(real, ill, []) == real).all()


def test_zone_masks_1024_are_the_512_grid_upscaled_nearest():
    m = zone_mask_1024("KSL-A1")
    assert m.shape == (1024, 1024) and m.dtype == bool
    small = GRID.mask("KSL-A1")
    assert (m[::2, ::2] == small).all() and (m[1::2, 1::2] == small).all()
