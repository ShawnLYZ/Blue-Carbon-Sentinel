"""Eligibility tracker and automatic Verified issuance (spec 23; addendum A6, I3, N4, N8, N12).

For every planted zone of each applied plan version that has a Projected record, four rules:

1. **Camera** (``camera_rule``): the trailing run of evidence-grade captures after the capture at
   application that show recovery (new growth >= 3 % of the zone, or canopy +5 pp versus the capture at
   application; ``config/thresholds.yaml``) is at least 3 long.
2. **Sensors** (``SensorWindow``): every covering node's N1 stressors (water stressors from covering WQ
   nodes, porewater from covering SP nodes; coverage N9 / A6) stay < 0.3 and every covering node stays
   online for the N12 window (120 s with demo time on). Any stressor >= 0.3 or a covering node offline
   resets the window. With no covering node the rule fails with "no coverage" and the zone is noted as
   needing coverage, so ``GET /coverage`` carries the gap advice.
3. **Confidence**: the zone's N4 ledger confidence (``LedgerService.zone_confidence`` with the prediction
   component of the forecast behind the Projected record) is >= 0.80 (``config/risk.yaml``).
4. **Chain**: issuance is not blocked; and just before issuing, a full chain verification over the stored
   rows passes (the app also verifies once at startup, before the evaluator starts, so a row tampered with
   before a restart still blocks).

When all four pass, a Verified record is appended for that zone: it references the Projected record and
carries the A6 verification ratio, quantity = the Projected zone net x ratio (3 dp half-even, N8), the
Projected record's AI provenance and the demo time scale. At most one Verified record per (plan, zone)
across all plan versions (ruling: a re-applied plan never credits a zone twice), read from the stored
records' canonical content. A failed issuance attempt backs off ``RETRY_S`` on the clock for that
(Projected record, zone). ``ZoneEligibility.reason`` carries blocking reasons the per-rule fields do not
(already verified, no expected recovery, an issuance retry pending).

Evaluation is event-driven (captures, zone metrics and assessments, node telemetry and status, ledger
and plan changes) plus a 1 s tick on the injected clock so the sensor window keeps advancing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, NamedTuple, TypeVar

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.core.aio import to_thread_settled
from bcs_gs.fusion.bands import BAND_KEY, SENSOR_STRESSORS, sensor_stress
from bcs_gs.ledger.canonical import fmt_frac, fmt_pct, fmt_tco2e
from bcs_gs.ledger.contents import stored_contents, verified_key
from bcs_gs.nodes.coverage import by_zone
from bcs_gs.restoration.catalogue import PLANT_KINDS
from bcs_gs.vegetation.metrics import ZoneMetricsRow

log = logging.getLogger("bcs_gs.ledger.eligibility")

T = TypeVar("T")

NEED_CAPTURES = 3
HEALTHY_BELOW = 0.3  # N8: every stressor < 0.3
TICK_S = 1.0
RETRY_S = 30.0  # back-off after a failed issuance attempt, per (Projected record, zone), on the clock
_Q3 = Decimal("0.001")
EXPECTED_FLOOR_PP = Decimal("1.0")  # A6
SOIL_STRESSORS = ("porewater_salinity",)
WATER_STRESSORS = tuple(s for s in SENSOR_STRESSORS if s not in SOIL_STRESSORS)
TRIGGERS = frozenset({
    "capture.created", "zone.metrics", "zone.assessed", "node.telemetry", "node.status", "ledger.appended",
    "ledger.verified", "plan.updated", "coverage.updated",
})  # fmt: skip


# ---- rule 1: camera ---------------------------------------------------------------------------------
class CameraRuleState(NamedTuple):
    have: int
    ok: bool


def shows_recovery(
    row: ZoneMetricsRow, at_application: ZoneMetricsRow, new_growth_pct: float = 3.0, canopy_pp: float = 5.0
) -> bool:
    return row.new_growth_pct >= new_growth_pct or row.canopy_pct - at_application.canopy_pct >= canopy_pp


def recovery_run(
    evidence_metrics_since_application: Sequence[ZoneMetricsRow], at_application: ZoneMetricsRow,
    new_growth_pct: float = 3.0, canopy_pp: float = 5.0,
) -> list[ZoneMetricsRow]:  # fmt: skip
    """The trailing run (oldest first) of captures showing recovery."""
    run: list[ZoneMetricsRow] = []
    for row in reversed(evidence_metrics_since_application):
        if not shows_recovery(row, at_application, new_growth_pct, canopy_pp):
            break
        run.append(row)
    return run[::-1]


def camera_rule(
    evidence_metrics_since_application: Sequence[ZoneMetricsRow], at_application: ZoneMetricsRow,
    new_growth_pct: float = 3.0, canopy_pp: float = 5.0,
) -> CameraRuleState:  # fmt: skip
    """Rule 1: the trailing run of evidence-grade captures showing recovery, needing 3 (``have`` caps at 3)."""
    n = len(recovery_run(evidence_metrics_since_application, at_application, new_growth_pct, canopy_pp))
    return CameraRuleState(min(n, NEED_CAPTURES), n >= NEED_CAPTURES)


# ---- rule 2: sensors --------------------------------------------------------------------------------
class SensorRuleState(NamedTuple):
    healthy_s: float
    ok: bool
    reason: str | None


class SensorWindow:
    """The continuous healthy time of a zone's covering nodes (N8, N12)."""

    def __init__(self, window_s: float) -> None:
        self.window_s = float(window_s)
        self.since: datetime | None = None  # start of the current healthy run
        self._last_reset: str | None = None  # why the window last restarted, shown until it passes

    def observe(
        self, at: datetime, stressors_by_node: dict[str, dict[str, float]], covering: list[str],
        online: dict[str, bool], went_offline: Sequence[str] = (),
    ) -> SensorRuleState:  # fmt: skip
        """``went_offline``: covering nodes that went offline since the previous observation, even if they
        are back online now (N8: a node going offline resets the window, however briefly)."""
        if not covering:
            self.since, self._last_reset = None, None
            return SensorRuleState(0.0, False, "no coverage")
        bad = self._unhealthy(stressors_by_node, covering, online)
        flipped = sorted(n for n in went_offline if n in covering)
        if bad is None and flipped:
            bad = f"{flipped[0]} went offline"
        if bad is not None:
            self.since, self._last_reset = None, bad
            return SensorRuleState(0.0, False, bad)
        if self.since is None:
            self.since = at
        healthy = max(0.0, (at - self.since).total_seconds())
        ok = healthy >= self.window_s
        why = None if ok or self._last_reset is None else f"window restarted: {self._last_reset}"
        return SensorRuleState(healthy, ok, why)

    @staticmethod
    def _unhealthy(
        stressors_by_node: dict[str, dict[str, float]], covering: list[str], online: dict[str, bool]
    ) -> str | None:
        for n in sorted(covering):
            if not online.get(n, False):
                return f"{n} offline"
        for n in sorted(covering):
            values = stressors_by_node.get(n) or {}
            if not values:
                return f"no readings from {n}"
            for s, v in sorted(values.items()):
                if v >= HEALTHY_BELOW:
                    return f"{n} {s} stress {v:.2f} >= {HEALTHY_BELOW}"
        return None


# ---- the evaluator ----------------------------------------------------------------------------------
@dataclass
class _ZoneEval:
    projected_id: str
    projected: dict[str, Any]  # the Projected record's content
    plan: dict[str, Any]
    zone: str
    application: dict[str, Any] | None  # the capture at application (id, taken_at)
    app_metrics: ZoneMetricsRow | None
    qualifying: list[tuple[dict[str, Any], ZoneMetricsRow]]  # the trailing recovery run (capture, metrics)
    window_since: datetime | None
    confidence: dict[str, float]
    expected_pp: Decimal | None
    verified: bool  # the plan already has a Verified record for the zone (any version)
    eligibility: m.ZoneEligibility


class EligibilityEvaluator:
    def __init__(
        self, *, repo: Any, bus: Any, clock: Any, settings: Any, ledger: Any, forecasts: Any, ingest: Any,
        registry: Any, tasking: Any, grid: Any, site_id: str,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._clock, self._settings = repo, bus, clock, settings
        self._ledger, self._forecasts, self._ingest, self._registry = ledger, forecasts, ingest, registry
        self._tasking, self._grid, self._site_id = tasking, grid, site_id
        self._lock = asyncio.Lock()
        self._sub: Any = None
        self._wake: asyncio.Event | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._gen = 0  # bumped by reset(): an evaluation begun before a reset writes nothing after it
        self.running = False
        self.reset()

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        """Start listening, ticking and evaluating. The app verifies the chain once (``startup_verify``)
        before it starts the evaluator; the test reset starts it again once the store is cleared."""
        self.running = True
        self._sub = self._bus.subscribe(10000)
        self._wake = asyncio.Event()
        self._wake.set()
        self._tasks = [
            asyncio.create_task(self._listen(), name="eligibility-listen"),
            asyncio.create_task(self._tick(), name="eligibility-tick"),
            asyncio.create_task(self._work(), name="eligibility-work"),
        ]

    async def stop(self) -> None:
        """Stop and wait until no evaluation or issuance is in flight (shutdown; the test reset stops it
        before clearing the store and starts it again afterwards, ruling R30)."""
        self.running = False
        if self._sub is not None:
            self._sub.close()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []

    def reset(self) -> None:
        self._gen += 1
        self._windows: dict[tuple[str, str], SensorWindow] = {}
        self._status: list[m.ZoneEligibility] = []
        self._offline_seen: dict[tuple[str, str], dict[str, int]] = {}  # window -> node -> last offline event
        self._expected: dict[tuple[str, str], Decimal] = {}  # (forecast, zone) -> expected_pp (A6)
        self.blocked: dict[tuple[str, str], str] = {}  # (Projected, zone) -> why issuance cannot happen
        self._retry_at: dict[tuple[str, str], datetime] = {}  # (Projected, zone) -> no attempt before this

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                if ev.type in TRIGGERS and self._wake is not None:
                    self._wake.set()
            if not sub.overflowed:
                return  # closed by stop()
            log.warning("eligibility event subscription overflowed; resubscribing")
            self._sub = self._bus.subscribe(10000)

    async def _tick(self) -> None:
        while True:
            await self._clock.sleep(TICK_S)
            if self._wake is not None:
                self._wake.set()

    async def _work(self) -> None:
        assert self._wake is not None
        while True:
            await self._wake.wait()
            self._wake.clear()
            try:
                await self.evaluate()
            except Exception:
                log.exception("eligibility evaluation failed")

    # ---- evaluation ---------------------------------------------------------------------------------
    def status(self) -> list[m.ZoneEligibility]:
        """The latest evaluation (I3 ZoneEligibility per planted zone of each Projected plan)."""
        return list(self._status)

    async def evaluate(self) -> list[m.ZoneEligibility]:
        """Evaluate every tracked zone now and issue the Verified records that are due."""
        async with self._lock:
            if not self.running:  # stopped (shutdown, or a test reset in progress): no reads, no writes
                return list(self._status)
            gen = self._gen
            zones = await to_thread_settled(self._evaluate_sync, gen)
            if gen != self._gen:
                return []
            self._status = [z.eligibility for z in zones]
            for z in zones:
                retry = self._retry_at.get((z.projected_id, z.zone))
                if retry is not None and self._clock.now() < retry:
                    continue  # a recent attempt failed: wait (its ledger.verified event woke us at once)
                if z.eligibility.eligible and not z.verified and not self._ledger.issuance_blocked:
                    await _settled(self._issue(z, gen))
            if self._ledger.issuance_blocked:  # a verification just failed: the chain rule fails
                self._status = [
                    e.model_copy(update={"chain": m.ChainEligibility(ok=False), "eligible": False})
                    for e in self._status
                ]
            return list(self._status)

    async def _issue(self, z: _ZoneEval, gen: int) -> None:
        key = (z.projected_id, z.zone)
        try:
            v = await self._ledger.verify_chain()  # rule 4: a real verification over the stored rows
            if not v.intact:
                return
            content = await to_thread_settled(self._verified_content, z)
            if gen != self._gen or not self.running:
                return  # a reset happened meanwhile: its Projected record is gone
            await self._ledger.append(content)
            self._retry_at.pop(key, None)
        except Exception:
            if gen == self._gen:
                self._retry_at[key] = self._clock.now() + timedelta(seconds=RETRY_S)
            log.exception("Verified issuance failed for %s %s; retrying in %.0f s", *key, RETRY_S)

    def _evaluate_sync(self, gen: int) -> list[_ZoneEval]:
        now = self._clock.now()
        nodes = self._registry.nodes()
        cover = by_zone(nodes, self._grid)
        rows = {n.id: n for n in nodes}
        window_s = float(self._settings.demo_values().verified_sensor_window_s)
        need_conf = float(self._settings.risk.confidence.get("verified_min_confidence", 0.8))
        flags = self._settings.thresholds.flags
        chain_ok = not self._ledger.issuance_blocked
        out: list[_ZoneEval] = []
        seen: set[tuple[str, str]] = set()
        projected, verified = self._records()
        for rid, content in projected:
            ev = content.get("evidence") or {}
            plan = self._plan(ev.get("plan_id"), ev.get("plan_version"))
            if plan is None:
                continue
            app = self._capture(plan["capture_at_application_id"])
            for zone in _planted(plan, content.get("zone_ids") or []):
                key = (rid, zone)
                seen.add(key)
                # rule 1
                app_m, after = self._metrics_since(zone, app)
                run_m = recovery_run([x for _, x in after], app_m, flags.new_growth_pct, flags.new_growth_canopy_pp) \
                    if app_m is not None else []  # fmt: skip
                qualifying = after[len(after) - len(run_m):] if run_m else []
                cam = CameraRuleState(min(len(run_m), NEED_CAPTURES), len(run_m) >= NEED_CAPTURES)
                # rule 2
                water, soil = cover.get(zone, {}).get("water", []), cover.get(zone, {}).get("soil", [])
                covering = [*water, *soil]
                if not covering and gen == self._gen:
                    self._tasking.note_zone_needing(zone)  # the gap advice in GET /coverage
                stressors = {
                    n: self._node_stressors(n, rows.get(n), SOIL_STRESSORS if n in soil else WATER_STRESSORS)
                    for n in covering
                }
                online = {n: getattr(rows.get(n), "status", None) == "online" for n in covering}
                win = self._windows.get(key)
                if win is None:
                    win = self._windows[key] = SensorWindow(window_s)
                win.window_s = window_s
                marks = self._offline_marks(covering)
                prev = self._offline_seen.setdefault(key, dict(marks))  # a new window starts from now
                went = [n for n in covering if marks.get(n, 0) > prev.get(n, 0)]
                self._offline_seen[key] = marks
                sens = win.observe(now, stressors, covering, online, went)
                # rule 3
                pred = _float(((content.get("confidence") or {}).get("zones") or {}).get(zone, {}).get("prediction"))
                conf = self._ledger.zone_confidence(zone, pred)
                value = round(float(conf["overall"]), 4)
                conf_ok = value >= need_conf
                # the A6 denominator: without it there is no honest ratio, so no issuance
                expected = self._expected_pp((content.get("evidence") or {}).get("forecast_id"), zone)
                done = verified.get((plan["plan_id"], zone))
                retry = self._retry_at.get(key)
                reason = None
                if expected is None:
                    why = "expected recovery unavailable: no 2026/2027 forecast canopy for the zone"
                    if self.blocked.get(key) != why:
                        log.warning("Verified issuance blocked for %s %s: %s", rid, zone, why)
                    self.blocked[key] = why
                    reason = why
                else:
                    self.blocked.pop(key, None)
                if done is not None:
                    reason = f"already verified for this plan: {done}"
                elif reason is None and retry is not None and now < retry:
                    reason = f"issuance failed; retrying after {RETRY_S:.0f} s"
                elig = m.ZoneEligibility(
                    zone_id=zone, plan_id=plan["plan_id"],
                    camera=m.CameraEligibility(have=cam.have, ok=cam.ok),
                    sensors=m.SensorEligibility(healthy_s=round(sens.healthy_s, 1), need_s=window_s, ok=sens.ok,
                                                reason=sens.reason),
                    confidence=m.ConfidenceEligibility(value=value, need=need_conf, ok=conf_ok),
                    chain=m.ChainEligibility(ok=chain_ok),
                    eligible=cam.ok and sens.ok and conf_ok and chain_ok and expected is not None,
                    reason=reason,
                )  # fmt: skip
                out.append(_ZoneEval(
                    projected_id=rid, projected=content, plan=plan, zone=zone, application=app,
                    app_metrics=app_m, qualifying=qualifying, window_since=win.since, confidence=conf,
                    expected_pp=expected, verified=done is not None, eligibility=elig,
                ))  # fmt: skip
        for key in list(self._windows):
            if key not in seen:
                del self._windows[key]
                self._offline_seen.pop(key, None)
        for key in list(self._retry_at):
            if key not in seen:
                del self._retry_at[key]
        return out

    # ---- reads (blocking) ---------------------------------------------------------------------------
    def _records(self) -> tuple[list[tuple[str, dict[str, Any]]], dict[tuple[str, str], str]]:
        """(the Projected records as (record ID, content), (plan, zone) -> its first Verified record ID),
        read from the canonical content in chain order (never the editable display columns)."""
        projected: list[tuple[str, dict[str, Any]]] = []
        verified: dict[tuple[str, str], str] = {}
        for _, content in stored_contents(self._repo):
            rid = content.get("record_id")
            if not isinstance(rid, str):
                continue  # unreadable: chain verification reports it
            if content.get("type") == "projected":
                projected.append((rid, content))
            elif (key := verified_key(content)) is not None:
                verified.setdefault(key, rid)
        return projected, verified

    def _plan(self, plan_id: Any, version: Any) -> dict[str, Any] | None:
        """The plan version behind a Projected record, while it is the applied one."""
        if not isinstance(plan_id, str) or not isinstance(version, int):
            return None
        rows = self._repo.query(
            "SELECT * FROM restoration_plans WHERE plan_id = ? AND version = ? AND status = 'applied'",
            (plan_id, version), table="restoration_plans",
        )  # fmt: skip
        return rows[0] if rows else None

    def _capture(self, capture_id: str | None) -> dict[str, Any] | None:
        if not capture_id:
            return None
        rows = self._repo.query("SELECT id, taken_at FROM captures WHERE id = ?", (capture_id,))
        return rows[0] if rows else None

    def _zone_metrics(self, capture_id: str, zone: str) -> ZoneMetricsRow | None:
        row = self._repo.get("zone_metrics", {"capture_id": capture_id, "zone_id": zone})
        if row is None:
            return None
        return ZoneMetricsRow.model_validate({k: v for k, v in row.items() if k in ZoneMetricsRow.model_fields})

    def _metrics_since(
        self, zone: str, app: dict[str, Any] | None
    ) -> tuple[ZoneMetricsRow | None, list[tuple[dict[str, Any], ZoneMetricsRow]]]:
        """(the zone at application, the zone in the latest 3 evidence-grade captures after it, oldest
        first). Only the latest 3 can form the trailing run that rule 1 needs."""
        if app is None:
            return None, []
        app_m = self._zone_metrics(app["id"], zone)
        caps = self._repo.query(
            "SELECT id, taken_at FROM captures WHERE evidence_grade = 1 "
            "AND (taken_at > ? OR (taken_at = ? AND id > ?)) ORDER BY taken_at DESC, id DESC LIMIT ?",
            (app["taken_at"], app["taken_at"], app["id"], NEED_CAPTURES),
        )  # fmt: skip
        after = []
        for c in reversed(caps):
            zm = self._zone_metrics(c["id"], zone)
            if zm is not None:
                after.append((c, zm))
        return app_m, after

    def _node_stressors(self, node_id: str, row: Any, keys: Sequence[str]) -> dict[str, float]:
        """N1 stressors of a covering node from its robust readings."""
        if row is None:
            return {}
        readings = self._ingest.robust_all(node_id, getattr(row, "mode", None) or "baseline")
        return {
            s: sensor_stress(s, readings[BAND_KEY[s]], self._settings) for s in keys if BAND_KEY[s] in readings
        }

    def _offline_marks(self, node_ids: list[str]) -> dict[str, int]:
        """Per node, the row ID of its latest offline transition (the ingest's ``ground_station`` node
        event). It is stored before the status message counts as handled, so a quick offline -> online
        flip between two evaluations is still seen."""
        if not node_ids:
            return {}
        qs = ", ".join("?" * len(node_ids))
        rows = self._repo.query(
            "SELECT node_id, MAX(rowid) AS mark FROM node_events WHERE origin = 'ground_station' "
            f"AND kind = 'offline' AND node_id IN ({qs}) GROUP BY node_id",
            tuple(node_ids),
        )  # fmt: skip
        return {r["node_id"]: int(r["mark"]) for r in rows}

    # ---- the Verified record (blocking) -------------------------------------------------------------
    def _expected_pp(self, forecast_id: Any, zone: str) -> Decimal | None:
        """A6: 100 x (C_with,2027 - C_with,2026) for the zone, floor 1.0 pp (for a small real delta).
        None when the forecast cannot be read or lacks those points: no ratio can be computed, so
        issuance waits. The floor is never a stand-in (it would credit the full Projected quantity)."""
        if not isinstance(forecast_id, str):
            return None
        key = (forecast_id, zone)
        if key in self._expected:
            return self._expected[key]
        try:
            forecast = self._forecasts.get(forecast_id)
        except ApiError:  # not_found
            return None
        pts = {p.year: p for p in forecast.scenarios.with_.zones.get(zone, [])}
        if forecast.status != "ready" or 2026 not in pts or 2027 not in pts:
            return None
        pp = Decimal(str(round(100 * (pts[2027].canopy.central - pts[2026].canopy.central), 4)))
        self._expected[key] = max(pp, EXPECTED_FLOOR_PP)  # a ready forecast never changes
        return self._expected[key]

    def _verified_content(self, z: _ZoneEval) -> dict[str, Any]:
        p = z.projected
        ev = p.get("evidence") or {}
        assert z.app_metrics is not None and z.application is not None and z.qualifying
        last = z.qualifying[-1][1]  # A6: measured on the last of the qualifying captures
        new_growth = Decimal(str(round(last.new_growth_pct, 4)))
        gain = Decimal(str(round(last.canopy_pct - z.app_metrics.canopy_pct, 4)))
        observed = max(new_growth, gain)
        expected = z.expected_pp
        assert expected is not None  # a zone without it is never eligible
        ratio = Decimal(fmt_frac(min(Decimal(1), observed / expected)))
        zq = (p.get("zone_quantities") or {})[z.zone]

        def scaled(key: str) -> str:  # half-even to 3 dp, as the Projected quantities (carbon.deductions)
            return fmt_tco2e((Decimal(zq[key]) * ratio).quantize(_Q3, ROUND_HALF_EVEN))

        deductions = p.get("deductions") or {}
        conf = z.confidence
        captures = [{"id": z.application["id"], "role": "application", "taken_at": z.application["taken_at"]}]
        captures += [{"id": c["id"], "role": "qualifying", "taken_at": c["taken_at"]} for c, _ in z.qualifying]
        return {
            "type": "verified",
            "site_id": self._site_id,
            "zone_ids": [z.zone],
            "period": p.get("period"),
            "projected_record_id": z.projected_id,
            "verification_ratio": fmt_frac(ratio),
            "verification": {
                "expected_pp": fmt_pct(expected), "observed_pp": fmt_pct(observed),
                "new_growth_pct": fmt_pct(new_growth), "canopy_gain_pp": fmt_pct(gain),
            },
            "quantity_tco2e": scaled("net_tco2e"),
            "gross_tco2e": scaled("gross_tco2e"),
            "deductions": {
                "buffer_pct": deductions.get("buffer_pct"), "buffer_tco2e": scaled("buffer_tco2e"),
                "uncertainty_fraction": zq["uncertainty_fraction"], "uncertainty_tco2e": scaled("uncertainty_tco2e"),
            },
            "confidence": {
                "overall": fmt_frac(_dec4(conf["overall"])),
                "zones": {z.zone: {k: fmt_frac(_dec4(v)) for k, v in conf.items()}},
            },
            "evidence": {
                "captures": captures,
                "telemetry_window": self._ledger.telemetry_window([z.zone], start=z.window_since),
                "forecast_id": ev.get("forecast_id"),
                "plan_id": z.plan["plan_id"],
                "plan_version": z.plan["version"],
                "ai_calls": ev.get("ai_calls") or [],  # the Projected record's AI provenance, hashed here too
            },
            "demo_time_scale": self._settings.demo_time_scale == "on",
        }


def _planted(plan: dict[str, Any], zone_ids: list[str]) -> list[str]:
    planted = {
        i["zone_id"]
        for i in plan["items"] or []
        if any((iv or {}).get("kind") in PLANT_KINDS for iv in i.get("interventions") or [])
    }
    return sorted(planted & set(zone_ids))


def _float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _dec4(x: float) -> Decimal:
    return Decimal(str(round(float(x), 4)))


async def _settled(aw: Awaitable[T]) -> T:
    """Await ``aw`` in its own task; a cancellation waits for it to finish first (a ledger write never
    lands after a test reset cleared the tables; ruling R30)."""
    fut = asyncio.ensure_future(aw)
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        while not fut.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait({fut})
        if not fut.cancelled():
            fut.exception()
        raise
