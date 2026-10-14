"""Zone assessment routes (addendum I2). Built in M4."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError

router = APIRouter()


def _fusion(request: Request):
    return request.app.state.services.fusion


def _zone(request: Request, zone_id: str) -> str:
    if zone_id not in _fusion(request).grid.zone_ids():
        raise ApiError("not_found", 404, f"No zone {zone_id}.")
    return zone_id


@router.get(
    "/zones/{zone_id}/assessments", response_model=list[m.Assessment], summary="Zone assessments (M4)"
)
async def zone_assessments(request: Request, zone_id: str, limit: int = Query(100, ge=1, le=1000)):
    """Newest first. A zone without any measured stressor has none (addendum N3.5)."""
    _zone(request, zone_id)
    return await asyncio.to_thread(_fusion(request).list_assessments, zone_id, limit)


@router.post(
    "/zones/{zone_id}/analyze", response_model=m.RequestAccepted, status_code=202, summary="Analyze zone (M4)"
)
async def analyze_zone(request: Request, zone_id: str):
    """Operator AI assessment in the background; 429 within 30 s of the zone's previous request."""
    _zone(request, zone_id)
    return m.RequestAccepted(request_id=await _fusion(request).request_analysis(zone_id))
