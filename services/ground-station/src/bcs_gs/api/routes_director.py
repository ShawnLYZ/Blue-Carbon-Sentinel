"""Demo Director routes (addendum I2). The state machine is bcs_gs.director.Director."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.director.machine import Director, DirectorInactive

router = APIRouter()


def _director(request: Request) -> Director:
    return request.app.state.services.director


@router.get("/director", response_model=m.DirectorState, summary="Get director")
async def get_director(request: Request):
    return _director(request).state()


@router.post("/director/start", response_model=m.DirectorState, summary="Start director")
async def start_director(request: Request, body: m.DirectorStart | None = None):
    """Reset every step and begin at the first one (the early-warning step first when asked)."""
    return _director(request).start((body or m.DirectorStart(branch="main")).branch)


@router.post("/director/skip", response_model=m.DirectorState, summary="Skip step")
async def skip_step(request: Request):
    try:
        return _director(request).skip()
    except DirectorInactive as exc:
        raise ApiError("conflict", 409, str(exc)) from None


@router.post("/director/retry", response_model=m.DirectorState, summary="Retry step")
async def retry_step(request: Request):
    try:
        return _director(request).retry()
    except DirectorInactive as exc:
        raise ApiError("conflict", 409, str(exc)) from None


@router.post("/director/stop", response_model=m.DirectorState, summary="Stop director")
async def stop_director(request: Request):
    return _director(request).stop()
