"""Test-only routes (addendum I4). Mounted only when ``test_mode`` is on."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from bcs_protocol.timefmt import from_iso, to_iso
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.api.state import Services, cancel_background, reset_store
from bcs_gs.core.clock import ManualClock

log = logging.getLogger("bcs_gs.test")
router = APIRouter(prefix="/test", tags=["test"])


class AdvanceBody(BaseModel):
    seconds: float


class SetBody(BaseModel):
    at: str


class FailBody(BaseModel):
    failing: bool


class BurstBody(BaseModel):
    count: int = 1
    type: str = "test.burst"


class SeedCaptureBody(BaseModel):
    """Addendum I4: per-zone metric values (missing fields and zones take seed defaults)."""

    zone_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    evidence_grade: bool
    quality: dict[str, Any] | None = None
    trigger: Literal["interval", "change", "manual"] = "manual"


class ClockState(BaseModel):
    now: str


def _svc(request: Request) -> Services:
    return request.app.state.services


def _manual(svc: Services) -> ManualClock:
    if not isinstance(svc.clock, ManualClock):
        raise ApiError("conflict", 409, "The clock is not manual; start with --clock manual.")
    return svc.clock


@router.post("/clock/advance", response_model=ClockState, summary="Advance the manual clock")
async def clock_advance(request: Request, body: AdvanceBody):
    clock = _manual(_svc(request))
    clock.advance(body.seconds)
    return ClockState(now=to_iso(clock.now()))


@router.post("/clock/set", response_model=ClockState, summary="Set the manual clock")
async def clock_set(request: Request, body: SetBody):
    clock = _manual(_svc(request))
    try:
        at: datetime = from_iso(body.at)
    except ValueError as exc:
        raise ApiError("validation_error", 422, f"Invalid timestamp: {exc}") from None
    clock.set(at)
    return ClockState(now=to_iso(clock.now()))


@router.post("/cloud/fail", summary="Switch the fake cloud target to failing or healthy")
async def cloud_fail(request: Request, body: FailBody):
    cloud = _svc(request).cloud
    if not hasattr(cloud, "failing"):
        raise ApiError("conflict", 409, "The cloud target is not the fake target; start with --cloud fake.")
    cloud.failing = body.failing  # type: ignore[attr-defined]
    return {"failing": body.failing}


@router.post("/events/burst", summary="Publish N events at once (slow-client checks)")
async def events_burst(request: Request, body: BurstBody):
    bus = _svc(request).bus
    for i in range(body.count):  # no await: subscribers cannot drain while the burst runs
        bus.publish(body.type, {"i": i})
    return {"published": body.count}


@router.post("/reset", summary="Clear the store between browser checks")
async def reset(request: Request):
    svc = _svc(request)
    await cancel_background(svc)  # ruling R30: no in-flight work outlives the reset
    try:
        reset_store(svc)
    finally:
        if svc.eligibility is not None:  # stopped by cancel_background; the cleared chain needs no check
            svc.eligibility.start()
    if svc.settings.auto_commission:  # the e2e stack expects its 8 nodes after a reset (off-loop work)
        try:
            await svc.commissioning.run(confirm=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("auto-commissioning after reset failed: %s: %s", type(exc).__name__, exc)
    return {"reset": True}


@router.post(
    "/seed/capture", response_model=m.Capture, status_code=201, summary="Seed a capture from numbers"
)
async def seed_capture(request: Request, body: SeedCaptureBody):
    """Creates a capture row from numbers (no media) and runs everything downstream (flags, events)."""
    try:
        return await _svc(request).capture.seed_capture(
            body.zone_metrics, body.evidence_grade, body.quality, body.trigger
        )
    except ValueError as exc:  # unknown zone or metric field, or invalid values
        raise ApiError("validation_error", 422, str(exc)) from None
