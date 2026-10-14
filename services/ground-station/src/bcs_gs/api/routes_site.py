"""Site and zone routes (addendum I2). ``/site`` and ``/zones`` are M1; zone detail and the zone
metrics enrichment arrive in M2 (assessments, coverage, carbon and trees in M3-M6)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.api.state import Services

router = APIRouter()

HISTORY_DEFAULT = 200
# Both queries walk the captures_taken_at index newest-first and probe the zone_metrics primary key
# (capture_id, zone_id), so they stop after the first match (latest) or ``limit`` matches (history)
# instead of sorting every capture of the zone.
_LATEST_ID_SQL = """
SELECT c.id FROM captures c INDEXED BY captures_taken_at
WHERE EXISTS (SELECT 1 FROM zone_metrics zm WHERE zm.capture_id = c.id AND zm.zone_id = ?)
ORDER BY c.taken_at DESC, c.id DESC LIMIT 1
"""
_HISTORY_SQL = """
SELECT zm.*, c.taken_at AS taken_at FROM captures c INDEXED BY captures_taken_at
JOIN zone_metrics zm ON zm.capture_id = c.id AND zm.zone_id = ?
ORDER BY c.taken_at DESC, c.id DESC LIMIT ?
"""


def _svc(request: Request) -> Services:
    return request.app.state.services


def _metrics(row: dict[str, Any]) -> m.ZoneMetrics:
    return m.ZoneMetrics.model_validate({k: v for k, v in row.items() if k not in ("capture_id", "taken_at")})


def latest_zone_metrics(svc: Services) -> dict[str, m.ZoneMetrics]:
    """The zone_metrics row of each zone's latest capture (blocking: call off the event loop)."""
    out: dict[str, m.ZoneMetrics] = {}
    for z in svc.site.zones():
        ids = svc.repo.query(_LATEST_ID_SQL, (z.id,))
        if ids:
            row = svc.repo.get("zone_metrics", {"capture_id": ids[0]["id"], "zone_id": z.id})
            if row is not None:
                out[z.id] = _metrics(row)
    return out


def zone_history(svc: Services, zone_id: str, limit: int) -> list[dict[str, Any]]:
    """The zone's last ``limit`` metrics rows with ``taken_at``, chronological (blocking)."""
    rows = svc.repo.query(_HISTORY_SQL, (zone_id, limit), table="zone_metrics")
    rows.reverse()
    return rows


@router.get("/site", response_model=m.Site, summary="Site with zones and planned sites")
async def get_site(request: Request):
    return _svc(request).site.site()


@router.get("/zones", response_model=list[m.ZoneSummary], summary="Zone summaries")
async def list_zones(request: Request):
    """Geometry and the latest zone metrics; assessments, coverage and carbon arrive in M3-M6."""
    svc = _svc(request)
    latest = await asyncio.to_thread(latest_zone_metrics, svc)
    return [m.ZoneSummary(zone=z, metrics=latest.get(z.id)) for z in svc.site.zones()]


@router.get("/zones/{zone_id}", response_model=m.ZoneDetail, summary="Zone detail")
async def get_zone(
    request: Request,
    zone_id: str,
    limit: int = Query(HISTORY_DEFAULT, ge=1, le=1000, description="Most recent history points to return"),
):
    svc = _svc(request)
    zone = next((z for z in svc.site.zones() if z.id == zone_id), None)
    if zone is None:
        raise ApiError("not_found", 404, f"Zone {zone_id} not found.")
    rows = await asyncio.to_thread(zone_history, svc, zone_id, limit)
    history = [
        m.ZoneMetricsAt.model_validate({k: v for k, v in r.items() if k != "capture_id"}) for r in rows
    ]
    return m.ZoneDetail(
        zone=zone,
        metrics=_metrics(rows[-1]) if rows else None,
        last_capture_at=rows[-1]["taken_at"] if rows else None,
        metrics_history=history,
        covering_nodes=[],
        stressors=None,
    )
