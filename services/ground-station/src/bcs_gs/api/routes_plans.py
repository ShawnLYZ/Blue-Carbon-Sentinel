"""Restoration plan routes (addendum I2). Built in M5 (ruling R8)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError

router = APIRouter()


def _plans(request: Request):
    return request.app.state.services.plans


@router.post("/plans/propose", response_model=m.RequestAccepted, status_code=202, summary="Propose plan (M5)")
async def propose_plan(request: Request, body: m.PlanProposeRequest | None = None):
    """The RestorationPlanner drafts version 1 in the background (`plan.updated` when stored). The request
    ID is the new plan's ID. Without `zone_ids`: every zone."""
    return m.RequestAccepted(request_id=await _plans(request).propose(body.zone_ids if body else None))


@router.get("/plans", response_model=list[m.PlanSummary], summary="List plans (M5)")
async def list_plans(request: Request):
    """The latest version of each plan, newest first."""
    return await asyncio.to_thread(_plans(request).list)


@router.get("/plans/{plan_id}", response_model=m.PlanVersion, summary="Get plan (M5)")
async def get_plan(request: Request, plan_id: str, version: int | None = Query(None)):
    return await asyncio.to_thread(_plans(request).get, plan_id, version)


@router.put("/plans/{plan_id}", response_model=m.PlanVersion, summary="Update plan (M5)")
async def update_plan(request: Request, plan_id: str, body: m.PlanUpdateRequest | None = None):
    """Stores a new draft version. 422 when an item breaks the catalogue (the plan is unchanged); a
    species switch comes back in `warnings`."""
    if body is None:
        raise ApiError("validation_error", 422, "The plan items are required.")
    return await _plans(request).update(plan_id, body.items)


@router.post("/plans/{plan_id}/apply", response_model=m.PlanApplied, summary="Apply plan (M5)")
async def apply_plan(request: Request, plan_id: str, body: m.PlanApplyRequest | None = None):
    """Applies a version (default: the latest) and starts its forecast. 409 without an evidence-grade
    capture or a baseline."""
    plan, forecast_id = await _plans(request).apply(plan_id, body.version if body else None)
    return m.PlanApplied(plan=plan, forecast_id=forecast_id)
