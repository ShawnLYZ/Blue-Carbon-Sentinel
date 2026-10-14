"""Per-pixel RGB indices (product spec section 9): VARI, ExG and the water brownness index."""

from __future__ import annotations

import numpy as np

VARI_MIN_DENOMINATOR = 1e-3  # on normalised RGB (0-1); below it VARI is 0


def _channels(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = np.asarray(rgb, np.float32) / np.float32(255.0)
    return f[..., 0], f[..., 1], f[..., 2]


def vari(rgb: np.ndarray) -> np.ndarray:
    """VARI = (G - R) / (G + R - B) on normalised RGB, clamped to [-1, 1]; 0 where |G + R - B| < 1e-3."""
    r, g, b = _channels(rgb)
    den = g + r - b
    ok = np.abs(den) >= VARI_MIN_DENOMINATOR
    out = np.zeros(den.shape, np.float32)
    np.divide(g - r, den, out=out, where=ok)
    return np.clip(out, -1.0, 1.0, out=out)


def _chromatic(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r, g, b = _channels(rgb)
    total = r + g + b
    inv = np.zeros(total.shape, np.float32)
    np.divide(np.float32(1.0), total, out=inv, where=total > 0)
    return r * inv, g * inv, b * inv


def exg(rgb: np.ndarray) -> np.ndarray:
    """Excess green 2g - r - b on chromatic coordinates (r + g + b = 1); 0 for black pixels."""
    r, g, b = _chromatic(rgb)
    return (2 * g - r - b).astype(np.float32, copy=False)


def brownness(rgb: np.ndarray) -> np.ndarray:
    """(r - b) / (r + g + b), the per-pixel water-discolouration index (addendum N11); 0 for black."""
    r, _, b = _chromatic(rgb)
    return (r - b).astype(np.float32, copy=False)
