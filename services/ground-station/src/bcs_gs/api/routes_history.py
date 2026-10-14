"""History routes (addendum I2)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from bcs_gs.api import models as m

router = APIRouter()


@router.get("/history", response_model=m.History, summary="Get history")
async def get_history(request: Request):
    """The latest synthetic generation (always labelled) plus real capture points. Before the first
    baseline: no series."""
    return await asyncio.to_thread(request.app.state.services.history.latest)


@router.post(
    "/history/regenerate",
    response_model=m.RequestAccepted,
    status_code=202,
    summary="Regenerate history",
)
async def regenerate_history(request: Request):
    """A new generation in the background (`history.updated` when done); 409 without a baseline."""
    return m.RequestAccepted(request_id=await request.app.state.services.history.regenerate())
