"""Commissioning and coverage routes (addendum I2). Built in M3."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.nodes.commissioning import ConfirmationRequired

router = APIRouter()


@router.get("/commissioning", response_model=m.CommissioningRun, summary="Get commissioning (M3)")
async def get_commissioning(request: Request):
    run = await asyncio.to_thread(request.app.state.services.commissioning.latest)
    if run is None:
        raise ApiError("not_found", 404, "No commissioning run yet.")
    return run


@router.post("/commissioning", response_model=m.CommissioningRun, summary="Run commissioning (M3)")
async def run_commissioning(request: Request, body: m.Confirm | None = None):
    try:
        return await request.app.state.services.commissioning.run(bool(body and body.confirm))
    except ConfirmationRequired as exc:
        raise ApiError("confirmation_required", 409, str(exc)) from None


@router.get("/coverage", response_model=m.Coverage, summary="Get coverage (M3)")
async def get_coverage(request: Request):
    """Per-zone WQ/SP coverage plus the gaps for flagged (or High/Critical) uncovered zones (§15)."""
    return await asyncio.to_thread(request.app.state.services.tasking.coverage_now)
