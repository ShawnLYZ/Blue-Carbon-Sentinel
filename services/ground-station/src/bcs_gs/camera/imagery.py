"""Imagery seam (addendum M): camera frames become north-up 512 x 512 RGB site rasters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import cv2
import numpy as np

from bcs_gs.api.models import Calibration

from .link import Frame

SOURCE_ID = "esp32cam"


@dataclass(frozen=True)
class SiteRaster:
    image: np.ndarray  # 512x512xC uint8, north-up; C = len(bands)
    bands: tuple[str, ...]  # ("R","G","B") today; ("B2","B3","B4","B8") for Sentinel-2
    captured_at: datetime  # UTC
    source_id: str  # "esp32cam"
    seq: int
    calibration_id: str | None


class ImagerySource(Protocol):
    source_id: str

    def online(self) -> bool: ...
    def latest(self) -> SiteRaster | None: ...
    def recent(self, n: int) -> list[SiteRaster]: ...  # sharpest-of-last-5 selection
    def subscribe(self) -> AsyncIterator[SiteRaster]: ...


def to_site_raster(
    frame: Frame, calibration: Calibration, rectify: Callable[[np.ndarray], np.ndarray]
) -> SiteRaster:
    rgb = cv2.cvtColor(rectify(frame.image_bgr), cv2.COLOR_BGR2RGB)
    return SiteRaster(
        image=np.ascontiguousarray(rgb, dtype=np.uint8).copy(),
        bands=("R", "G", "B"),
        captured_at=frame.captured_at,
        source_id=SOURCE_ID,
        seq=frame.seq,
        calibration_id=calibration.id,
    )


class CameraImagerySource:
    source_id = SOURCE_ID

    def __init__(self, camera: Any, calibration: Any) -> None:
        self.camera = camera
        self.calibration = calibration

    def _raster(self, frame: Frame) -> SiteRaster:
        return to_site_raster(frame, self.calibration.active(), self.calibration.rectify)

    def online(self) -> bool:
        return bool(self.camera.status().online)

    def latest(self) -> SiteRaster | None:
        frame = self.camera.latest()
        return None if frame is None else self._raster(frame)

    def recent(self, n: int) -> list[SiteRaster]:
        return [self._raster(f) for f in self.camera.recent(n)]

    async def subscribe(self) -> AsyncIterator[SiteRaster]:
        async for frame in self.camera.subscribe():
            yield self._raster(frame)
