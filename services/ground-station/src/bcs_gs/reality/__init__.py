"""Reality layer: live height map from depth (DirectML) or colour classes (addendum N10)."""

from .depth import DepthRunner, preprocess
from .fallback import fallback_heights
from .layer import HeightFrame, RealityLayer
from .quality import dynamic_range01, ema, normalise_robust, quality_score, stability, to_height_u16

__all__ = [
    "DepthRunner",
    "HeightFrame",
    "RealityLayer",
    "dynamic_range01",
    "ema",
    "fallback_heights",
    "normalise_robust",
    "preprocess",
    "quality_score",
    "stability",
    "to_height_u16",
]
