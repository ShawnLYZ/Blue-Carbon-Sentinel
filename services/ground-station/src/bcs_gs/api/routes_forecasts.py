"""Forecast routes (addendum I2). Built in M5. ``latest`` comes before ``{forecast_id}``."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from bcs_gs.api import models as m
from bcs_gs.futures.jobs import illustration_url

router = APIRouter()


def _forecasts(request: Request):
    return request.app.state.services.forecasts


@router.post("/forecasts", response_model=m.ForecastAccepted, status_code=202, summary="Run forecast (M5)")
async def run_forecast(request: Request, body: m.ForecastRequest | None = None):
    """Runs in the background (`forecast.ready` when done). With `plan_id`: that plan's applied version,
    else its latest; without: the latest applied plan, else no plan. 409 without an evidence-grade
    capture or a baseline."""
    svc = _forecasts(request)
    version_id = await asyncio.to_thread(svc.resolve_plan, body.plan_id if body else None)
    return m.ForecastAccepted(forecast_id=await svc.start(version_id))


@router.get("/forecasts/latest", response_model=m.Forecast, summary="Latest forecast (M5)")
async def latest_forecast(request: Request):
    return await asyncio.to_thread(_forecasts(request).latest)


@router.get("/forecasts/{forecast_id}", response_model=m.Forecast, summary="Get forecast (M5)")
async def get_forecast(request: Request, forecast_id: str):
    return await asyncio.to_thread(_forecasts(request).get, forecast_id)


@router.get(
    "/forecasts/{forecast_id}/illustrations",
    response_model=list[m.Illustration],
    summary="Forecast illustrations (M5)",
)
async def forecast_illustrations(request: Request, forecast_id: str):
    """The 4 keyframe illustrations; ``url`` only when ready. 404 when the forecast does not exist."""
    svc = request.app.state.services
    await asyncio.to_thread(svc.forecasts.get, forecast_id)  # raises 404

    def rows():
        return svc.repo.query(
            "SELECT * FROM illustrations WHERE forecast_id = ? ORDER BY scenario, year",
            (forecast_id,), table="illustrations",
        )

    return [
        m.Illustration(
            id=r["id"], forecast_id=r["forecast_id"], year=int(r["year"]), scenario=r["scenario"],
            status=r["status"], url=illustration_url(r["id"]) if r["status"] == "ready" else None,
            provider=r["provider"], model=r["model"], error=r["error"],
        )
        for r in await asyncio.to_thread(rows)
    ]
