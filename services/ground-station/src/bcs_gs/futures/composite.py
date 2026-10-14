"""Composite a FLUX illustration over the real capture, only inside the changed zones (pure).

The weight is 0 outside the union of the zone masks (those pixels are exactly the real capture), rises
linearly over ``feather_px`` pixels inside the union's edge (distance to the nearest outside pixel), and is
exactly 1 deeper inside. Borders shared by two changed zones are inside the union, so they get no seam.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from bcs_gs.futures.repaint import ZoneGrid

SIZE = 1024


def zone_masks_1024(grid: ZoneGrid, zone_ids: Sequence[str], size: int = SIZE) -> list[np.ndarray]:
    """The zones' masks on the grid, upscaled (nearest) to ``size`` x ``size`` booleans."""
    out = []
    for z in zone_ids:
        if z not in grid.ids:
            continue
        m = grid.mask(z).astype(np.uint8)
        out.append(cv2.resize(m, (size, size), interpolation=cv2.INTER_NEAREST).astype(bool))
    return out


def feather_weight(union: np.ndarray, feather_px: int) -> np.ndarray:
    """float32 in [0, 1]: 0 outside ``union``, distance / feather_px inside, clipped to 1."""
    if not union.any():
        return np.zeros(union.shape, np.float32)
    if feather_px <= 0:
        return union.astype(np.float32)
    dist = cv2.distanceTransform(union.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    w = np.clip(dist / float(feather_px), 0.0, 1.0).astype(np.float32)
    w[~union] = 0.0
    return w


def composite(
    real_rgb1024: np.ndarray,
    illustration_rgb1024: np.ndarray,
    zone_masks: list[np.ndarray],
    feather_px: int = 8,
) -> np.ndarray:
    """uint8 H x W x 3: the illustration inside the union of ``zone_masks`` (feathered inward), the real
    image everywhere else, pixel for pixel."""
    if real_rgb1024.shape != illustration_rgb1024.shape:
        raise ValueError("the real image and the illustration must have the same shape")
    union = np.zeros(real_rgb1024.shape[:2], bool)
    for m in zone_masks:
        if m.shape != union.shape:
            raise ValueError("every zone mask must match the image size")
        union |= m
    w = feather_weight(union, feather_px)
    out = real_rgb1024.copy()
    inside = w > 0
    wi = w[inside][:, None]
    mixed = real_rgb1024[inside].astype(np.float32) * (1.0 - wi) + illustration_rgb1024[inside] * wi
    out[inside] = np.clip(np.rint(mixed), 0, 255).astype(np.uint8)
    full = w >= 1.0
    out[full] = illustration_rgb1024[full]  # exact, whatever the float rounding
    return out
