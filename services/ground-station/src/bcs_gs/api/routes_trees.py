"""Tree point routes (addendum I2)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError

router = APIRouter()


@router.get("/trees", response_model=m.TreePoints, summary="Get trees")
async def get_trees(request: Request):
    """The latest tree points; 404 before any have been located."""
    points = await asyncio.to_thread(request.app.state.services.trees.latest)
    if points is None:
        raise ApiError("not_found", 404, "No tree points yet.")
    return points


@router.post("/trees/locate", response_model=m.RequestAccepted, status_code=202, summary="Locate trees")
async def locate_trees(request: Request):
    """Locate trees in the latest capture with a class map, in the background (`trees.updated`);
    409 when there is none."""
    return m.RequestAccepted(request_id=await request.app.state.services.trees.locate())
