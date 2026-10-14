"""Alert routes (addendum I2). Built in M4."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m

router = APIRouter()


@router.get("/alerts", response_model=list[m.Alert], summary="List alerts")
async def list_alerts(
    request: Request, unacknowledged: bool = Query(False), limit: int = Query(100, ge=1, le=1000)
):
    """Newest first."""
    return await asyncio.to_thread(request.app.state.services.alerts.list, unacknowledged, limit)


@router.post("/alerts/{alert_id}/ack", response_model=m.Alert, summary="Acknowledge an alert")
async def ack_alert(request: Request, alert_id: str):
    """Idempotent: acknowledging again returns the alert without a new event. 404 for an unknown id."""
    return request.app.state.services.alerts.ack(alert_id)
