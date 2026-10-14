"""Carbon summary route (addendum I2, M6)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from bcs_gs.api import models as m
from bcs_gs.api.routes_site import latest_zone_metrics
from bcs_gs.carbon import engine

router = APIRouter()


@router.get("/carbon/summary", response_model=m.CarbonSummary, summary="Carbon summary (M6)")
async def carbon_summary(request: Request):
    """Standing stock from each zone's current canopy; projected and verified summed over the ledger."""
    svc = request.app.state.services

    def build() -> m.CarbonSummary:
        latest = latest_zone_metrics(svc)
        canopy = {z.id: (latest[z.id].canopy_pct / 100.0 if z.id in latest else 0.0) for z in svc.site.zones()}
        return engine.summary(svc.repo, canopy)

    return await asyncio.to_thread(build)
