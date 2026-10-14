"""Land-cover classification of a site raster (addendum N11; class codes from F5).

Ranges written "a-b" in N11 are inclusive; "<" and ">" are strict. HSV is on OpenCV scales
(H 0-179, S and V 0-255). Texture is the Laplacian squared, box-averaged over the configured
window (7 x 7).
"""

from __future__ import annotations

import cv2
import numpy as np

from bcs_gs.core.config import Classification, Thresholds
from bcs_gs.vegetation.indices import exg

CANOPY, WATER, MUD, OTHER = 1, 2, 3, 4
CLASS_CODES: dict[str, int] = {"canopy": CANOPY, "water": WATER, "mud": MUD, "other": OTHER}

# ExG = 3g - 1 on chromatic coordinates, so it spans [-1, 2]; Otsu runs on 256 bins of that range.
_EXG_LO, _EXG_HI = -1.0, 2.0


def rules(cfg: Thresholds | Classification) -> Classification:
    return cfg.classification if isinstance(cfg, Thresholds) else cfg


def otsu_threshold(exg_values: np.ndarray) -> float:
    """Otsu threshold of ExG values; canopy is ExG strictly above it.

    The value is placed midway between the last background bin and the first foreground bin.
    A sample with a single value yields that value, so nothing lies above it.
    """
    x = np.asarray(exg_values, np.float32).ravel()
    x = x[np.isfinite(x)]
    if x.size == 0:
        raise ValueError("otsu_threshold needs at least one finite value")
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-6:
        return lo
    scale = 255.0 / (_EXG_HI - _EXG_LO)
    q = np.clip(np.rint((x - _EXG_LO) * scale), 0, 255).astype(np.uint8).reshape(1, -1)
    t, _ = cv2.threshold(q, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float((t + 0.5) / scale + _EXG_LO)


def texture(rgb: np.ndarray, window_px: int) -> np.ndarray:
    """Local texture: Laplacian of the grey image, squared, averaged over a window x window box."""
    grey = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY).astype(np.float32)
    lap = cv2.Laplacian(grey, cv2.CV_32F)
    return cv2.blur(lap * lap, (window_px, window_px))


def hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    out = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV)
    return out[..., 0], out[..., 1], out[..., 2]


def _between(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return (x >= lo) & (x <= hi)


def classify_raster(
    rgb: np.ndarray, exg_threshold: float | None, cfg: Thresholds | Classification
) -> np.ndarray:
    """uint8 class map (1 canopy, 2 water, 3 mud, 4 other) of an RGB uint8 raster.

    ``exg_threshold`` is the baseline Otsu threshold; ``None`` (no baseline yet) uses the
    configured default (0.05).
    """
    r = rules(cfg)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("classify_raster expects an H x W x 3 uint8 RGB array")
    t = r.canopy.exg_default if exg_threshold is None else exg_threshold
    h, s, v = hsv(rgb)
    w, m = r.water, r.mud
    masks = {
        "canopy": (exg(rgb) > t) & (s > r.canopy.s_min),
        "water": (
            ((v < w.dark.v_max) & (s < w.dark.s_max))
            | (_between(h, w.blue.h_min, w.blue.h_max) & (s > w.blue.s_min))
        )
        & (texture(rgb, w.texture_window_px) < w.texture_max),
        "mud": (
            _between(h, m.brown.h_min, m.brown.h_max)
            & _between(s, m.brown.s_min, m.brown.s_max)
            & _between(v, m.brown.v_min, m.brown.v_max)
        )
        | ((s < m.grey.s_max) & _between(v, m.grey.v_min, m.grey.v_max)),
    }
    out = np.full(rgb.shape[:2], OTHER, np.uint8)
    for name in reversed(r.precedence):  # lowest precedence first; higher classes overwrite
        if name in masks:
            out[masks[name]] = CLASS_CODES[name]
    return out
