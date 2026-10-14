"""System routes (addendum I2, M1): status, preflight, public config and UI settings."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bcs_gs.api import models as m
from bcs_gs.api.state import Services, load_ui_settings, patch_ui_settings

router = APIRouter()


def _svc(request: Request) -> Services:
    return request.app.state.services


@router.get("/system/status", response_model=m.SystemStatus, summary="System status")
async def system_status(request: Request):
    return _svc(request).status.snapshot()


@router.get("/system/preflight", response_model=m.PreflightReport, summary="Latest preflight report")
async def get_preflight(request: Request):
    svc = _svc(request)
    return svc.preflight or await svc.status.run_preflight()


@router.post("/system/preflight", response_model=m.PreflightReport, summary="Re-run preflight")
async def post_preflight(request: Request):
    return await _svc(request).status.run_preflight()


@router.get("/system/config", response_model=m.PublicConfig, summary="Public config for the browser")
async def system_config(request: Request):
    """The only route that carries a key, and only the Mapbox public token (E3)."""
    svc = _svc(request)
    token = svc.settings.mapbox_public_token
    return m.PublicConfig(
        version=svc.version,
        mapbox_token=token.get_secret_value() if token else "",
        sim_url=f"http://127.0.0.1:{svc.settings.sim_port}",
        demo_time_scale=svc.settings.demo_time_scale == "on",
        demo_time=svc.settings.demo_values(),
        site=svc.site.site(),
    )


@router.get("/system/bands", response_model=m.BandsView, summary="Parameter stress breakpoints (config/bands.yaml)")
async def system_bands(request: Request):
    """The same breakpoints FusionRiskEngine uses, so the UI classifies readings without its own copy."""
    b = _svc(request).settings.bands
    return m.BandsView(
        status=b.status,
        class_limits=_svc(request).settings.risk.class_limits,
        parameters={
            k: m.BandView(unit=v.unit, breakpoints=v.breakpoints, evidence=v.evidence)
            for k, v in b.parameters.items()
        },
    )


@router.get("/system/settings", response_model=m.Settings, summary="UI settings")
async def get_settings(request: Request):
    return load_ui_settings(_svc(request))


@router.patch("/system/settings", response_model=m.Settings, summary="Update UI settings")
async def patch_settings(request: Request, body: m.SettingsPatch):
    return patch_ui_settings(_svc(request), body)
