"""Calibration and baseline routes (addendum I2, F4). Built in M2.

Corner validation (count, north edge, convexity) needs no camera, so a bad request is a 422 even
offline. Fitting four corners and serving the corner-picking frame need a real camera frame:
without one they answer ``409 camera_offline``. Reset needs none (it reuses the active size)."""

from __future__ import annotations

import asyncio

import cv2
from fastapi import APIRouter, Request, Response

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.api.state import Services
from bcs_gs.site.calibration import CalibrationError, normalise_corners

router = APIRouter()

FRAME_JPEG_QUALITY = 90
_MESSAGES = {
    "non_convex": "The four corners do not form a convex quadrilateral.",
    "degenerate": "The four corners enclose too small an area.",
    "bad_corners": "Exactly four finite corner points are required.",
    "bad_north_edge": "north_edge must be 0, 1, 2 or 3.",
}


def _svc(request: Request) -> Services:
    return request.app.state.services


def _calibration_error(exc: CalibrationError) -> ApiError:
    code = str(exc)
    return ApiError(code, 422, _MESSAGES.get(code, "Invalid calibration."))


def _no_frame() -> ApiError:
    return ApiError("camera_offline", 409, "The camera is offline; no camera frame is available.")


def _result(cal: m.Calibration) -> m.CalibrationResult:
    return m.CalibrationResult(calibration=cal, recommend=m.CalibrationRecommend())


@router.get("/calibration", response_model=m.Calibration, summary="Active calibration")
async def get_calibration(request: Request):
    return _svc(request).calibration.active()


@router.get(
    "/calibration/frame.jpg",
    response_class=Response,
    responses={"200": {"content": {"image/jpeg": {}}}},
    summary="Latest raw camera frame (for corner picking)",
)
async def calibration_frame(request: Request):
    frame = _svc(request).camera.latest()
    if frame is None:
        raise _no_frame()
    ok, buf = await asyncio.to_thread(
        cv2.imencode, ".jpg", frame.image_bgr, [cv2.IMWRITE_JPEG_QUALITY, FRAME_JPEG_QUALITY]
    )
    if not ok:
        raise ApiError("internal_error", 500, "Could not encode the camera frame.")
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post(
    "/calibration/four-corner", response_model=m.CalibrationResult, summary="Four-corner calibration"
)
async def four_corner(request: Request, body: m.FourCornerRequest):
    svc = _svc(request)
    try:
        normalise_corners(list(body.corners_px), body.north_edge)  # shape and convexity: no camera needed
    except CalibrationError as exc:
        raise _calibration_error(exc) from None
    frame = svc.camera.latest()
    if frame is None:
        raise _no_frame()
    h, w = frame.image_bgr.shape[:2]
    try:
        cal = await asyncio.to_thread(
            svc.calibration.set_four_corner, list(body.corners_px), body.north_edge, w, h
        )
    except CalibrationError as exc:
        raise _calibration_error(exc) from None
    return _result(cal)


@router.post(
    "/calibration/reset", response_model=m.CalibrationResult, summary="Reset to the default calibration"
)
async def reset_calibration(request: Request):
    svc = _svc(request)
    frame = svc.camera.latest()
    if frame is not None:
        h, w = frame.image_bgr.shape[:2]
    else:
        active = svc.calibration.active()
        w, h = active.frame_w, active.frame_h
    return _result(await asyncio.to_thread(svc.calibration.reset, w, h))


@router.post("/baseline", response_model=m.Capture, summary="Set the baseline capture")
async def set_baseline(request: Request, body: m.BaselineRequest | None = None):
    return await _svc(request).capture.set_baseline(body.capture_id if body else None)
