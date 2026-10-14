"""Height-signal maths (addendum N10): robust normalisation, EMA, smoothing and the quality score."""

from __future__ import annotations

import cv2
import numpy as np

EPS = 1e-6
HEIGHT_SIZE = 256
EMA_ALPHA = 0.3
BILATERAL_D = 5  # px neighbourhood
BILATERAL_SIGMA_COLOR = 0.1  # on 0-1 heights
BILATERAL_SIGMA_SPACE = 5.0
FALLBACK_BELOW = 0.35  # quality below this -> colour-class fallback


def normalise_robust(d: np.ndarray, lo: float = 2, hi: float = 98) -> np.ndarray:
    """Map the lo-th..hi-th percentile of ``d`` onto 0..1 and clip; a flat input maps to 0."""
    x = np.asarray(d, np.float32)
    p_lo, p_hi = np.percentile(x, (lo, hi))
    span = float(p_hi - p_lo)
    if not np.isfinite(span) or span < EPS:
        return np.zeros(x.shape, np.float32)
    out = (x - np.float32(p_lo)) / np.float32(span)
    return np.clip(out, 0.0, 1.0, out=out).astype(np.float32, copy=False)


def ema(prev: np.ndarray | None, cur: np.ndarray, alpha: float = EMA_ALPHA) -> np.ndarray:
    """Exponential moving average: ``alpha * cur + (1 - alpha) * prev``; ``cur`` when there is no prev."""
    c = np.asarray(cur, np.float32)
    if prev is None or np.shape(prev) != c.shape:
        return c.copy()
    return (np.float32(alpha) * c + np.float32(1 - alpha) * np.asarray(prev, np.float32)).astype(np.float32)


def to_height_u16(h01: np.ndarray, size: int = HEIGHT_SIZE) -> np.ndarray:
    """0-1 heights -> 5 px bilateral filter -> ``size`` x ``size`` (area) -> uint16 0..65535."""
    h = np.ascontiguousarray(np.clip(np.asarray(h01, np.float32), 0.0, 1.0))
    h = cv2.bilateralFilter(h, BILATERAL_D, BILATERAL_SIGMA_COLOR, BILATERAL_SIGMA_SPACE)
    if h.shape != (size, size):
        h = cv2.resize(h, (size, size), interpolation=cv2.INTER_AREA)
    return np.rint(np.clip(h, 0.0, 1.0) * 65535.0).astype(np.uint16)


def dynamic_range01(d: np.ndarray, lo: float = 2, hi: float = 98) -> float:
    """Dynamic range of raw relative inverse depth, before normalisation, as 0-1.

    ``(p98 - p2) / max(|p98|, eps)``, clipped to [0, 1]. Inverse depth is scale-free, so the spread
    is taken relative to the nearest (largest) robust value: a flat scene gives 0, a scene whose far
    points are much farther than its near points approaches 1.
    """
    p_lo, p_hi = np.percentile(np.asarray(d, np.float32), (lo, hi))
    if not (np.isfinite(p_lo) and np.isfinite(p_hi)):
        return 0.0
    return float(np.clip((p_hi - p_lo) / max(abs(float(p_hi)), EPS), 0.0, 1.0))


def stability(prev: np.ndarray | None, cur: np.ndarray) -> float:
    """Temporal stability ``1 - mean |h_t - h_(t-1)|`` on per-frame normalised heights.

    There is no evidence of stability on the first frame (or after a size change), so it scores 0.
    """
    if prev is None or np.shape(prev) != np.shape(cur):
        return 0.0
    diff = np.abs(np.asarray(cur, np.float32) - np.asarray(prev, np.float32))
    return float(np.clip(1.0 - float(diff.mean()), 0.0, 1.0))


def quality_score(range01: float, stability: float, model_ok: bool) -> float:
    """0.5 x dynamic range + 0.3 x temporal stability + 0.2 x model availability (N10)."""
    return 0.5 * float(range01) + 0.3 * float(stability) + 0.2 * (1.0 if model_ok else 0.0)
