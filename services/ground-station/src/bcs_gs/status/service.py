"""StatusService: the ``SystemStatus`` snapshot, ``system.status`` events and component heartbeats."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Literal

from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.status.preflight import Facts, collect_preflight, dashboard_url
from bcs_gs.status.probes import Probes
from bcs_gs.store.retention import DEFAULT_BUDGET_BYTES

if TYPE_CHECKING:
    from bcs_gs.api.state import Services

log = logging.getLogger("bcs_gs.status")

STATUS_PERIOD_S = 5
PREFLIGHT_PERIOD_S = 300
HEARTBEAT_REFRESH_S = 60

Comp = Literal["ok", "warn", "fail", "off"]
_FROM_CHECK: dict[str, Comp] = {"pass": "ok", "warn": "warn", "fail": "fail"}
_SYNC_COMP: dict[str, Comp] = {"online": "ok", "buffering": "warn", "offline": "fail"}


class StatusService:
    def __init__(self, services: Services, probes: Probes) -> None:
        self.svc = services
        self.probes = probes
        self.facts = Facts()
        self._heartbeat: dict[str, tuple[str, float]] = {}  # component -> (signature, monotonic)
        self._preflight_lock = asyncio.Lock()

    # -- preflight --------------------------------------------------------------------------
    def run_preflight_blocking(self) -> m.PreflightReport:
        report, facts = collect_preflight(self.svc.settings, self.probes, self.svc.clock.now())
        self.svc.preflight = report
        self.facts = facts
        return report

    async def run_preflight(self) -> m.PreflightReport:
        """Re-run preflight off the event loop, then publish the new status at once."""
        async with self._preflight_lock:
            report = await asyncio.to_thread(self.run_preflight_blocking)
        await self.publish()
        return report

    # -- snapshot ---------------------------------------------------------------------------
    def _check(self, cid: str) -> m.PreflightCheck | None:
        rep = self.svc.preflight
        return next((c for c in rep.checks if c.id == cid), None) if rep else None

    def _from_check(self, comp: str, cid: str, ok: str, *, off_if_warn: bool = False) -> m.ComponentStatus:
        since = self.svc.started_at
        c = self._check(cid)
        if c is None:
            return m.ComponentStatus(id=comp, status="off", summary="Not checked yet", since=since)  # type: ignore[arg-type]
        status = _FROM_CHECK[c.status]
        if off_if_warn and c.status != "pass":
            status = "off"
        return m.ComponentStatus(  # type: ignore[arg-type]
            id=comp, status=status, summary=ok if c.status == "pass" else c.detail, since=since
        )

    def snapshot(self) -> m.SystemStatus:
        svc = self.svc
        since = svc.started_at
        st = svc.sync.status()
        sync = m.SyncState(
            state=st.state, queue=st.queue, media_queue=st.media_queue, lag_s=st.lag_s,
            last_success_at=st.last_success_at,
        )  # fmt: skip
        cloud_on = svc.cloud.enabled
        if cloud_on:
            summary = {
                "online": "Cloud reachable",
                "buffering": "Buffering to disk",
                "offline": "Unreachable",
            }
            cloud = m.ComponentStatus(
                id="cloud", status=_SYNC_COMP[sync.state], summary=summary[sync.state], since=since
            )
            if self.facts.paused:
                cloud = m.ComponentStatus(
                    id="cloud", status="fail", summary="Supabase project is paused", since=since,
                    details={"dashboard_url": dashboard_url(svc.settings)},
                )  # fmt: skip
        else:
            cloud = m.ComponentStatus(id="cloud", status="off", summary="Cloud sync disabled", since=since)

        if not svc.camera_enabled:
            camera = m.ComponentStatus(id="camera", status="off", summary="Camera disabled", since=since)
        else:
            camera = self._from_check("camera", "camera", "Camera online")
            info = self.facts.camera_json
            if info and camera.status == "ok":
                camera.details = {
                    k: info[k] for k in ("device_id", "fw_version", "ip", "rssi_dbm") if k in info
                }

        gem = self._check("gemini_keys")
        if gem is None:
            ai = m.ComponentStatus(id="ai", status="off", summary="Not checked yet", since=since)
        elif gem.status == "fail":
            ai = m.ComponentStatus(id="ai", status="warn", summary="Rules tier only", since=since)
        else:
            ai = m.ComponentStatus(
                id="ai", status=_FROM_CHECK[gem.status], summary=gem.detail, since=since
            )  # fmt: skip

        reality = svc.reality
        provider = reality.provider if reality is not None else None
        if provider is None and self.facts.directml is not None:
            provider = "DmlExecutionProvider" if self.facts.directml else "CPUExecutionProvider"
        depth_mode = reality.mode if reality is not None and reality.mode is not None else "off"
        depth_fps = reality.fps if reality is not None else 0.0
        components = [
            camera,
            m.ComponentStatus(id="ground_station", status="ok", summary="Running", since=since),
            self._from_check("broker", "broker", "Broker reachable"),
            cloud,
            m.ComponentStatus(
                id="sync",
                status=_SYNC_COMP[sync.state] if cloud_on else "off",
                summary=f"{sync.queue} rows and {sync.media_queue} media queued",
                since=since,
                details={
                    "queue": sync.queue,
                    "media_queue": sync.media_queue,
                    "media_failed": st.media_failed,
                    "dead_letter": st.dead_letter,
                    "failures": svc.sync.consecutive_failures,
                },
            ),
            ai,
            self._from_check("image_service", "nvidia_key", "Image service ready", off_if_warn=True),
            self._from_check("gpu", "depth_model", "Depth model ready"),
            self._from_check("ollama", "ollama", "Local Gemma ready", off_if_warn=True),
            m.ComponentStatus(
                id="simulator", status="off", summary="Simulator is not connected", since=since
            ),
        ]
        storage = svc.repo.query(
            "SELECT COALESCE(SUM(bytes), 0) AS n FROM media_objects WHERE state = 'uploaded'"
        )
        return m.SystemStatus(
            version=svc.version,
            started_at=since,
            now=to_iso(svc.clock.now()),
            demo_time_scale=svc.settings.demo_time_scale == "on",
            components=components,
            sync=sync,
            cloud=m.CloudUsage(
                db_bytes=self.facts.db_bytes,
                storage_bytes=int(storage[0]["n"]),
                storage_budget_bytes=DEFAULT_BUDGET_BYTES,
                paused=self.facts.paused,
                dashboard_url=dashboard_url(svc.settings),
            ),
            depth=m.DepthStatus(provider=provider, mode=depth_mode, fps=depth_fps),
        )

    # -- publish and heartbeats -------------------------------------------------------------
    def _snapshot_and_beat(self) -> m.SystemStatus:
        """Worker-thread part of a publish: SQLite reads and heartbeat writes."""
        status = self.snapshot()
        self._write_heartbeats(status)
        return status

    async def publish(self) -> m.SystemStatus:
        """Build the status off the loop, then publish on the loop (the EventBus is not thread-safe)."""
        status = await asyncio.to_thread(self._snapshot_and_beat)
        self.svc.bus.publish("system.status", status.model_dump())
        return status

    def _write_heartbeats(self, status: m.SystemStatus) -> None:
        """Upsert one ``system_heartbeats`` row per component: at once on change, else every 60 s."""
        now_m = self.svc.clock.monotonic()
        at = to_iso(self.svc.clock.now())
        for c in status.components:
            # the sync summary carries queue counts; sign it on status only to avoid outbox churn
            sig = json.dumps([c.status] if c.id == "sync" else [c.status, c.summary])
            prev = self._heartbeat.get(c.id)
            if prev and prev[0] == sig and now_m - prev[1] < HEARTBEAT_REFRESH_S:
                continue
            self.svc.repo.upsert(
                "system_heartbeats",
                {
                    "component": c.id,
                    "at": at,
                    "status": c.status,
                    "details": {"summary": c.summary, **c.details},
                },
            )
            self._heartbeat[c.id] = (sig, now_m)

    # -- loops ------------------------------------------------------------------------------
    async def run(self) -> None:
        """Publish ``system.status`` every 5 s. Never raises."""
        while True:
            await self.svc.clock.sleep(STATUS_PERIOD_S)
            try:
                await self.publish()
            except Exception as exc:  # noqa: BLE001
                log.warning("system.status failed: %s", type(exc).__name__)

    async def run_preflight_loop(self) -> None:
        """Run preflight at start (in the background, so start-up never waits on the network),
        then every 5 minutes. Never raises."""
        while True:
            try:
                await self.run_preflight()
            except Exception as exc:  # noqa: BLE001
                log.warning("preflight failed: %s", type(exc).__name__)
            await self.svc.clock.sleep(PREFLIGHT_PERIOD_S)
