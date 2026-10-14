"""FusionRiskEngine (spec §16; addendum A6, N1-N5): zone assessments from code, interpreted by AI.

Code measures, AI interprets. Every assessment's numbers (stressors, weights, risk, confidence, early
warning) are computed here from the latest zone metrics against the baseline and the robust node
readings. The RiskInterpreter only supplies multipliers in the configured bounds plus the narrative,
root causes and actions. AI work never blocks: a code-only assessment is stored and emitted first, and
the AI result arrives as a second ``zone.assessed`` for the same zone.

The latest AI interpretation of a zone (multipliers, narrative, root causes, actions, source chip) is
carried by the zone's later code-only assessments until the next interpretation replaces it.

Events handled:

- ``zone.metrics``: a code-only assessment of every zone;
- ``zone.flagged``: a code-only assessment, and AI (VisionAnalyst when both rasters exist, then
  RiskInterpreter, priority FLAGGED) only when the zone becomes flagged or its set of flag kinds changes:
  a zone that stays flagged is re-flagged on every capture (flags compare to the baseline);
- ``node.telemetry``: the early-warning evaluation for every zone the node covers, and a code-only
  assessment of those zones, at most one per zone per ``TELEMETRY_THROTTLE_S`` of clock time.

A zone becoming High or Critical starts an AI assessment and ``tasking.trigger(zone, "risk_high")``;
an early warning firing triggers ``early_warning`` tasking and marks that zone's assessment.

Automatic (non-operator) AI assessments run at most one at a time per zone and at most one per
``AUTO_MIN_INTERVAL_S`` of clock time per zone; a skipped flag set is retried on the next flagged capture.
Operator requests have their own ``ANALYZE_MIN_INTERVAL_S`` rule.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso

from bcs_gs.ai.roles._common import RoleConfig
from bcs_gs.ai.roles.base import Priority
from bcs_gs.ai.roles.risk_interpreter import RiskInput, RiskInterpreter
from bcs_gs.ai.roles.vision_analyst import VisionAnalyst, VisionInput
from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.core.aio import to_thread_settled
from bcs_gs.core.clock import Clock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.fusion.bands import BAND_KEY, SENSOR_STRESSORS, sensor_stress
from bcs_gs.fusion.confidence import (
    NodeHealthView,
    camera_confidence,
    overall,
    sensor_confidence,
    tier_factor,
)
from bcs_gs.fusion.early_warning import EARLY_WARNING_REASON, EarlyWarning
from bcs_gs.fusion.risk import effective_weights, risk
from bcs_gs.fusion.stressors import sensor_composite, vegetation_decline
from bcs_gs.nodes.coverage import ZoneGrid, by_zone
from bcs_gs.store.repo import Repo

log = logging.getLogger("bcs_gs.fusion")

STRESSORS = ("vegetation", *SENSOR_STRESSORS)
HIGH_CLASSES = ("high", "critical")
TELEMETRY_THROTTLE_S = 2.0
ANALYZE_MIN_INTERVAL_S = 30.0
AUTO_MIN_INTERVAL_S = 30.0  # automatic AI assessments per zone (flags, risk High), clock time
CAPTURES_BUCKET = "captures"


@dataclass
class _Interpretation:
    """The latest AI interpretation of a zone."""

    multipliers: dict[str, float] = field(default_factory=dict)
    narrative: str = ""
    root_causes: list[m.RootCause] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    source: m.SourceChip = field(default_factory=lambda: m.SourceChip(tier="rules", cached=False))
    # Latest VisionAnalyst observations of this zone (carried like the narrative) and their source chip.
    observations: list[m.VisionObservationView] = field(default_factory=list)
    observations_source: m.SourceChip | None = None


@dataclass
class _Snapshot:
    """Everything an assessment reads, gathered in one worker-thread pass."""

    at: datetime
    cover: dict[str, list[str]]  # zone -> covering WQ/SP node IDs
    nodes: dict[str, Any]  # node ID -> NodeRow
    readings: dict[str, dict[str, float]]  # node ID -> robust value per parameter (N1)
    latest: dict[str, Any]  # node ID -> latest TelemetryRow
    capture: dict[str, Any] | None  # the latest capture row
    metrics: dict[str, m.ZoneMetrics]  # zone -> the latest capture's metrics
    baseline_ok: bool  # a baseline exists under the latest capture's calibration (N2)
    four_corner: bool
    camera_online: bool
    cfg: Settings

    def node_stressors(self, node_id: str) -> dict[str, float]:
        """The node's measured sensor stressors from its robust readings."""
        r = self.readings.get(node_id, {})
        return {s: sensor_stress(s, r[k], self.cfg) for s, k in BAND_KEY.items() if r.get(k) is not None}


@dataclass
class _ZoneState:
    stressors: dict[str, float | None]
    readings_summary: dict[str, float]  # stressor -> the reading behind the zone value
    driver_node: dict[str, str]  # stressor -> the covering node with the maximum stress


class FusionRiskEngine:
    def __init__(
        self,
        *,
        repo: Repo,
        bus: EventBus,
        clock: Clock,
        settings: Settings,
        registry: Any,
        ingest: Any,
        captures: Any,
        media: Any,
        camera: Any,
        calibration: Any,
        tasking: Any,
        gateway: Any,
        grid: ZoneGrid,
    ) -> None:
        self._repo, self._bus, self._clock, self._settings = repo, bus, clock, settings
        self._registry, self._ingest, self._captures, self._media = registry, ingest, captures, media
        self._camera, self._calibration, self._tasking, self.gateway = camera, calibration, tasking, gateway
        self.grid = grid
        role_cfg = RoleConfig.from_settings(settings)  # the live Settings, so .env overrides apply
        self._risk_role = RiskInterpreter(role_cfg)
        self._vision_role = VisionAnalyst(role_cfg)
        self._base = dict(settings.risk.weights)
        self._sub: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._bg: set[asyncio.Task[Any]] = set()
        self.reset()

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        self._sub = self._bus.subscribe(10000)
        self._listener = asyncio.create_task(self._listen(), name="fusion-listen")

    async def stop(self) -> None:
        if self._sub is not None:
            self._sub.close()
        tasks = [t for t in (self._listener, *self._bg) if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._bg.clear()

    async def cancel_work(self) -> None:
        """Cancel the work in flight and wait until it ended, then listen again (test reset; ruling R30)."""
        await self.stop()
        self.start()

    def reset(self) -> None:
        """Forget the in-memory state (test reset clears the tables)."""
        self._ew = EarlyWarning(self._settings)
        self._interp: dict[str, _Interpretation] = {}
        self._class: dict[str, str] = {}
        self._last_telemetry: dict[str, datetime] = {}
        self._last_request: dict[str, datetime] = {}
        self._last_key: dict[str, tuple[Any, ...]] = {}  # zone -> fingerprint of its last stored assessment
        self._flag_kinds: dict[str, frozenset[str]] = {}  # zone -> flag kinds whose AI assessment started
        self._auto_running: set[str] = set()  # zones with an automatic AI assessment in flight
        self._last_auto: dict[str, datetime] = {}  # zone -> start of its last automatic AI assessment

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                try:
                    await self._on_event(ev.type, ev.data)
                except Exception:
                    log.exception("fusion failed on %s", ev.type)
            if not sub.overflowed:
                return  # closed by stop()
            log.warning("fusion event subscription overflowed; resubscribing")
            self._sub = self._bus.subscribe(10000)

    async def _on_event(self, type_: str, data: dict[str, Any]) -> None:
        if type_ == "zone.metrics":
            for zm in data.get("metrics") or []:
                if not zm.get("flags"):
                    self._flag_kinds.pop(zm.get("zone_id"), None)  # no longer flagged: a new flag is news
            await self._assess_many(self.grid.zone_ids(), capture_id=data.get("capture_id"))
        elif type_ == "zone.flagged":
            zone_id = data["zone_id"]
            kinds = frozenset(f["kind"] for f in data.get("flags") or [])
            await self.assess(zone_id, capture_id=data.get("capture_id"))
            if kinds != self._flag_kinds.get(zone_id):
                self._auto_interpret(zone_id, Priority.FLAGGED, vision=True, flag_kinds=kinds)
        elif type_ == "node.telemetry":
            await self._on_telemetry(data)

    # ---- public API ---------------------------------------------------------------------------------
    async def assess(
        self,
        zone_id: str,
        *,
        with_ai: bool = False,
        priority: Priority = Priority.BACKGROUND,
        vision: bool = False,
        capture_id: str | None = None,
    ) -> m.Assessment | None:
        """Store and emit a code-only assessment of the zone and return it (None when nothing is measured,
        N3.5). With ``with_ai`` the AI interpretation follows in a background task."""
        done = await self._assess_many([zone_id], capture_id=capture_id)
        if with_ai:
            self._auto_interpret(zone_id, priority, vision=vision)
        return done[0] if done else None

    async def request_analysis(self, zone_id: str) -> str:
        """Operator request (I2 ``POST /zones/{id}/analyze``): an AI assessment in the background."""
        if zone_id not in self.grid.zone_ids():
            raise ApiError("not_found", 404, f"No zone {zone_id}.")
        now = self._clock.now()
        last = self._last_request.get(zone_id)
        if last is not None and (now - last).total_seconds() < ANALYZE_MIN_INTERVAL_S:
            wait = ANALYZE_MIN_INTERVAL_S - (now - last).total_seconds()
            raise ApiError(
                "rate_limited", 429, f"{zone_id} was analysed less than {ANALYZE_MIN_INTERVAL_S:g} s ago.",
                {"retry_after_s": round(wait, 1)},
            )  # fmt: skip
        self._last_request[zone_id] = now
        request_id = uuid7()
        self._spawn(self._interpret(zone_id, Priority.OPERATOR, vision=True), f"fusion-analyze-{zone_id}")
        return request_id

    def list_assessments(self, zone_id: str, limit: int = 100) -> list[m.Assessment]:
        """Newest first (blocking)."""
        rows = self._repo.query(
            "SELECT * FROM zone_assessments WHERE zone_id = ? ORDER BY at DESC, id DESC LIMIT ?",
            (zone_id, limit), table="zone_assessments",
        )  # fmt: skip
        return [_from_row(r) for r in rows]

    def zone_sensors(self, zone_ids: list[str]) -> dict[str, tuple[dict[str, float], bool]]:
        """Per zone: (the reading behind each measured sensor stressor, i.e. the covering node with the
        maximum stress (A6), keyed by stressor such as ``porewater_salinity``; whether any WQ/SP node
        covers the zone). Blocking. Used by the restoration planner (M5)."""
        snap = self._snapshot(list(zone_ids), False)
        return {
            z: (dict(self._zone_state(snap, z).readings_summary), bool(snap.cover.get(z))) for z in zone_ids
        }

    # ---- code-only assessments ----------------------------------------------------------------------
    async def _assess_many(
        self,
        zones: list[str],
        *,
        capture_id: str | None = None,
        early: set[str] | None = None,
    ) -> list[m.Assessment]:
        camera_online = self._camera_online()
        snap = await to_thread_settled(self._snapshot, zones, camera_online, capture_id=capture_id)
        out = await to_thread_settled(self._store_many, snap, zones, capture_id, early or set())
        for a in out:
            self._bus.publish("zone.assessed", a.model_dump(mode="json"))
        for a in out:
            await self._after(a)
        return out

    def _store_many(
        self,
        snap: _Snapshot,
        zones: list[str],
        capture_id: str | None,
        early: set[str],
        *,
        force: bool = False,
    ) -> list[m.Assessment]:
        """Build, store and return the zones' assessments. A code-only assessment that would repeat the
        zone's previous one (same rounded numbers, flags and interpretation) is skipped, so frequent
        captures and telemetry do not flood the synced table; early warnings and AI results (``force``)
        are always stored."""
        out = []
        for z in zones:
            a = self._build(snap, z, self._interp.get(z) or _Interpretation(), z in early, capture_id)
            if a is None:
                continue
            key = _fingerprint(a)
            if not force and z not in early and self._last_key.get(z) == key:
                continue
            self._last_key[z] = key
            self._repo.insert("zone_assessments", _to_row(a))
            out.append(a)
        return out

    async def _after(self, a: m.Assessment) -> None:
        """A zone that becomes High or Critical gets an AI assessment and ``risk_high`` tasking."""
        before = self._class.get(a.zone_id)
        self._class[a.zone_id] = a.risk_class
        if a.risk_class in HIGH_CLASSES and before not in HIGH_CLASSES:
            self._auto_interpret(a.zone_id, Priority.BACKGROUND)
            await self._trigger(
                a.zone_id, "risk_high", f"{a.zone_id} risk {a.risk_class} ({a.risk_score:.1f})"
            )

    async def _trigger(self, zone_id: str, trigger: str, reason: str) -> None:
        if self._tasking is None:
            return
        try:
            await self._tasking.trigger(zone_id, trigger, reason)
        except Exception:
            log.exception("tasking %s for %s failed", trigger, zone_id)

    # ---- telemetry: early warning and throttled assessments -----------------------------------------
    async def _on_telemetry(self, data: dict[str, Any]) -> None:
        node_id = data["node_id"]
        camera_online = self._camera_online()
        snap = await to_thread_settled(self._snapshot_for_node, node_id, camera_online)
        if snap is None:
            return
        zones = [z for z, ns in snap.cover.items() if node_id in ns]
        investigation = data.get("mode") == "investigation"
        now = self._clock.now()
        fired: set[str] = set()
        due: list[str] = []
        for z in zones:
            st = self._zone_state(snap, z)
            # Ruling (Task 5, N5 per-sample reading): the composite is taken per node, over the measured
            # sensor stressors of one node (sum w s / sum w, base weights), not over the zone's pooled
            # stressors: salt intrusion moves only porewater and water salinity, which pooled can never
            # reach 0.5. The streak stays per zone; so that one node's calm sample does not reset another
            # node's streak, a zone evaluation takes the highest per-node composite among its covering
            # nodes (always including the node whose sample triggered it).
            composites = [
                c
                for n in snap.cover.get(z, [])
                if (c := sensor_composite(snap.node_stressors(n), self._base)) is not None
            ]
            composite = max(composites) if composites else None
            if self._ew.observe(z, st.stressors["vegetation"], composite, investigation):
                fired.add(z)
            last = self._last_telemetry.get(z)
            if z in fired or last is None or (now - last).total_seconds() >= TELEMETRY_THROTTLE_S:
                self._last_telemetry[z] = now
                due.append(z)
        for z in sorted(fired):  # tasking first, so the task exists when the assessment is seen
            log.info("early warning for %s", z)
            await self._trigger(z, "early_warning", EARLY_WARNING_REASON)
        if due:
            out = await to_thread_settled(self._store_many, snap, due, None, fired)
            for a in out:
                self._bus.publish("zone.assessed", a.model_dump(mode="json"))
            for a in out:
                await self._after(a)

    # ---- AI interpretation ----------------------------------------------------------------------------
    def _spawn(self, coro: Any, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    def _auto_interpret(
        self,
        zone_id: str,
        priority: Priority,
        *,
        vision: bool = False,
        flag_kinds: frozenset[str] | None = None,
    ) -> bool:
        """Start an automatic AI assessment unless one is in flight for the zone or one started less than
        ``AUTO_MIN_INTERVAL_S`` ago (calls happen on events, not per capture). ``flag_kinds`` is recorded
        only when it starts, so a skipped flag set is retried by the next flagged capture."""
        if zone_id in self._auto_running:
            return False
        now = self._clock.now()
        last = self._last_auto.get(zone_id)
        if last is not None and (now - last).total_seconds() < AUTO_MIN_INTERVAL_S:
            return False
        self._auto_running.add(zone_id)
        self._last_auto[zone_id] = now
        if flag_kinds is not None:
            self._flag_kinds[zone_id] = flag_kinds
        self._spawn(self._interpret_auto(zone_id, priority, vision), f"fusion-ai-{zone_id}")
        return True

    async def _interpret_auto(self, zone_id: str, priority: Priority, vision: bool) -> None:
        try:
            await self._interpret(zone_id, priority, vision=vision)
        finally:
            self._auto_running.discard(zone_id)

    async def _interpret(self, zone_id: str, priority: Priority, *, vision: bool = False) -> None:
        try:
            camera_online = self._camera_online()
            snap = await to_thread_settled(self._snapshot, [zone_id], camera_online)
            st = self._zone_state(snap, zone_id)
            measured = {k: v for k, v in st.stressors.items() if v is not None}
            if not measured or self.gateway is None:
                return  # N3.5: nothing to interpret
            metrics = snap.metrics.get(zone_id) if snap.baseline_ok else None
            context: dict[str, Any] = {"node_readings": self._readings_context(snap, zone_id)}
            prev = self._interp.get(zone_id)
            observations = list(prev.observations) if prev else []
            observations_source = prev.observations_source if prev else None
            if vision and metrics is not None:
                images = await to_thread_settled(self._rasters, snap)
                if images is not None:
                    vin = VisionInput([zone_id], images[0], images[1], {zone_id: metrics})
                    v = await self.gateway.call(self._vision_role, vin, priority)
                    observations, observations_source = observations_of(zone_id, v.output.observations, v.source)
                    context["vision"] = {
                        "narrative": v.output.narrative,
                        "observations": [o.model_dump() for o in v.output.observations],
                        "tier": v.source.tier,
                    }
            rin = RiskInput(zone_id, measured, metrics, st.readings_summary, context)
            r = await self.gateway.call(self._risk_role, rin, priority)
            out = r.output
            interp = _Interpretation(
                multipliers=dict(out.multipliers),
                narrative=out.narrative,
                root_causes=[m.RootCause(driver=c.driver, rank=c.rank, why=c.why) for c in out.root_causes],
                actions=list(out.actions),
                source=r.source,
                observations=observations,
                observations_source=None if observations_source == r.source else observations_source,
            )
            self._interp[zone_id] = interp
            stored = await to_thread_settled(self._store_many, snap, [zone_id], None, set(), force=True)
            for a in stored:
                self._bus.publish("zone.assessed", a.model_dump(mode="json"))
            for a in stored:
                await self._after(a)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("AI assessment of %s failed", zone_id)

    def _readings_context(self, snap: _Snapshot, zone_id: str) -> dict[str, dict[str, Any]]:
        """Robust value per covering node and parameter, with units (bands.yaml)."""
        params = self._settings.bands.parameters
        out: dict[str, dict[str, Any]] = {}
        for n in snap.cover.get(zone_id, []):
            r = snap.readings.get(n) or {}
            out[n] = {
                p: {"value": v, "unit": getattr(params.get(p), "unit", None)} for p, v in sorted(r.items())
            }
        return out

    def _rasters(self, snap: _Snapshot) -> tuple[bytes, bytes] | None:
        """(current, previous) JPEG of the latest capture and the baseline; None when either is missing."""
        cap = snap.capture
        if cap is None:
            return None
        base = self._repo.query(
            "SELECT * FROM captures WHERE is_baseline = 1 ORDER BY taken_at DESC LIMIT 1", table="captures"
        )
        if not base or base[0]["id"] == cap["id"]:
            return None
        out = []
        for row in (cap, base[0]):
            key = (row.get("media") or {}).get("image")
            if not key:
                return None
            path = self._media.path(CAPTURES_BUCKET, key)
            if not path.exists():
                return None
            out.append(path.read_bytes())
        return out[0], out[1]

    # ---- snapshot (worker thread) ---------------------------------------------------------------------
    def _camera_online(self) -> bool:
        try:
            return bool(self._camera.status().online) if self._camera is not None else False
        except Exception:  # noqa: BLE001
            return False

    def _snapshot_for_node(self, node_id: str, camera_online: bool) -> _Snapshot | None:
        nodes = self._registry.nodes()
        cover = self._cover(nodes)
        zones = [z for z, ns in cover.items() if node_id in ns]
        return self._snapshot(zones, camera_online, nodes=nodes, cover=cover) if zones else None

    def _cover(self, nodes: list[Any]) -> dict[str, list[str]]:
        return {z: [*c["water"], *c["soil"]] for z, c in by_zone(nodes, self.grid).items()}

    def _snapshot(
        self,
        zones: list[str],
        camera_online: bool,
        *,
        nodes: list[Any] | None = None,
        cover: dict[str, list[str]] | None = None,
        capture_id: str | None = None,
    ) -> _Snapshot:
        """``capture_id`` (an event's capture) is used instead of the latest capture when it exists, so an
        event handled late still assesses the metrics it announced."""
        nodes = self._registry.nodes() if nodes is None else nodes
        cover = self._cover(nodes) if cover is None else cover
        by_id = {n.id: n for n in nodes}
        wanted = sorted({n for z in zones for n in cover.get(z, [])})
        latest = {n: row for n in wanted if (row := self._ingest.latest(n)) is not None}
        readings = {}
        for n in wanted:
            if n not in latest:
                continue
            mode = getattr(by_id.get(n), "mode", None) or latest[n].mode or "baseline"
            readings[n] = self._ingest.robust_all(n, mode)
        named = self._repo.get("captures", {"id": capture_id}) if capture_id else None
        caps = (
            [named]
            if named is not None
            else self._repo.query(
                "SELECT * FROM captures ORDER BY taken_at DESC, id DESC LIMIT 1", table="captures"
            )
        )
        capture = caps[0] if caps else None
        metrics: dict[str, m.ZoneMetrics] = {}
        baseline_ok = False
        if capture is not None:
            rows = self._repo.query(
                "SELECT * FROM zone_metrics WHERE capture_id = ?", (capture["id"],), table="zone_metrics"
            )
            metrics = {
                r["zone_id"]: m.ZoneMetrics.model_validate({k: v for k, v in r.items() if k != "capture_id"})
                for r in rows
            }
            baseline_ok = bool(
                self._repo.query(
                    "SELECT id FROM captures WHERE is_baseline = 1 AND calibration_id = ? LIMIT 1",
                    (capture["calibration_id"],),
                )
            )
        four_corner = False
        if self._calibration is not None:
            with contextlib.suppress(Exception):
                four_corner = self._calibration.active().mode == "four_corner"
        snap = _Snapshot(
            at=self._clock.now(), cover=cover, nodes=by_id, readings=readings, latest=latest, capture=capture,
            metrics=metrics, baseline_ok=baseline_ok, four_corner=four_corner, camera_online=camera_online,
            cfg=self._settings,
        )  # fmt: skip
        return snap

    # ---- the maths (pure over the snapshot) -----------------------------------------------------------
    def _zone_state(self, snap: _Snapshot, zone_id: str) -> _ZoneState:
        """A6: each sensor stressor is the maximum over the covering nodes; vegetation is N2 from the
        latest metrics against the baseline (unmeasured without one)."""
        stressors: dict[str, float | None] = dict.fromkeys(STRESSORS)
        summary: dict[str, float] = {}
        driver: dict[str, str] = {}
        for n in snap.cover.get(zone_id, []):
            r = snap.readings.get(n) or {}
            for s, score in snap.node_stressors(n).items():
                cur = stressors[s]
                if cur is None or score > cur:
                    stressors[s] = score
                    summary[s] = r[BAND_KEY[s]]
                    driver[s] = n
        zm = snap.metrics.get(zone_id)
        if snap.baseline_ok and zm is not None:
            stressors["vegetation"] = vegetation_decline(
                zm.canopy_loss_pp, zm.dieback_pct, zm.vari_drop, self._settings
            )
        return _ZoneState(stressors, summary, driver)

    def _build(
        self,
        snap: _Snapshot,
        zone_id: str,
        interp: _Interpretation,
        early_warning: bool,
        capture_id: str | None,
    ) -> m.Assessment | None:
        cfg = self._settings
        st = self._zone_state(snap, zone_id)
        measured = {k for k, v in st.stressors.items() if v is not None}
        if not measured:
            return None  # N3.5: no assessment; the zone shows "no data"
        weights = effective_weights(self._base, interp.multipliers, measured, cfg)
        if not weights:
            return None
        score, cls = risk(st.stressors, weights, cfg)
        multipliers = {k: float(interp.multipliers.get(k, 1.0)) for k in sorted(measured)}
        conf = self._confidence(snap, zone_id, measured, interp.source.tier)
        cap = snap.capture
        return m.Assessment(
            id=uuid7(), zone_id=zone_id, at=to_iso(self._clock.now()),
            capture_id=capture_id or (cap["id"] if cap is not None and "vegetation" in measured else None),
            stressors=st.stressors, multipliers=multipliers, weights=weights, risk_score=score,
            risk_class=cls, confidence=conf, early_warning=early_warning, narrative=interp.narrative,
            root_causes=list(interp.root_causes), actions=list(interp.actions), source=interp.source,
            observations=list(interp.observations), observations_source=interp.observations_source,
        )  # fmt: skip

    def _confidence(self, snap: _Snapshot, zone_id: str, measured: set[str], tier: str) -> m.Confidence:
        cfg = self._settings
        cap = snap.capture
        if cap is None or not snap.baseline_ok or zone_id not in snap.metrics:
            # Review Focus 4: no camera measurement of this zone against a baseline yet -> low confidence
            camera = camera_confidence(False, 0.0, snap.camera_online, False, snap.four_corner, False, cfg)
        else:
            age = max(0.0, (snap.at - from_iso(cap["taken_at"])).total_seconds())
            locked = bool((cap.get("quality") or {}).get("exposure_locked"))
            camera = camera_confidence(
                bool(cap["evidence_grade"]), age, snap.camera_online, locked, snap.four_corner, True, cfg
            )
        states = []
        for n in snap.cover.get(zone_id, []):
            row = snap.nodes.get(n)
            t = snap.latest.get(n)
            interval = float(getattr(row, "interval_s", None) or cfg.demo_values().baseline_interval_s)
            age = None if t is None else max(0.0, (snap.at - from_iso(t.sampled_at)).total_seconds())
            battery = None if t is None else (t.health or {}).get("battery_pct")
            faulty = t is not None and any((f or {}).get("kind") in ("stuck", "spike") for f in t.flags or [])
            online = getattr(row, "status", None) == "online"
            states.append(NodeHealthView(online, battery, age, interval, faulty))
        wsum = sum(self._base.get(s, 0.0) for s in measured if s in SENSOR_STRESSORS)
        sensor = sensor_confidence(wsum, states, False, cfg)
        prediction = tier_factor(tier, cfg)
        return m.Confidence(
            camera=camera,
            sensor=sensor,
            prediction=prediction,
            overall=overall(camera, sensor, prediction, cfg),
        )


def _fingerprint(a: m.Assessment) -> tuple[Any, ...]:
    return (
        a.risk_class, round(a.risk_score, 1), a.early_warning, a.source.ai_call_id, a.narrative,
        tuple(sorted((k, None if v is None else round(v, 2)) for k, v in a.stressors.items())),
        round(a.confidence.overall, 2),
    )  # fmt: skip


def observations_of(
    zone_id: str, observations: list[Any], source: m.SourceChip
) -> tuple[list[m.VisionObservationView], m.SourceChip]:
    """The zone's own VisionAnalyst observations (kind, confidence, text) and the chip of the answering tier."""
    mine = [
        m.VisionObservationView(kind=o.kind, confidence=o.confidence, text=o.text)
        for o in observations
        if o.zone_id == zone_id
    ]
    return mine, source


# ---- rows ------------------------------------------------------------------------------------------
def _to_row(a: m.Assessment) -> dict[str, Any]:
    return {
        "id": a.id, "zone_id": a.zone_id, "at": a.at, "capture_id": a.capture_id, "stressors": a.stressors,
        "multipliers": a.multipliers, "weights": a.weights, "risk_score": a.risk_score,
        "risk_class": a.risk_class, "confidence": a.confidence.model_dump(), "early_warning": a.early_warning,
        "narrative": a.narrative, "root_causes": [c.model_dump() for c in a.root_causes], "actions": a.actions,
        "tier": a.source.tier, "model": a.source.model, "cached": a.source.cached,
        "ai_call_id": a.source.ai_call_id,
        "observations": {
            "items": [o.model_dump() for o in a.observations],
            "source": a.observations_source.model_dump() if a.observations_source else None,
        },
    }  # fmt: skip


def _from_row(r: dict[str, Any]) -> m.Assessment:
    return m.Assessment(
        id=r["id"], zone_id=r["zone_id"], at=r["at"], capture_id=r["capture_id"], stressors=r["stressors"],
        multipliers=r["multipliers"], weights=r["weights"], risk_score=r["risk_score"],
        risk_class=r["risk_class"], confidence=m.Confidence.model_validate(r["confidence"]),
        early_warning=bool(r["early_warning"]), narrative=r["narrative"] or "",
        root_causes=[m.RootCause.model_validate(c) for c in r["root_causes"] or []], actions=r["actions"] or [],
        source=m.SourceChip(tier=r["tier"], model=r["model"], cached=bool(r["cached"]), ai_call_id=r["ai_call_id"]),
        observations=[m.VisionObservationView.model_validate(o) for o in (r.get("observations") or {}).get("items", [])],
        observations_source=(
            m.SourceChip.model_validate(r["observations"]["source"])
            if (r.get("observations") or {}).get("source")
            else None
        ),
    )  # fmt: skip
