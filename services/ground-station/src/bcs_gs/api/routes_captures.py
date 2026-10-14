"""Capture routes (addendum I2). Built in M2. Fixed paths come before ``{capture_id}``."""

from __future__ import annotations

from typing import Any, Literal

from bcs_protocol.timefmt import from_iso, to_iso
from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.api.state import Services
from bcs_gs.capture import CaptureNotFound, to_capture

router = APIRouter()

COMPARE_URL = "/api/v1/media/compare/{a}/{b}/change.png"


def _svc(request: Request) -> Services:
    return request.app.state.services


def _iso_param(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return to_iso(from_iso(value))
    except ValueError:
        raise ApiError("validation_error", 422, f"Invalid timestamp for {name!r}: {value!r}") from None


def _summary(row: dict[str, Any]) -> m.CaptureSummary:
    cap = to_capture(row, [])
    return m.CaptureSummary.model_validate(cap.model_dump(include=set(m.CaptureSummary.model_fields)))


def _get(svc: Services, capture_id: str) -> m.Capture:
    cap = svc.capture.get(capture_id)
    if cap is None:
        raise CaptureNotFound(capture_id)
    return cap


@router.get("/captures", response_model=list[m.CaptureSummary], summary="List captures, newest first")
async def list_captures(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    trigger: Literal["interval", "change", "manual"] | None = Query(None),
    evidence_grade: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    where: list[str] = []
    params: list[Any] = []
    for clause, value in (
        ("taken_at >= ?", _iso_param("from", from_)),
        ("taken_at <= ?", _iso_param("to", to)),
    ):
        if value is not None:
            where.append(clause)
            params.append(value)
    if trigger is not None:
        where.append("trigger = ?")
        params.append(trigger)
    if evidence_grade is not None:
        where.append("evidence_grade = ?")
        params.append(1 if evidence_grade else 0)
    sql = "SELECT * FROM captures"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY taken_at DESC, id DESC LIMIT ?"
    rows = _svc(request).repo.query(sql, (*params, limit), table="captures")
    return [_summary(r) for r in rows]


@router.get("/captures/latest", response_model=m.Capture, summary="Latest capture")
async def latest_capture(request: Request):
    svc = _svc(request)
    rows = svc.repo.query("SELECT id FROM captures ORDER BY taken_at DESC, id DESC LIMIT 1", table="captures")
    if not rows:
        raise ApiError("not_found", 404, "There are no captures yet.")
    return _get(svc, rows[0]["id"])


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


@router.get("/captures/compare", response_model=m.CaptureComparison, summary="Compare two captures (b - a)")
async def compare_captures(request: Request, a: str = Query(...), b: str = Query(...)):
    svc = _svc(request)
    ca, cb = _get(svc, a), _get(svc, b)
    by_zone = {z.zone_id: z for z in ca.zone_metrics}
    zones = []
    for zb in cb.zone_metrics:
        za = by_zone.get(zb.zone_id)
        if za is None:
            continue
        zones.append(
            m.ComparisonZone(
                zone_id=zb.zone_id,
                canopy_pp=zb.canopy_pct - za.canopy_pct,
                vari=_delta(za.vari_mean, zb.vari_mean),
                dieback_pp=zb.dieback_pct - za.dieback_pct,
                new_growth_pp=zb.new_growth_pct - za.new_growth_pct,
            )
        )
    return m.CaptureComparison(a=a, b=b, change_url=COMPARE_URL.format(a=a, b=b), zones=zones)


@router.get("/captures/{capture_id}", response_model=m.Capture, summary="Get a capture")
async def get_capture(request: Request, capture_id: str):
    return _get(_svc(request), capture_id)


@router.post("/captures", response_model=m.Capture, status_code=201, summary="Take a capture now")
async def create_capture(request: Request):
    return await _svc(request).capture.capture_now("manual")
