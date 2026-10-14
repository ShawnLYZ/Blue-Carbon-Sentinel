"""Media routes (addendum I2, H5). Captures, compare and live in M2; futures and illustrations in M5.

Capture files are immutable once written, so they are served with a one-year immutable cache.
The change map is derived from the two stored ``ndvi.png`` files and cached under
``var/media/cache/`` (outside every synced bucket). The live JPEG is the latest real site raster;
when there is none the route answers 404 and never substitutes an image."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from bcs_gs.api.errors import ApiError
from bcs_gs.api.state import Services
from bcs_gs.capture.artefacts import BUCKET, CONTENT_TYPES
from bcs_gs.futures.renderer import BUCKET as FUTURES_BUCKET
from bcs_gs.futures.renderer import CONTENT_TYPES as FUTURE_CONTENT_TYPES
from bcs_gs.futures.renderer import SCENARIOS as FUTURE_SCENARIOS
from bcs_gs.futures.renderer import future_key

router = APIRouter()

IMMUTABLE = {"Cache-Control": "max-age=31536000, immutable"}
LIVE_JPEG_QUALITY = 85
CHANGE_FULL_SCALE = 0.5  # |VARI difference| that maps to the top of the colour map


def _svc(request: Request) -> Services:
    return request.app.state.services


def _not_found(message: str, reason: str | None = None) -> ApiError:
    """404; ``reason`` is machine-readable in ``error.details.reason`` (clients must not parse ``message``)."""
    return ApiError("not_found", 404, message, {"reason": reason} if reason else None)


def _media_path(svc: Services, capture_id: str, kind: str) -> Path:
    if kind not in CONTENT_TYPES:
        raise _not_found(f"Unknown capture media kind {kind!r}.")
    row = svc.repo.get("captures", {"id": capture_id})
    if row is None:
        raise _not_found(f"Capture {capture_id} not found.")
    key = (row.get("media") or {}).get(kind)
    if not key:
        raise _not_found(f"Capture {capture_id} has no {kind} file.", "no_media")
    path = svc.media.path(BUCKET, key)
    if not path.is_file():
        raise _not_found(f"The {kind} file of capture {capture_id} is no longer stored locally.")
    return path


@router.get(
    "/media/captures/{capture_id}/{kind}",
    response_class=Response,
    responses={"200": {"content": {"image/*": {}}}},
    summary="Capture media: image, height, classes or ndvi",
)
async def capture_media(request: Request, capture_id: str, kind: str):
    path = _media_path(_svc(request), capture_id, kind)
    return FileResponse(path, media_type=CONTENT_TYPES[kind], headers=IMMUTABLE)


def _read_vari(path: Path) -> np.ndarray:
    u16 = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if u16 is None or u16.ndim != 2:
        raise _not_found(f"{path.name} could not be read as a 16-bit VARI map.")
    return u16.astype(np.float32) / 65535.0 * 2.0 - 1.0  # 0-65535 -> VARI [-1, 1] (H5)


def change_map_png(ndvi_a: Path, ndvi_b: Path) -> bytes:
    """|VARI_a - VARI_b| colour-mapped (inferno), as PNG bytes."""
    va, vb = _read_vari(ndvi_a), _read_vari(ndvi_b)
    if vb.shape != va.shape:
        vb = cv2.resize(vb, (va.shape[1], va.shape[0]), interpolation=cv2.INTER_AREA)
    diff = np.abs(va - vb)
    scaled = np.clip(diff / CHANGE_FULL_SCALE * 255.0, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", cv2.applyColorMap(scaled, cv2.COLORMAP_INFERNO))
    if not ok:
        raise RuntimeError("could not encode the change map")
    return buf.tobytes()


def _change_map(svc: Services, a: str, b: str) -> Path:
    ndvi_a, ndvi_b = _media_path(svc, a, "ndvi"), _media_path(svc, b, "ndvi")
    cache = svc.data_root / "var" / "media" / "cache" / "compare" / f"{a}_{b}.png"
    if cache.is_file():
        return cache
    data = change_map_png(ndvi_a, ndvi_b)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f"{cache.name}.{uuid4().hex}.tmp")  # unique: concurrent requests never collide
    try:
        tmp.write_bytes(data)
        try:
            tmp.replace(cache)
        except OSError:
            if not cache.is_file():  # a concurrent request that won the rename is success too
                raise
    finally:
        tmp.unlink(missing_ok=True)
    return cache


@router.get(
    "/media/compare/{a}/{b}/change.png",
    response_class=Response,
    responses={"200": {"content": {"image/png": {}}}},
    summary="Change map between two captures (cached)",
)
async def compare_media(request: Request, a: str, b: str):
    path = await asyncio.to_thread(_change_map, _svc(request), a, b)
    return FileResponse(path, media_type="image/png", headers=IMMUTABLE)


@router.get(
    "/media/live/latest.jpg",
    response_class=Response,
    responses={"200": {"content": {"image/jpeg": {}}}},
    summary="Latest site raster",
)
async def live_latest(request: Request):
    frame = _svc(request).reality.latest()
    if frame is None:
        raise _not_found("No live site raster yet.")
    bgr = cv2.cvtColor(np.ascontiguousarray(frame.raster_rgb[..., :3], np.uint8), cv2.COLOR_RGB2BGR)
    ok, buf = await asyncio.to_thread(
        cv2.imencode, ".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, LIVE_JPEG_QUALITY]
    )
    if not ok:
        raise ApiError("internal_error", 500, "Could not encode the live raster.")
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get(
    "/media/futures/{forecast_id}/{scenario}/{year}/{kind}",
    response_class=Response,
    responses={"200": {"content": {"image/*": {}}}},
    summary="Future texture or height of a forecast year and scenario",
)
async def future_media(request: Request, forecast_id: str, scenario: str, year: int, kind: str):
    if kind not in FUTURE_CONTENT_TYPES or scenario not in FUTURE_SCENARIOS:
        raise _not_found(f"Unknown future media {scenario}/{kind}.")
    try:
        path = _svc(request).media.path(FUTURES_BUCKET, future_key(forecast_id, scenario, year, kind))
    except ValueError:
        raise _not_found("Invalid future media key.") from None
    if not path.is_file():  # never a substitute image
        await _svc(request).futures.ensure(forecast_id)  # R22b: a ready forecast without files renders now
        raise _not_found(f"Forecast {forecast_id} has no {kind} for {scenario} {year}.", "no_media")
    return FileResponse(path, media_type=FUTURE_CONTENT_TYPES[kind], headers=IMMUTABLE)


@router.get(
    "/media/illustrations/{illustration_id}.jpg",
    response_class=Response,
    responses={"200": {"content": {"image/*": {}}}},
    summary="Illustration media (M5)",
)
async def illustration_media(request: Request, illustration_id: str):
    svc = _svc(request)
    row = await asyncio.to_thread(svc.repo.get, "illustrations", {"id": illustration_id})
    if row is None or row["status"] != "ready" or not row.get("media_key"):
        raise _not_found(f"Illustration {illustration_id} is not ready.", "no_media")
    try:
        path = svc.media.path(FUTURES_BUCKET, row["media_key"])
    except ValueError:
        raise _not_found("Invalid illustration media key.") from None
    if not path.is_file():  # never a substitute image
        raise _not_found(f"Illustration {illustration_id} is no longer stored locally.", "no_media")
    return FileResponse(path, media_type="image/jpeg", headers=IMMUTABLE)
