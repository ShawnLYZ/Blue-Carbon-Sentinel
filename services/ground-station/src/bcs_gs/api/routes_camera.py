"""Camera routes (addendum I2, L5). Built in M2.

Desired settings and the exposure lock are persisted even while the camera is offline; the
CameraLink re-applies them on every reconnect. ``apply``/``set_lock`` may POST to the camera
(blocking httpx), so they run in a worker thread."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response

from bcs_gs.api import models as m
from bcs_gs.api.state import Services

router = APIRouter()


def _svc(request: Request) -> Services:
    return request.app.state.services


@router.get("/camera/status", response_model=m.CameraStatus, summary="Camera status")
async def camera_status(request: Request):
    return _svc(request).camera.status()


@router.patch("/camera/settings", response_model=m.CameraStatus, summary="Change desired camera settings")
async def camera_settings(request: Request, body: m.CameraSettingsPatch | None = None):
    camera = _svc(request).camera
    changes = body.model_dump(exclude_none=True) if body else {}
    desired = m.CameraSettings.model_validate({**camera.desired.model_dump(), **changes})
    await asyncio.to_thread(camera.apply, desired)
    return camera.status()


@router.post(
    "/camera/lock", response_model=m.CameraStatus, summary="Lock or unlock exposure and white balance"
)
async def camera_lock(request: Request, body: m.LockRequest):
    camera = _svc(request).camera
    await asyncio.to_thread(camera.set_lock, body.locked)
    return camera.status()


@router.post(
    "/camera/reconnect", status_code=202, response_class=Response, summary="Reconnect the camera stream"
)
async def camera_reconnect(request: Request):
    _svc(request).camera.reconnect()
    return Response(status_code=202)
