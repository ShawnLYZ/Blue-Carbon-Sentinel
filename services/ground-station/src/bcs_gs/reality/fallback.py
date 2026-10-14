"""Colour-class fallback heights (addendum N10) for when depth is unavailable or poor."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import yaml

from bcs_gs.core.config import CONFIG_FILES, Classification, Thresholds
from bcs_gs.vegetation.classify import CANOPY, MUD, OTHER, WATER, classify_raster
from bcs_gs.vegetation.indices import vari

from .quality import HEIGHT_SIZE

REPO_ROOT = Path(__file__).resolve().parents[5]
BLUR_SIGMA_PX = 3.0  # at 256 px
CLASS_HEIGHTS = {OTHER: 0.45, MUD: 0.3, WATER: 0.1}
CANOPY_BASE, CANOPY_VARI_GAIN = 0.6, 0.4


@lru_cache(maxsize=1)
def default_thresholds() -> Thresholds:
    """``config/thresholds.yaml`` read once (env overrides apply only through ``Settings``)."""
    path = REPO_ROOT / "config" / CONFIG_FILES["thresholds"]
    return Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def fallback_heights(rgb512: np.ndarray, cfg: Thresholds | Classification | None = None) -> np.ndarray:
    """0-1 heights, 256 x 256: canopy 0.6 + 0.4 x VARI (mapped [-1, 1] -> [0, 1]), other 0.45,
    mud 0.3, water 0.1, then a Gaussian blur with sigma 3 px at 256.

    VARI is mapped with the fixed ``(v + 1) / 2`` rather than per-frame min-max, so the canopy
    height of a pixel does not change because other pixels did (temporal stability).
    """
    rgb = np.ascontiguousarray(rgb512, np.uint8)
    classes = classify_raster(rgb, None, cfg if cfg is not None else default_thresholds())
    h = np.zeros(classes.shape, np.float32)
    for code, value in CLASS_HEIGHTS.items():
        h[classes == code] = value
    canopy = classes == CANOPY
    if canopy.any():
        v01 = (vari(rgb) + 1.0) * 0.5
        h[canopy] = CANOPY_BASE + CANOPY_VARI_GAIN * v01[canopy]
    if h.shape != (HEIGHT_SIZE, HEIGHT_SIZE):
        h = cv2.resize(h, (HEIGHT_SIZE, HEIGHT_SIZE), interpolation=cv2.INTER_AREA)
    h = cv2.GaussianBlur(h, (0, 0), BLUR_SIGMA_PX, borderType=cv2.BORDER_REFLECT)
    return np.clip(h, 0.0, 1.0).astype(np.float32, copy=False)
