"""Generated-array helpers for the vegetation tests (NumPy only, no image files).

Scenes are a neutral "other" background (230, 230, 230) with the content placed in zone KSL-B3,
whose raster pixels are derived here independently of the analyzer: pixel centres (u + 0.5) and
(v + 0.5) scaled by 500 / 512 m must fall in [100, 200) east and [200, 300) south (addendum F4).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from bcs_gs.core.config import load_settings
from bcs_gs.site.registry import SiteRegistry
from bcs_gs.vegetation import BaselineRef, baseline_ref_from, classify_raster, zone_metrics

REPO_ROOT = Path(__file__).resolve().parents[4]
_SETTINGS = load_settings(REPO_ROOT, env_file=None)
CFG = _SETTINGS.thresholds
REGISTRY = SiteRegistry(_SETTINGS.site)

N = 512
GREEN, BROWN, WATER, YELLOWED = (40, 160, 40), (120, 90, 60), (30, 60, 110), (170, 150, 40)
BACKGROUND = (230, 230, 230)  # grey with V > 200: "other" (N11)


def px(rgb: tuple[int, int, int]) -> np.ndarray:
    return np.array(rgb, np.uint8).reshape(1, 1, 3)


def tile(colours: list[tuple[int, int, int]]) -> np.ndarray:
    """512 x 512 image of four quadrants: top-left, top-right, bottom-left, bottom-right."""
    img = np.empty((N, N, 3), np.uint8)
    for (rows, cols), colour in zip(quadrants(), colours, strict=True):
        img[rows, cols] = colour
    return img


def quadrants() -> list[tuple[slice, slice]]:
    h = N // 2
    top, bottom, left, right = slice(0, h), slice(h, N), slice(0, h), slice(h, N)
    return [(top, left), (top, right), (bottom, left), (bottom, right)]


def mode_of(classes: np.ndarray, q: tuple[slice, slice]) -> int:
    return int(np.bincount(classes[q].ravel()).argmax())


def _span(index: int) -> tuple[int, int]:
    """Half-open pixel range whose centres lie in [100 * index, 100 * index + 100) metres."""
    centres_m = (np.arange(N) + 0.5) * 500 / N
    inside = np.flatnonzero((centres_m >= 100 * index) & (centres_m < 100 * index + 100))
    return int(inside[0]), int(inside[-1]) + 1


def zone_box(col: int = 1, row: int = 2) -> tuple[int, int, int, int]:
    """(v0, v1, u0, u1) of a zone; the default is KSL-B3 (column B = 1, row 3 = 2)."""
    (u0, u1), (v0, v1) = _span(col), _span(row)
    return v0, v1, u0, u1


def zone_image(
    canopy_fraction: float = 0.0,
    recolour_fraction: float = 0.0,
    colour: tuple[int, int, int] = YELLOWED,
    water: bool = False,
    water_colour: tuple[int, int, int] = WATER,
) -> np.ndarray:
    """Background scene with zone B3 filled: optional water, then green canopy over the top
    ``canopy_fraction`` of the zone's rows, of which the top ``recolour_fraction`` is ``colour``."""
    img = np.empty((N, N, 3), np.uint8)
    img[:] = BACKGROUND
    v0, v1, u0, u1 = zone_box()
    if water:
        img[v0:v1, u0:u1] = water_colour
    n_canopy = round(canopy_fraction * (v1 - v0))
    img[v0 : v0 + n_canopy, u0:u1] = GREEN
    img[v0 : v0 + round(recolour_fraction * n_canopy), u0:u1] = colour
    return img


def add_blobs(img: np.ndarray, n: int, size_px: int) -> np.ndarray:
    """Copy of ``img`` with ``n`` separate green squares in zone B3, packed upward from the zone's
    bottom edge, each at least 4 px from any other blob and any existing non-background pixel."""
    out = img.copy()
    v0, v1, u0, u1 = zone_box()
    pitch = size_px + 4
    per_row = (u1 - u0 - 2) // pitch
    content = np.any(img[v0:v1, u0:u1] != BACKGROUND, axis=2)
    for k in range(n):
        top = v1 - 2 - size_px - (k // per_row) * pitch
        left = u0 + 2 + (k % per_row) * pitch
        r0, c0 = top - v0, left - u0
        near = content[max(r0 - 4, 0) : r0 + size_px + 4, max(c0 - 4, 0) : c0 + size_px + 4]
        assert top >= v0 and not near.any(), "blobs do not fit below the existing content"
        out[top : top + size_px, left : left + size_px] = GREEN
    return out


def baseline_from(img: np.ndarray) -> BaselineRef:
    return baseline_ref_from(img, CFG, registry=REGISTRY)


def metrics_for(img: np.ndarray, baseline: BaselineRef | None):
    classes = classify_raster(img, baseline.exg_threshold if baseline else None, CFG)
    return zone_metrics(img, classes, baseline, CFG, registry=REGISTRY)


def kinds(flags) -> list[str]:
    return [f.kind for f in flags]
