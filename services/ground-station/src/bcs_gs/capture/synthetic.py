"""Deterministic synthetic site media for test-mode seeded captures (ruling R22a).

A seeded capture is made from numbers, so it has no camera frame. To let the whole pipeline (future
textures, trees, ...) work in test mode, the artefacts are generated from the zone metrics: inside each
zone the class shares follow the metrics along the columns (water, then canopy, then mud, then other),
so water edges are straight and the picture is the same for the same numbers. Cheap: 512 x 512 arrays.
These files are never used to compute metrics, flags or baselines.
"""

from __future__ import annotations

import numpy as np

from bcs_gs.site.registry import SiteRegistry
from bcs_gs.vegetation import vari
from bcs_gs.vegetation.metrics import zone_index_image

SIZE = 512
# class code -> (RGB, height as a fraction of 65535); canopy 1, water 2, mud 3, other 4
LOOK = {
    1: ((40, 160, 40), 0.60),
    2: ((30, 100, 200), 0.02),
    3: ((139, 101, 60), 0.30),
    4: ((200, 200, 200), 0.35),
}


def synthetic_artefacts(
    metrics: dict[str, object], registry: SiteRegistry
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(rgb, height_u16, classes, vari image) for the seeded zone ``metrics`` (ZoneMetrics-like)."""
    labels, ids = zone_index_image(registry, SIZE)
    classes = np.full((SIZE, SIZE), 4, np.uint8)
    for i, zone_id in enumerate(ids):
        m = metrics.get(zone_id)
        if m is None:
            continue
        ys, xs = np.nonzero(labels == i)
        f = (xs - xs.min() + 0.5) / (xs.max() - xs.min() + 1.0)  # 0-1 across the zone, west to east
        edges = np.cumsum([m.water_pct, m.canopy_pct, m.mud_pct]) / 100.0
        code = np.where(f < edges[0], 2, np.where(f < edges[1], 1, np.where(f < edges[2], 3, 4)))
        classes[ys, xs] = code.astype(np.uint8)
    rgb = np.zeros((SIZE, SIZE, 3), np.uint8)
    height = np.zeros((SIZE, SIZE), np.uint16)
    for code, (colour, h) in LOOK.items():
        rgb[classes == code] = colour
        height[classes == code] = int(h * 65535)
    return rgb, height, classes, vari(rgb)
