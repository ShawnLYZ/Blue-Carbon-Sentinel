"""Capture pipeline: triggers, quality, artefacts and the CaptureService (spec section 9)."""

from bcs_gs.capture.artefacts import media_keys, write_artefacts
from bcs_gs.capture.payloads import capture_events, to_capture
from bcs_gs.capture.quality import is_evidence_grade, pick_sharpest, quality_metrics, should_become_baseline
from bcs_gs.capture.service import BaselineConflict, CameraOffline, CaptureNotFound, CaptureService
from bcs_gs.capture.triggers import ChangeTrigger, cloud_eligible, frame_difference

__all__ = [
    "BaselineConflict",
    "CameraOffline",
    "CaptureNotFound",
    "CaptureService",
    "ChangeTrigger",
    "capture_events",
    "cloud_eligible",
    "frame_difference",
    "is_evidence_grade",
    "media_keys",
    "pick_sharpest",
    "quality_metrics",
    "should_become_baseline",
    "to_capture",
    "write_artefacts",
]
