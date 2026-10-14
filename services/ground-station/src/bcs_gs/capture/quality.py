"""Capture quality metrics, evidence grade, baseline rule and sharpest-frame pick (addendum N11; spec section 9)."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from bcs_gs.api.models import CaptureQuality
from bcs_gs.camera.imagery import SiteRaster
from bcs_gs.core.config import QualityLimits, Thresholds

# A pixel is clipped when its grey level is within this many levels of 0 or 255.
CLIP_MARGIN = 2


def _grey(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(rgb[..., :3], np.uint8), cv2.COLOR_RGB2GRAY)


def sharpness(rgb: np.ndarray) -> float:
    """Variance of the Laplacian of the grey image."""
    return float(cv2.Laplacian(_grey(rgb), cv2.CV_64F).var())


def quality_metrics(rgb: np.ndarray, moving: bool, exposure_locked: bool) -> CaptureQuality:
    grey = _grey(rgb)
    clipped = np.count_nonzero((grey <= CLIP_MARGIN) | (grey >= 255 - CLIP_MARGIN))
    return CaptureQuality(
        sharpness=float(cv2.Laplacian(grey, cv2.CV_64F).var()),
        mean=float(grey.mean()),
        clipped_pct=float(clipped * 100.0 / grey.size),
        motion=bool(moving),
        exposure_locked=bool(exposure_locked),
    )


def _limits(cfg: Thresholds | QualityLimits | None) -> QualityLimits:
    if cfg is None:
        from bcs_gs.reality.fallback import default_thresholds  # config/thresholds.yaml, read once

        return default_thresholds().quality
    return cfg.quality if isinstance(cfg, Thresholds) else cfg


def is_evidence_grade(q: CaptureQuality, limits: Thresholds | QualityLimits | None = None) -> bool:
    """N11: sharpness >= 60, mean 40-220, clipped <= 5 %, no motion and exposure locked."""
    lim = _limits(limits)
    return (
        q.sharpness >= lim.sharpness_min
        and lim.brightness_min <= q.mean <= lim.brightness_max
        and q.clipped_pct <= lim.clipped_max_pct
        and not q.motion
        and q.exposure_locked
    )


def should_become_baseline(evidence_grade: bool, has_baseline: bool) -> bool:
    """Spec section 9: the first evidence-grade capture after a calibration becomes the baseline."""
    return evidence_grade and not has_baseline


def pick_sharpest(rasters: Sequence[SiteRaster]) -> SiteRaster:
    """The raster with the highest Laplacian variance (callers pass the last five, oldest first)."""
    if not rasters:
        raise ValueError("pick_sharpest needs at least one raster")
    return max(reversed(rasters), key=lambda r: sharpness(r.image))  # ties: the newest
