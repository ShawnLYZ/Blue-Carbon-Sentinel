"""Tree positions from the canopy class raster (rules tier of the TreeLocator)."""

from __future__ import annotations

import cv2
import numpy as np

from bcs_gs.vegetation.classify import CANOPY


def blob_centroids(classes: np.ndarray, min_area_px: int = 30) -> list[tuple[float, float]]:
    """Centroids ``(y, x)`` in pixels of the connected canopy blobs of at least ``min_area_px``,
    largest first."""
    mask = (np.asarray(classes) == CANOPY).astype(np.uint8)
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    blobs = [(int(stats[i, cv2.CC_STAT_AREA]), float(cents[i][1]), float(cents[i][0])) for i in range(1, n)]
    blobs = [b for b in blobs if b[0] >= min_area_px]
    blobs.sort(key=lambda b: -b[0])
    return [(y, x) for _, y, x in blobs]
