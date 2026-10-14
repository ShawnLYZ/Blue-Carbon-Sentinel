"""Calibration: camera pixels -> 512 x 512 north-up site raster (addendum F4)."""

from __future__ import annotations

import math
import threading
from typing import Any

import cv2
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.api.models import Calibration
from bcs_gs.core.clock import Clock
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.store.repo import Repo

RASTER = 512
_DST = np.array([(0, 0), (RASTER, 0), (RASTER, RASTER), (0, RASTER)], np.float32)


class CalibrationError(ValueError):
    """Raised with a short code as the message: non_convex, degenerate, bad_corners, bad_north_edge."""


def default_homography(w: int, h: int) -> np.ndarray:
    s = min(w, h)
    x0, y0 = (w - s) / 2, (h - s) / 2
    src = np.array([(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s)], np.float32)
    return cv2.getPerspectiveTransform(src, _DST).astype(np.float64)


def _area(pts: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True))) / 2


def normalise_corners(
    corners_px: list[tuple[float, float]],
    north_edge: int,
    *,
    frame_wh: tuple[int, int] | None = None,
) -> list[tuple[float, float]]:
    """Return the corners ordered NW, NE, SE, SW for the chosen north edge (corner k -> NW)."""
    if len(corners_px) != 4:
        raise CalibrationError("bad_corners")
    if north_edge not in (0, 1, 2, 3):
        raise CalibrationError("bad_north_edge")
    pts = [(float(x), float(y)) for x, y in corners_px]
    if not all(math.isfinite(v) for p in pts for v in p):
        raise CalibrationError("bad_corners")
    cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # y down: ascending angle is clockwise
    min_area = 0.01 * frame_wh[0] * frame_wh[1] if frame_wh else 1.0
    if _area(pts) < min_area:
        raise CalibrationError("degenerate")
    signs = []
    for i in range(4):
        (x0, y0), (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        signs.append((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1))
    if not (all(c > 0 for c in signs) or all(c < 0 for c in signs)):
        raise CalibrationError("non_convex")
    start = min(range(4), key=lambda i: (pts[i][0] + pts[i][1], pts[i][1]))
    pts = pts[start:] + pts[:start]
    return pts[north_edge:] + pts[:north_edge]


def four_corner_homography(corners_nw_ne_se_sw: list[tuple[float, float]]) -> np.ndarray:
    src = np.array(corners_nw_ne_se_sw, np.float32)
    return cv2.getPerspectiveTransform(src, _DST).astype(np.float64)


class CalibrationService:
    def __init__(
        self,
        repo: Repo,
        bus: EventBus,
        clock: Clock,
        *,
        frame_w: int = 800,
        frame_h: int = 600,
        seed_default: bool = True,
    ) -> None:
        """``seed_default=False`` leaves the default to the caller (the app installs it after hydration)."""
        self.repo = repo
        self.bus = bus
        self.clock = clock
        self._lock = threading.RLock()
        self._default_wh = (frame_w, frame_h)
        if seed_default:
            self.ensure_default()

    def ensure_default(self) -> None:
        """Install a default calibration when none is active (start-up, or after a test reset)."""
        w, h = self._default_wh
        with self._lock:
            if self._active_row() is None:
                self._swap(self._new_row("default", w, h, None, None, default_homography(w, h)))

    # -- queries ----------------------------------------------------------------------------
    def _active_row(self) -> dict[str, Any] | None:
        rows = self.repo.query("select * from calibrations where active = 1", (), table="calibrations")
        return rows[0] if rows else None

    def active(self) -> Calibration:
        row = self._active_row()
        if row is None:  # unreachable while the service owns the table
            raise CalibrationError("no_active")
        return Calibration(**row)

    # -- commands ---------------------------------------------------------------------------
    def _new_row(
        self,
        mode: str,
        frame_w: int,
        frame_h: int,
        corners: list[tuple[float, float]] | None,
        north_edge: int | None,
        h: np.ndarray,
    ) -> dict[str, Any]:
        return {
            "id": uuid7(),
            "created_at": to_iso(self.clock.now()),
            "mode": mode,
            "frame_w": frame_w,
            "frame_h": frame_h,
            "corners_px": [list(c) for c in corners] if corners else None,
            "north_edge": north_edge,
            "homography": [float(v) for v in h.reshape(9)],
            "active": True,
        }

    def _swap(self, new_row: dict[str, Any]) -> None:
        """Deactivate the old active row and insert the new one in ONE transaction."""
        old = self._active_row()
        with self.repo.transaction():
            if old is not None:
                self.repo.upsert("calibrations", {**old, "active": False})
            self.repo.insert("calibrations", new_row)

    def _install(self, row: dict[str, Any]) -> Calibration:
        self._swap(row)
        cal = Calibration(**row)
        self.bus.publish("calibration.updated", cal.model_dump(mode="json"))
        return cal

    def set_four_corner(
        self, corners: list[tuple[float, float]], north_edge: int, frame_w: int, frame_h: int
    ) -> Calibration:
        ordered = normalise_corners(corners, north_edge, frame_wh=(frame_w, frame_h))
        h = four_corner_homography(ordered)
        with self._lock:
            return self._install(self._new_row("four_corner", frame_w, frame_h, ordered, north_edge, h))

    def reset(self, frame_w: int, frame_h: int) -> Calibration:
        with self._lock:
            return self._install(
                self._new_row("default", frame_w, frame_h, None, None, default_homography(frame_w, frame_h))
            )

    # -- rectification ----------------------------------------------------------------------
    @staticmethod
    def rectify_with(h: np.ndarray, image_bgr: np.ndarray) -> np.ndarray:
        return cv2.warpPerspective(image_bgr, h, (RASTER, RASTER), flags=cv2.INTER_AREA)

    def rectify(self, image_bgr: np.ndarray) -> np.ndarray:
        cal = self.active()
        h = np.array(cal.homography, np.float64).reshape(3, 3)
        ih, iw = image_bgr.shape[:2]
        if (iw, ih) != (cal.frame_w, cal.frame_h):
            # the camera changed frame size: map new-frame pixels into the calibrated frame first
            h = h @ np.diag([cal.frame_w / iw, cal.frame_h / ih, 1.0])
        return self.rectify_with(h, image_bgr)
