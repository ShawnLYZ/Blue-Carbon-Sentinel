"""AlertService (spec 25; addendum H2 ``alerts``, I3 Alert, J2 ``alert.created`` / ``alert.acknowledged``).

Alerts are raised from events on the bus, the camera link and the sync worker. Duplicates share a
dedupe key (see ``rules.py``): inside the rule's window, or while unacknowledged when the rule has no
window, a duplicate only increments ``occurrences`` and ``last_seen_at``. Windows are measured on the
injected Clock from the first occurrence. An acknowledged alert is never reused: the next occurrence
is a new alert.

``raise_`` is synchronous (one short SQLite write) and publishes on the caller's thread, so call it on
the event loop; the callbacks from other services (camera link, sync worker) are marshalled onto it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso

from bcs_gs.alerts.rules import ALERT_RULES
from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.core.clock import Clock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.fusion.early_warning import EARLY_WARNING_REASON
from bcs_gs.store.repo import Repo

log = logging.getLogger("bcs_gs.alerts")

DEGRADED_TIERS = ("gemma_local", "rules")
TIER_LABELS = {"gemma_local": "local Gemma", "rules": "the rules tier"}
ANOMALY_KINDS = ("anomaly", "threshold", "stuck")
TERMINAL_TASK_STATUSES = ("completed", "expired", "cancelled")
FLAG_UNITS = {
    "canopy_loss": ("canopy loss", "pp"),
    "dieback": ("dieback", "%"),
    "index_drop": ("VARI drop", ""),
    "discolouration": ("discolouration", "%"),
    "new_growth": ("new growth", "pp"),
}
PARAMETER_LABELS = {
    "turbidity_ntu": ("turbidity", "NTU"),
    "salinity_psu": ("salinity", "PSU"),
    "porewater_salinity_psu": ("porewater salinity", "PSU"),
    "do_mg_l": ("dissolved oxygen", "mg/L"),
    "temp_c": ("temperature", "°C"),
    "ph": ("pH", ""),
    "soil_moisture_pct": ("soil moisture", "%"),
    "water_level_cm": ("water level", "cm"),
}
ROLE_LABELS = {
    "vision_analyst": "Vision analyst",
    "risk_interpreter": "Risk interpreter",
    "tree_locator": "Tree locator",
    "forecast_parameter_estimator": "Forecast estimator",
    "restoration_planner": "Restoration planner",
    "history_synthesizer": "History synthesizer",
}
SEEN_TASKS_MAX = 2000


def _num(x: float | None, digits: int = 1) -> str:
    return "?" if x is None else f"{x:.{digits}f}"


def _with_unit(value: float | None, unit: str) -> str:
    return f"{_num(value)} {unit}".strip()


def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else from_iso(value)


class AlertService:
    def __init__(self, repo: Repo, bus: EventBus, clock: Clock, settings: Settings | None = None) -> None:
        self._repo = repo
        self._bus = bus
        self._clock = clock
        self._settings = settings
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sub: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._started_tasks: dict[str, None] = {}  # task ids already announced as started
        self._risk_class: dict[str, str] = {}  # zone -> last assessed risk class (risk_critical = entering)

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self, *, camera: Any = None) -> None:
        self._loop = asyncio.get_running_loop()
        self._sub = self._bus.subscribe(10000)
        self._listener = asyncio.create_task(self._listen(), name="alerts-listen")
        if camera is not None:
            camera.on_offline(self._camera_offline)
            camera.on_online(self._camera_online)

    async def stop(self) -> None:
        if self._sub is not None:
            self._sub.close()
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
            self._listener = None

    def reset(self) -> None:
        """Forget the in-memory state (test reset clears the tables)."""
        self._started_tasks.clear()
        self._risk_class.clear()

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                try:
                    self._on_event(ev.type, ev.data)
                except Exception:
                    log.exception("alerts failed on %s", ev.type)
            if not sub.overflowed:
                return  # closed by stop()
            log.warning("alert event subscription overflowed; resubscribing")
            self._sub = self._bus.subscribe(10000)

    # ---- core ---------------------------------------------------------------------------------------
    def raise_(
        self,
        type: str,
        *,
        zone_id: str | None = None,
        node_id: str | None = None,
        message: str,
        details: dict[str, Any] | None = None,
        severity: str | None = None,
    ) -> m.Alert:
        """Raise an alert, or count a duplicate. Returns the stored alert (new, or the one counted)."""
        rule = ALERT_RULES.get(type)
        if rule is None:
            raise ValueError(f"unknown alert type {type!r}")
        details = dict(details or {})
        key = rule.dedupe_key(zone_id, node_id, details)
        now = self._clock.now()
        with self._lock:
            row = self._open_duplicate(key, now, rule.window_s)
            if row is not None:
                row["occurrences"] = int(row["occurrences"]) + 1
                row["last_seen_at"] = to_iso(now)
                self._repo.upsert("alerts", row)
                return self._model(row)
            row = {
                "id": uuid7(), "at": to_iso(now), "last_seen_at": to_iso(now), "occurrences": 1,
                "type": type, "severity": severity or rule.severity, "zone_id": zone_id, "node_id": node_id,
                "message": message, "dedupe_key": key, "details": details, "acknowledged_at": None,
            }  # fmt: skip
            self._repo.insert("alerts", row)
        alert = self._model(row)
        self._bus.publish("alert.created", alert.model_dump(mode="json"))
        return alert

    def _open_duplicate(self, key: str, now: datetime, window_s: int | None) -> dict[str, Any] | None:
        rows = self._repo.query(
            'SELECT * FROM "alerts" WHERE "dedupe_key" = ? AND "acknowledged_at" IS NULL '
            'ORDER BY "at" DESC LIMIT 1',
            (key,),
            table="alerts",
        )
        if not rows:
            return None
        row = rows[0]
        if window_s is not None and (now - _dt(row["at"])).total_seconds() >= window_s:
            return None
        return row

    def ack(self, alert_id: str) -> m.Alert:
        with self._lock:
            row = self._repo.get("alerts", {"id": alert_id})
            if row is None:
                raise ApiError("not_found", 404, f"No alert {alert_id}.")
            if row["acknowledged_at"] is not None:
                return self._model(row)  # already acknowledged: nothing new to announce
            row["acknowledged_at"] = to_iso(self._clock.now())
            self._repo.upsert("alerts", row)
        self._bus.publish("alert.acknowledged", {"id": alert_id, "acknowledged_at": row["acknowledged_at"]})
        return self._model(row)

    def list(self, unacknowledged: bool = False, limit: int = 100) -> list[m.Alert]:
        """Newest first (blocking)."""
        where = ' WHERE "acknowledged_at" IS NULL' if unacknowledged else ""
        rows = self._repo.query(
            f'SELECT * FROM "alerts"{where} ORDER BY "at" DESC, "rowid" DESC LIMIT ?',
            (limit,),
            table="alerts",
        )
        return [self._model(r) for r in rows]

    @staticmethod
    def _model(row: dict[str, Any]) -> m.Alert:
        return m.Alert.model_validate({k: v for k, v in row.items() if k != "dedupe_key"})

    # ---- event mapping ------------------------------------------------------------------------------
    def _on_event(self, type_: str, d: dict[str, Any]) -> None:
        handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "zone.flagged": self._zone_flagged,
            "zone.assessed": self._zone_assessed,
            "node.event": self._node_event,
            "node.status": self._node_status,
            "node.telemetry": self._node_telemetry,
            "ai.call": self._ai_call,
            "coverage.updated": self._coverage,
            "task.updated": self._task,
        }
        handler = handlers.get(type_)
        if handler is not None:
            handler(d)

    def _zone_flagged(self, d: dict[str, Any]) -> None:
        zone = d["zone_id"]
        flags = d.get("flags") or []
        parts = []
        for f in flags:
            label, unit = FLAG_UNITS.get(f.get("kind"), (str(f.get("kind")), ""))
            parts.append(f"{label} {_with_unit(f.get('value'), unit)}")
        what = ", ".join(parts) or "canopy change"
        self.raise_(
            "zone_flagged", zone_id=zone, message=f"{zone} flagged: {what}",
            details={"capture_id": d.get("capture_id"), "flags": flags},
        )  # fmt: skip

    def _zone_assessed(self, d: dict[str, Any]) -> None:
        zone = d["zone_id"]
        score = d.get("risk_score")
        cls = d.get("risk_class")
        previous = self._risk_class.get(zone)
        if cls:
            self._risk_class[zone] = cls
        if cls == "critical" and previous != "critical":  # entering Critical, not every critical assessment
            self.raise_(
                "risk_critical", zone_id=zone, message=f"{zone} risk critical: score {_num(score)} of 100",
                details={"assessment_id": d.get("id"), "risk_score": score},
            )  # fmt: skip
        if d.get("early_warning"):
            self.raise_(
                "early_warning", zone_id=zone,
                message=f"{zone}: {EARLY_WARNING_REASON}",
                details={"assessment_id": d.get("id"), "risk_score": score},
            )  # fmt: skip

    def _node_event(self, d: dict[str, Any]) -> None:
        if d.get("origin") != "node" or d.get("kind") not in ANOMALY_KINDS:
            return
        node, param, value = d["node_id"], d.get("parameter"), d.get("value")
        label, unit = PARAMETER_LABELS.get(param or "", (param or "reading", ""))
        z = f" (z {_num(d['score'])})" if d.get("score") is not None else ""
        if d["kind"] == "stuck":
            msg = f"{node} {label} sensor stuck at {_with_unit(value, unit)}"
        elif d["kind"] == "threshold":
            msg = f"{node} {label} past threshold: {_with_unit(value, unit)}{z}"
        else:
            msg = f"{node} {label} spike: {_with_unit(value, unit)}{z}"
        self.raise_(
            "node_anomaly", node_id=node, message=msg,
            details={"kind": d["kind"], "parameter": param, "value": value, "score": d.get("score")},
        )  # fmt: skip

    def _node_status(self, d: dict[str, Any]) -> None:
        if d.get("state") != "offline":
            return
        node = d["node_id"]
        reason = d.get("reason")
        self.raise_(
            "node_offline", node_id=node,
            message=f"{node} offline" + (f" ({reason.replace('_', ' ')})" if reason else ""),
            details={"reason": reason},
        )  # fmt: skip

    def _node_telemetry(self, d: dict[str, Any]) -> None:
        battery = (d.get("health") or {}).get("battery_pct")
        if battery is None:
            return
        common = self._settings.demo_time.common if self._settings is not None else {}
        if battery < float(common.get("battery_low_pct", 15)):
            node = d["node_id"]
            self.raise_(
                "node_low_battery", node_id=node, message=f"{node} battery low: {_num(battery)} %",
                details={"battery_pct": battery},
            )  # fmt: skip

    def _ai_call(self, d: dict[str, Any]) -> None:
        tier, role = d.get("tier"), d.get("role")
        if tier not in DEGRADED_TIERS or d.get("status") not in ("success", "cache_hit") or not role:
            return  # only the row that actually served the call counts
        self.raise_(
            "ai_degraded", message=f"{ROLE_LABELS.get(role, role)} answered by {TIER_LABELS[tier]}",
            details={"role": role, "tier": tier, "call_id": d.get("call_id")},
            severity="warning" if tier == "rules" else "info",
        )  # fmt: skip

    def _coverage(self, d: dict[str, Any]) -> None:
        for gap in d.get("gaps") or []:
            zone = gap["zone_id"]
            self.raise_(
                "coverage_gap", zone_id=zone,
                message=f"{zone} has no sensor coverage: place a {gap['node_type'].replace('_', ' ')} node",
                details={"node_type": gap["node_type"], "reason": gap.get("reason")},
            )  # fmt: skip

    def _task(self, d: dict[str, Any]) -> None:
        tid, status, zone = d["id"], d.get("status"), d.get("zone_id")
        where = f" in {zone}" if zone else ""
        if status in TERMINAL_TASK_STATUSES:
            self.raise_(
                "task_ended", zone_id=zone, message=f"Investigation{where} {status}",
                details={"task_id": tid, "status": status, "trigger": d.get("trigger")},
            )  # fmt: skip
        elif tid not in self._started_tasks:
            self._started_tasks[tid] = None
            while len(self._started_tasks) > SEEN_TASKS_MAX:
                self._started_tasks.pop(next(iter(self._started_tasks)))
            why = f": {d['reason']}" if d.get("reason") else ""
            self.raise_(
                "task_started", zone_id=zone, message=f"Investigation started{where}{why}",
                details={"task_id": tid, "trigger": d.get("trigger")},
            )  # fmt: skip

    # ---- callbacks from other services (any thread) -------------------------------------------------
    def _camera_offline(self, _status: Any) -> None:
        self._on_loop(self.raise_, "camera_offline", message="Camera offline: no frames for 3 s")

    def _camera_online(self, _status: Any) -> None:
        self._on_loop(self.raise_, "camera_online", message="Camera back online")

    def cloud_offline(self) -> None:
        """SyncWorker ``on_offline(True)``: uploads are buffering locally."""
        self._on_loop(self.raise_, "cloud_offline", message="Cloud sync offline: buffering uploads locally")

    def _on_loop(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._guarded(fn, *args, **kwargs)
        else:
            loop.call_soon_threadsafe(lambda: self._guarded(fn, *args, **kwargs))

    @staticmethod
    def _guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("alert callback failed")
