"""Shared application state: the ``Services`` container, site seeding, UI settings and test reset."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.core.clock import Clock, ManualClock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus
from bcs_gs.site.registry import SiteRegistry
from bcs_gs.store.cloud import CloudTarget
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.repo import Repo
from bcs_gs.store.retention import MediaBudget, Retention
from bcs_gs.store.schema import LEDGER_TRIGGERS_DDL, LEDGER_TRIGGERS_DROP
from bcs_gs.store.sync import SyncWorker

SETTINGS_KEY = "ui_settings"


@dataclass
class Services:
    """Everything routes need. Later milestones add fields."""

    db: Database
    repo: Repo
    bus: EventBus
    site: SiteRegistry
    sync: SyncWorker
    media: MediaStore
    clock: Clock
    settings: Settings
    cloud: CloudTarget
    budget: MediaBudget
    retention: Retention
    data_root: Path
    started_at: str
    version: str
    test_mode: bool = False
    camera_enabled: bool = True
    camera: Any = None  # CameraLink; built always, started only when camera_enabled
    calibration: Any = None  # CalibrationService
    imagery: Any = None  # ImagerySource (CameraImagerySource)
    reality: Any = None  # RealityLayer; built always, started only when camera_enabled
    live: Any = None  # LiveGateway (/ws/live); its pump runs only with the camera
    nodes: Any = None  # NodeRegistry (devices, keys, broker identities)
    commissioning: Any = None  # Commissioning (automatic node placement, §12)
    ingest: Any = None  # TelemetryIngest (G5) and the retained node configs
    tasking: Any = None  # TaskingController (§15): tasks, commands, zones needing coverage
    capture: Any = None  # CaptureService; built always, triggers started only when camera_enabled
    ai_providers: Any = None
    ai: Any = None  # AIGateway (M4): role calls down the tier chain (test mode: rules only)
    fusion: Any = None  # FusionRiskEngine (M4): zone assessments, early warning
    alerts: Any = None  # AlertService (M4): deduplicated, acknowledgeable alerts
    history: Any = None  # HistoryService (M4): synthetic 2016-2025 series
    trees: Any = None  # TreeService (M4): tree points in site coordinates
    forecasts: Any = None  # ForecastService (M5): 2026-2035 forecasts with AI parameters
    plans: Any = None  # PlanService (M5): restoration plans, versions and apply
    futures: Any = None  # FutureRenderer (M5): code-only future textures and heights
    illustrations: Any = None  # IllustrationJobs (M5): FLUX keyframe illustrations
    ledger: Any = None  # LedgerService (M6): the append-only hash-chained carbon ledger
    eligibility: Any = None  # EligibilityEvaluator (M6): the four Verified rules, automatic issuance
    evidence: Any = None  # EvidencePackBuilder (M6): the PDF evidence pack of a ledger record
    director: Any = None  # Director (M7): the event-driven Demo Director state machine (in memory)
    preflight: m.PreflightReport | None = None
    probes: Any = None
    status: Any = None  # StatusService
    sync_offline: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


def _site_row(site: SiteRegistry, now: str) -> dict[str, Any]:
    s = site.site()
    note = site._cfg.selection_note
    return {
        "id": s.id, "name": s.name, "status": "live", "region": s.region,
        "centre_lat": s.centre.lat, "centre_lng": s.centre.lng,
        "anchor_nw_lat": s.anchor_nw.lat, "anchor_nw_lng": s.anchor_nw.lng,
        "bearing_deg": float(site._cfg.bearing_deg), "size_m": s.size_m,
        "scale_label": s.scale_label, "rationale": note or s.name, "updated_at": now,
    }


def _planned_rows(site: SiteRegistry, now: str) -> list[dict[str, Any]]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "status": "planned",
            "region": p.region,
            "centre_lat": p.centre.lat,
            "centre_lng": p.centre.lng,
            "anchor_nw_lat": None,
            "anchor_nw_lng": None,
            "bearing_deg": 0.0,
            "size_m": None,
            "scale_label": None,
            "rationale": p.rationale,
            "updated_at": now,
        }
        for p in site.site().planned_sites
    ]


def _zone_row(site_id: str, z: Any) -> dict[str, Any]:
    return {
        "id": z.id, "site_id": site_id, "label": z.label, "coordinate_id": z.coordinate_id,
        "col": z.col, "row": z.row, "bounds": z.bounds, "bounds_site_m": z.bounds_site_m.model_dump(),
        "centre_lat": z.centre.lat, "centre_lng": z.centre.lng, "area_ha": z.area_ha,
    }


def seed_site(repo: Repo, site: SiteRegistry, clock: Clock) -> None:
    """Upsert the ``sites`` and ``zones`` rows from the registry. Unchanged rows are left alone,
    so a restart does not queue redundant sync work."""
    now = to_iso(clock.now())
    s = site.site()
    for row in [_site_row(site, now), *_planned_rows(site, now)]:
        old = repo.get("sites", {"id": row["id"]})
        if old is None or {**old, "updated_at": ""} != {**row, "updated_at": ""}:
            repo.upsert("sites", row)
    for z in s.zones:
        row = _zone_row(s.id, z)
        old = repo.get("zones", {"id": z.id})
        if old is None or old != row:
            repo.upsert("zones", row)


# ---- UI settings (GET/PATCH /system/settings), persisted in the local ``settings`` table ----------
def load_ui_settings(svc: Services) -> m.Settings:
    row = svc.repo.get("settings", {"key": SETTINGS_KEY})
    return m.Settings.model_validate(row["value"]) if row else m.Settings()


def patch_ui_settings(svc: Services, patch: m.SettingsPatch) -> m.Settings:
    current = load_ui_settings(svc).model_dump()
    changes = patch.model_dump(exclude_none=True)
    camera = changes.pop("camera_desired", None)
    current.update(changes)
    if camera:
        current["camera_desired"].update(camera)
    merged = m.Settings.model_validate(current)
    svc.repo.upsert(
        "settings",
        {"key": SETTINGS_KEY, "value": merged.model_dump(), "updated_at": to_iso(svc.clock.now())},
        sync=False,
    )
    return merged


# ---- test reset ------------------------------------------------------------------------------
async def cancel_background(svc: Services) -> None:
    """Cancel the in-flight background work (fusion, tree-point and tasking work; forecast runs, plan
    proposals, futures renders, illustration jobs) and wait until it has ended, so nothing writes a row
    or a media file after the reset clears them (ruling R30). Renders go before illustrations: a finished
    render starts them. Fusion, trees and tasking restart their listeners (TaskingController.cancel is
    the operator's task cancel, hence ``cancel_work``). The eligibility evaluator is only stopped here: it
    reads the store and may write (a gap note, a Verified record), so the reset route starts it again
    once ``reset_store`` has run."""
    if svc.eligibility is not None:
        await svc.eligibility.stop()
    await asyncio.gather(*(s.cancel_work() for s in (svc.fusion, svc.trees, svc.tasking) if s is not None))
    for service in (svc.forecasts, svc.plans, svc.futures, svc.illustrations):
        if service is not None:
            await service.cancel()


def reset_store(svc: Services) -> None:
    """Clear every table (keeping the schema), the media files and cached state (manual clock, fake
    cloud, sync bookkeeping, capture and reality caches), then re-seed the site and a single fresh
    default calibration."""
    with svc.db.tx() as conn:
        conn.execute("PRAGMA defer_foreign_keys = ON")
        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"
            )
        ]
        for stmt in LEDGER_TRIGGERS_DROP:  # the test reset is the one place the ledger is ever cleared
            conn.execute(stmt)
        for name in tables:
            conn.execute(f'DELETE FROM "{name}"')
        conn.execute("DELETE FROM sqlite_sequence")
        for stmt in LEDGER_TRIGGERS_DDL:
            conn.execute(stmt)
    shutil.rmtree(svc.data_root / "var" / "media", ignore_errors=True)
    svc.preflight = None
    if isinstance(svc.clock, ManualClock):
        svc.clock.reset()
    cloud_reset = getattr(svc.cloud, "reset", None)  # the fake cloud only
    if callable(cloud_reset):
        cloud_reset()
    svc.sync.reset()
    svc.sync_offline = False
    if svc.camera is not None:
        svc.camera.reset_desired()
    if svc.capture is not None:
        svc.capture.reset()
    if svc.reality is not None:
        svc.reality.reset()
    seed_site(svc.repo, svc.site, svc.clock)
    if svc.nodes is not None:
        svc.nodes.ensure_camera()
    if svc.ingest is not None:
        svc.ingest.reset()
    if svc.tasking is not None:
        svc.tasking.reset()
    if svc.fusion is not None:
        svc.fusion.reset()
    if svc.alerts is not None:
        svc.alerts.reset()
    if svc.history is not None:
        svc.history.reset()
    if svc.trees is not None:
        svc.trees.reset()
    if svc.forecasts is not None:
        svc.forecasts.reset()
    if svc.plans is not None:
        svc.plans.reset()
    if svc.futures is not None:
        svc.futures.reset()
    if svc.illustrations is not None:
        svc.illustrations.reset()
    if svc.ledger is not None:
        svc.ledger.reset()
    if svc.eligibility is not None:
        svc.eligibility.reset()
    if svc.evidence is not None:
        svc.evidence.reset()
    if svc.director is not None:
        svc.director.reset()
    if svc.calibration is not None:
        svc.calibration.ensure_default()  # a single fresh default calibration
