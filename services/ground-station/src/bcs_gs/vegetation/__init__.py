"""VegetationAnalyzer: NDVI-proxy indices, land-cover classes, zone metrics and zone flags."""

from bcs_gs.vegetation.classify import classify_raster, otsu_threshold
from bcs_gs.vegetation.flags import evaluate_flags
from bcs_gs.vegetation.indices import brownness, exg, vari
from bcs_gs.vegetation.metrics import (
    BaselineRef,
    ZoneMetricsRow,
    baseline_ref_from,
    zone_index_image,
    zone_metrics,
)

__all__ = [
    "BaselineRef",
    "ZoneMetricsRow",
    "baseline_ref_from",
    "brownness",
    "classify_raster",
    "evaluate_flags",
    "exg",
    "otsu_threshold",
    "vari",
    "zone_index_image",
    "zone_metrics",
]
