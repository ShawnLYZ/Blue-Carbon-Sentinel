"""FastAPI application factory (addendum D3, I, J)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from bcs_protocol.timefmt import to_iso
from fastapi import FastAPI

from bcs_gs import __version__
from bcs_gs.ai.gateway import AIGateway
from bcs_gs.ai.providers.gemini import GeminiProvider
from bcs_gs.ai.providers.ollama import OllamaProvider
from bcs_gs.alerts import AlertService
from bcs_gs.api import (
    routes_ai,
    routes_alerts,
    routes_assessments,
    routes_calibration,
    routes_camera,
    routes_captures,
    routes_carbon,
    routes_commissioning,
    routes_director,
    routes_forecasts,
    routes_history,
    routes_internal,
    routes_ledger,
    routes_media,
    routes_nodes,
    routes_plans,
    routes_site,
    routes_system,
    routes_tasks,
    routes_test,
    routes_trees,
    ws,
)
from bcs_gs.api.errors import install_error_handlers
from bcs_gs.api.models import ErrorEnvelope
from bcs_gs.api.state import Services, seed_site
from bcs_gs.api.static import REPO_ROOT, mount_static
from bcs_gs.camera import CameraLink
from bcs_gs.camera.imagery import CameraImagerySource
from bcs_gs.capture import CaptureService
from bcs_gs.carbon import engine as carbon_engine
from bcs_gs.core.clock import Clock, RealClock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus
from bcs_gs.core.logging import register_secret
from bcs_gs.director import Director
from bcs_gs.evidence.builder import EvidencePackBuilder
from bcs_gs.forecast.service import ForecastService
from bcs_gs.fusion.engine import FusionRiskEngine
from bcs_gs.futures.illustrator import FLUX_MODEL, DisabledIllustrator, NvidiaFluxIllustrator
from bcs_gs.futures.jobs import IllustrationJobs
from bcs_gs.futures.renderer import FutureRenderer
from bcs_gs.history import HistoryService, TreeService
from bcs_gs.ledger.eligibility import EligibilityEvaluator
from bcs_gs.ledger.service import LedgerService
from bcs_gs.live import LiveGateway
from bcs_gs.models_paths import depth_model_dir
from bcs_gs.nodes.broker_admin import BrokerAdmin
from bcs_gs.nodes.commissioning import Commissioning
from bcs_gs.nodes.gs_identity import GS_USER, ensure_gs_identity
from bcs_gs.nodes.registry import NodeRegistry
from bcs_gs.reality import DepthRunner, RealityLayer
from bcs_gs.restoration.planner import PlanService
from bcs_gs.site.calibration import CalibrationService
from bcs_gs.site.registry import SiteRegistry
from bcs_gs.status.probes import FakeProbes, Probes, RealProbes
from bcs_gs.status.service import StatusService
from bcs_gs.store import hydrate as hydrate_mod
from bcs_gs.store.cloud import CloudTarget, NullCloudTarget, SupabaseCloudTarget
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.repo import Repo
from bcs_gs.store.retention import MediaBudget, Retention
from bcs_gs.store.sync import SyncWorker
from bcs_gs.tasking.controller import TaskingController
from bcs_gs.telemetry.ingest import TelemetryIngest
from bcs_gs.telemetry.mqtt import MqttBus

log = logging.getLogger("bcs_gs.app")

MAINTENANCE_PERIOD_S = 3600
API_PREFIX = "/api/v1"

_AREA_ROUTERS = (
    routes_system, routes_site, routes_camera, routes_calibration, routes_captures, routes_media,
    routes_trees, routes_nodes, routes_commissioning, routes_tasks, routes_assessments, routes_history,
    routes_ai, routes_plans, routes_forecasts, routes_carbon, routes_ledger, routes_alerts, routes_director,
)  # fmt: skip


@dataclass
class Overrides:
    """Injection points for tests and test mode."""

    clock: Clock | None = None
    cloud: CloudTarget | None = None
    ai_providers: Any = None
    probes: Probes | None = None
    illustrator: Any = None  # an ImageIllustrator (addendum M); tests inject a fake
    camera_enabled: bool = True
    test_mode: bool = False


def gemini_keys(settings: Settings) -> dict[int, Any]:
    """Configured Gemini key slots (1-3) -> SecretStr."""
    return {i: k for i in (1, 2, 3) if (k := getattr(settings, f"gemini_api_key_{i}")) is not None}


def select_ai_providers(settings: Settings, overrides: Overrides) -> dict[str, Any]:
    """Injected providers win. Test mode never reaches real Gemini or Ollama (the rules tier answers);
    otherwise Gemini (when a key is configured) and the local Ollama. The rules tier needs no provider."""
    if overrides.ai_providers is not None:
        return dict(overrides.ai_providers)
    if overrides.test_mode:
        return {}
    providers: dict[str, Any] = {"ollama": OllamaProvider()}
    keys = gemini_keys(settings)
    if keys:
        providers["gemini"] = GeminiProvider(keys)
    return providers


def select_illustrator(settings: Settings, overrides: Overrides) -> Any:
    """Injected wins. Test mode never reaches NVIDIA (DisabledIllustrator); without a key the same."""
    if overrides.illustrator is not None:
        return overrides.illustrator
    if overrides.test_mode:
        return DisabledIllustrator("test mode never calls NVIDIA")
    key = settings.nvidia_api_key
    if key is None or not key.get_secret_value():
        return DisabledIllustrator("no NVIDIA key (BCS_NVIDIA_API_KEY)")
    return NvidiaFluxIllustrator(key.get_secret_value(), model=settings.ai.models.get("image", FLUX_MODEL))


def select_cloud(settings: Settings) -> CloudTarget:
    key = settings.supabase_service_role_key
    if settings.supabase_url and key:
        return SupabaseCloudTarget(settings.supabase_url, key.get_secret_value())
    return NullCloudTarget()


async def _every(clock: Clock, period_s: float, fn: Any, name: str) -> None:
    """Run ``fn`` every ``period_s`` on the injected clock; one failure never stops the loop."""
    while True:
        await clock.sleep(period_s)
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            log.warning("%s failed: %s", name, type(exc).__name__)


def _build_services(settings: Settings, overrides: Overrides) -> Services:
    clock = overrides.clock or RealClock()
    root = settings.data_dir or REPO_ROOT
    db = Database(root / "var" / "bcs.sqlite3", clock)
    db.migrate()
    repo = Repo(db)
    bus = EventBus(clock=clock)
    site = SiteRegistry(settings.site)
    media = MediaStore(root, db)
    cloud = overrides.cloud or select_cloud(settings)
    budget = MediaBudget(db, cloud)
    svc: Services

    def on_offline(offline: bool) -> None:
        svc.sync_offline = offline
        log.warning("cloud sync %s", "offline" if offline else "recovered")
        if offline and svc.alerts is not None:
            svc.alerts.cloud_offline()

    sync = SyncWorker(db, media, cloud, bus, clock, on_offline, budget=budget)
    svc = Services(
        db=db, repo=repo, bus=bus, site=site, sync=sync, media=media, clock=clock, settings=settings,
        cloud=cloud, budget=budget, retention=Retention(db, media, clock), data_root=root,
        started_at=to_iso(clock.now()), version=__version__, test_mode=overrides.test_mode,
        camera_enabled=overrides.camera_enabled, ai_providers=overrides.ai_providers,
    )  # fmt: skip
    key = settings.supabase_service_role_key
    probes = overrides.probes or (
        FakeProbes()
        if overrides.test_mode
        else RealProbes(root / "var" / "run", settings.supabase_url, key.get_secret_value() if key else None)
    )
    svc.camera = CameraLink(settings, clock, bus, repo=repo)
    svc.calibration = CalibrationService(repo, bus, clock, seed_default=False)  # see _seed_defaults
    svc.imagery = CameraImagerySource(svc.camera, svc.calibration)
    live = svc.camera_enabled and not svc.test_mode  # same rule as starting the CameraLink
    svc.reality = RealityLayer(svc.imagery, DepthRunner(depth_model_dir(root), load=live), bus, settings)
    svc.live = LiveGateway(svc.reality, settings)
    svc.capture = CaptureService(
        repo=repo, media=media, bus=bus, clock=clock, imagery=svc.imagery, camera=svc.camera,
        calibration=svc.calibration, reality=svc.reality, site=site, thresholds=settings.thresholds,
        test_mode=overrides.test_mode,
    )  # fmt: skip
    svc.probes = probes
    svc.status = StatusService(svc, probes)
    admin_pw = settings.broker_admin_password
    broker_admin = (
        BrokerAdmin("127.0.0.1", settings.broker_port, settings.broker_admin_user, admin_pw.get_secret_value())
        if admin_pw
        else None
    )
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    svc.nodes = NodeRegistry(repo, broker_admin, bus, site, clock, loop=loop)
    svc.commissioning = Commissioning(
        svc.nodes, svc.capture, site, repo, bus, on_recommission=None, clock=clock, media=media
    )
    svc.tasking = TaskingController(
        repo, svc.nodes, bus, clock, settings, site=site, site_id=site.site().id, captures=svc.capture,
        grid=svc.commissioning.grid,
    )  # fmt: skip
    tasking = svc.tasking
    # A re-commission moves nodes, so every open task is cancelled (its nodes return to baseline).
    svc.commissioning.on_recommission = lambda: tasking.cancel_all("re-commissioned")
    svc.commissioning.gaps = tasking.gaps  # coverage.updated after a run carries the same gaps
    svc.ingest = TelemetryIngest(
        repo, svc.nodes, bus, clock, settings, site_id=site.site().id, on_ack=tasking.on_ack
    )
    slots = tuple(gemini_keys(settings)) or (1, 2, 3)
    svc.ai = AIGateway.from_settings(
        settings.ai, select_ai_providers(settings, overrides), repo, clock, bus, key_slots=slots
    )
    svc.fusion = FusionRiskEngine(
        repo=repo, bus=bus, clock=clock, settings=settings, registry=svc.nodes, ingest=svc.ingest,
        captures=svc.capture, media=media, camera=svc.camera, calibration=svc.calibration, tasking=tasking,
        gateway=svc.ai, grid=tasking.grid,
    )  # fmt: skip
    svc.alerts = AlertService(repo, bus, clock, settings)
    svc.history = HistoryService(
        repo=repo, bus=bus, clock=clock, settings=settings, site=site, captures=svc.capture, gateway=svc.ai
    )
    svc.trees = TreeService(
        repo=repo, bus=bus, clock=clock, settings=settings, site=site, captures=svc.capture, media=media,
        gateway=svc.ai,
    )  # fmt: skip
    svc.forecasts = ForecastService(
        repo=repo, bus=bus, clock=clock, settings=settings, site=site, captures=svc.capture, fusion=svc.fusion,
        gateway=svc.ai,
    )  # fmt: skip
    svc.plans = PlanService(
        repo=repo, bus=bus, clock=clock, settings=settings, site=site, captures=svc.capture, fusion=svc.fusion,
        gateway=svc.ai, forecasts=svc.forecasts, trees=svc.trees,
    )  # fmt: skip
    svc.futures = FutureRenderer(repo=repo, bus=bus, media=media, site=site, fusion=svc.fusion)
    svc.illustrations = IllustrationJobs(
        repo=repo, bus=bus, media=media, clock=clock, futures=svc.futures,
        illustrator=select_illustrator(settings, overrides), ai=settings.ai,
    )  # fmt: skip
    svc.futures.on_rendered = svc.illustrations.on_rendered
    svc.ledger = LedgerService(
        repo, bus, svc.alerts, clock, carbon_engine, settings=settings, forecasts=svc.forecasts,
        captures=svc.capture, registry=svc.nodes, grid=tasking.grid, site_id=site.site().id,
    )  # fmt: skip
    svc.eligibility = EligibilityEvaluator(
        repo=repo, bus=bus, clock=clock, settings=settings, ledger=svc.ledger, forecasts=svc.forecasts,
        ingest=svc.ingest, registry=svc.nodes, tasking=tasking, grid=tasking.grid, site_id=site.site().id,
    )  # fmt: skip
    svc.evidence = EvidencePackBuilder(
        repo=repo, media=media, ledger=svc.ledger, forecasts=svc.forecasts, clock=clock, carbon=carbon_engine
    )
    svc.director = Director(bus, svc.camera, clock)
    return svc


async def _start_ingest(svc: Services) -> None:
    """Once the ``bcs-gs`` broker identity exists, connect as it and start the telemetry ingest.
    Without broker credentials (preflight reports them) the ingest stays detached."""
    settings = svc.settings
    if not await ensure_gs_identity(settings):
        return
    gs_pw = settings.gs_mqtt_password
    assert gs_pw is not None  # ensure_gs_identity returns False without it
    mqtt = MqttBus("127.0.0.1", settings.broker_port, GS_USER, gs_pw.get_secret_value(), client_id=GS_USER)
    await svc.ingest.start(mqtt)
    svc.tasking.attach(mqtt)  # commands go out on the ingest's bcs-gs connection


async def _auto_commission(svc: Services) -> None:
    """Commission once at start when no nodes are registered (§12): the fallback spread without a
    capture. A failure (e.g. the broker is down) is logged; the operator can re-run commissioning."""
    try:
        if await asyncio.to_thread(svc.nodes.nodes):
            return
        await svc.commissioning.run(confirm=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("auto-commissioning failed: %s: %s", type(exc).__name__, exc)


def _seed_defaults(svc: Services) -> None:
    """Startup seeding: the site and zone rows, a default calibration when none is active, the CAM-01
    device. It runs after hydration, so on a hydrated machine it finds the cloud's rows and queues
    nothing (a seeded active calibration pushed over the cloud's would break its one-active index)."""
    seed_site(svc.repo, svc.site, svc.clock)
    svc.calibration.ensure_default()
    svc.nodes.ensure_camera()


async def _restore_identities(svc: Services) -> None:
    """Device keys are never pulled from the cloud (H6), so hydrated simulated nodes have none and a fresh
    broker has no accounts for them. Re-issue them through the simulator provisioning path (new key and
    broker account, then a ``key_regenerated`` event a running simulator reloads on). Hardware nodes need
    an operator: regenerate the key and re-flash. A failure (broker down) is logged; the simulator's own
    credential fetch at its start provisions the same nodes."""
    try:
        ids = await asyncio.to_thread(_simulated_without_keys, svc)
        if ids:
            await asyncio.to_thread(svc.nodes.provision_simulated, ids)
            log.info("re-issued identities for %d hydrated simulated nodes", len(ids))
    except Exception as exc:  # noqa: BLE001
        log.warning("restoring node identities failed: %s: %s", type(exc).__name__, exc)


def _simulated_without_keys(svc: Services) -> list[str]:
    keyed = {r["device_id"] for r in svc.repo.query("SELECT device_id FROM device_keys")}
    return [n.id for n in svc.nodes.nodes() if n.source == "simulated" and n.id not in keyed]


async def _auto_hydrate(svc: Services) -> None:
    """A fresh machine (empty local store) pulls its state from the cloud when that is reachable (H6).
    Never fatal: any failure is logged and the Ground Station starts with what it has."""
    try:
        if not svc.cloud.enabled or not await asyncio.to_thread(hydrate_mod.needs_hydration, svc.repo):
            return
        await asyncio.to_thread(svc.cloud.probe, "captures")
        log.info("hydrating from cloud... (a fresh local store; this can take a while)")
        started = time.monotonic()
        report = await asyncio.to_thread(hydrate_mod.hydrate, svc.repo, svc.media, svc.cloud, svc.clock)
        log.info(
            "hydration finished in %.1f s: %d rows, %d media objects",
            time.monotonic() - started, sum(report.tables.values()), report.media,
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001
        log.warning("hydration skipped: %s: %s", type(exc).__name__, exc)


def create_app(settings: Settings, *, overrides: Overrides | None = None) -> FastAPI:
    overrides = overrides or Overrides()
    for secret in settings.secret_values_except_mapbox():
        register_secret(secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = _build_services(settings, overrides)
        app.state.services = svc
        await _auto_hydrate(svc)  # before anything reads the store (nodes, ledger verification, commissioning)
        await asyncio.to_thread(_seed_defaults, svc)  # after hydration: finds hydrated rows, queues nothing
        svc.alerts.start(camera=svc.camera)  # first, so it sees every event the others publish
        svc.tasking.start()
        svc.fusion.start()
        svc.history.start()
        svc.trees.start()
        svc.futures.start()
        await svc.ledger.startup_verify()  # the one startup verification: before the evaluator's first pass
        svc.eligibility.start()
        svc.director.open()
        tasks = [
            asyncio.create_task(svc.sync.run(), name="sync"),  # never awaited on: the cloud may be down
            asyncio.create_task(svc.status.run(), name="status"),
            asyncio.create_task(svc.status.run_preflight_loop(), name="preflight"),
            asyncio.create_task(
                _every(svc.clock, MAINTENANCE_PERIOD_S, lambda: _maintain(svc), "maintenance"),
                name="maintenance",
            ),
            asyncio.create_task(_start_ingest(svc), name="broker-identity-and-ingest"),
        ]
        # Not cancelled at shutdown: these run registry work in a worker thread that must finish first.
        identities = asyncio.create_task(_restore_identities(svc), name="restore-node-identities")
        auto = (
            asyncio.create_task(_auto_commission(svc), name="auto-commission")
            if settings.auto_commission
            else None
        )
        if svc.camera_enabled and not svc.test_mode:
            svc.camera.start()
            pending: set[asyncio.Task[Any]] = set()

            def on_mode(_mode: str) -> None:  # runs on the loop: system.status carries the new mode
                t = asyncio.create_task(svc.status.publish(), name="status-on-depth-mode")
                pending.add(t)
                t.add_done_callback(pending.discard)

            svc.reality.on_mode_change(on_mode)
            svc.reality.start()
            tasks.append(asyncio.create_task(svc.live.run(), name="live-pump"))
            svc.capture.start()
        log.info("Ground Station %s ready (test_mode=%s)", svc.version, svc.test_mode)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            for t in (identities, auto):
                if t is not None:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await t
            await svc.director.aclose()
            await svc.eligibility.stop()
            await svc.futures.stop()
            await svc.illustrations.stop()
            await svc.plans.stop()
            await svc.forecasts.stop()
            await svc.trees.stop()
            await svc.history.stop()
            await svc.fusion.stop()
            await svc.tasking.stop()
            await svc.alerts.stop()
            await svc.ingest.stop()
            await svc.live.close()
            await svc.capture.stop()
            await asyncio.to_thread(svc.reality.stop)
            await asyncio.to_thread(svc.camera.stop)
            svc.db.close()

    app = FastAPI(
        title="Blue Carbon Sentinel Ground Station",
        version=__version__,
        lifespan=lifespan,
        responses={"default": {"model": ErrorEnvelope, "description": "Error envelope (addendum I1)"}},
    )
    install_error_handlers(app)
    for mod in _AREA_ROUTERS:
        app.include_router(mod.router, prefix=API_PREFIX)
    app.include_router(routes_internal.router, prefix=API_PREFIX)
    if overrides.test_mode:
        app.include_router(routes_test.router, prefix=API_PREFIX)
    app.include_router(ws.router)
    mount_static(app)  # last: the "/" mount is a catch-all
    return app


async def _maintain(svc: Services) -> None:
    """Hourly: thin old captures and unretained futures media (H7) and enforce the cloud media budget (A2)."""
    await asyncio.to_thread(svc.retention.thin_captures)
    await asyncio.to_thread(svc.retention.thin_futures)
    await asyncio.to_thread(svc.budget.enforce)
