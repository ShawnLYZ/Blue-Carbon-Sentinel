"""Telemetry ingest (addendum G5) and the retained node configuration (G3, N1, N12).

Every message on ``bcs/v1/+/nodes/+/{telemetry,event,status,ack}`` is queued in arrival order and
processed one at a time by a single worker: the database work runs in a thread, then the resulting
``node.telemetry`` / ``node.status`` / ``node.event`` events and ``on_ack`` calls are made on the loop.
The silence watchdog and registry changes go through the same queue, so the in-memory node state is
only ever touched by that worker and needs no locking.

Processing (G5): parse, validate, check consistency (topic vs payload, registered and active node, node
type), check ranges (the schema), check ``sampled_at`` (at most 60 s ahead), dedupe on (node, boot, seq),
store, then publish. A failure in steps 1-5 writes a ``malformed`` Ground Station node event instead
of a reading. A unique violation is a duplicate and is dropped silently.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import statistics
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso
from bcs_protocol.topics import parse_topic, topic
from bcs_protocol.validate import READING_KEYS, Ack, NodeEvent, ProtocolError, Status, parse_message

from bcs_gs.core.clock import Clock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.store.repo import Repo

log = logging.getLogger("bcs_gs.ingest")

CHANNELS = ("telemetry", "event", "status", "ack")
FUTURE_TOLERANCE_S = 60  # G5 step 5
EXCERPT_MAX_BYTES = 2048
WATCHDOG_PERIOD_S = 1.0
# J2 ``node.telemetry`` data
TELEMETRY_EVENT_KEYS = (
    "node_id",
    "sampled_at",
    "mode",
    "readings",
    "health",
    "flags",
    "late",
    "source",
    "replay",
)
VERSIONS_KEY = "node_config_versions"  # local settings row: {node_id: last published config_version}

# N1: the values where "Critical" starts (stress 0.6). Bands are thresholds (G3): a reading below
# ``min`` or above ``max`` is critical, and crossing one raises a ``threshold`` flag. Soil moisture and
# water level are not stressors and have no band.
CRITICAL_BANDS: dict[str, dict[str, float]] = {
    "do_mg_l": {"min": 2.0},
    "ph": {"min": 6.5, "max": 9.0},
    "turbidity_ntu": {"max": 100.0},
    "salinity_psu": {"max": 45.0},
    "porewater_salinity_psu": {"max": 60.0},
    "temp_c": {"max": 36.0},
}
ANOMALY = {"window": 30, "z_threshold": 3.0, "stuck_window": 10}
# Stuck epsilon per reading: the G4 resolution.
STUCK_EPSILON = {
    "salinity_psu": 0.1, "turbidity_ntu": 0.1, "do_mg_l": 0.01, "temp_c": 0.01, "ph": 0.01,
    "porewater_salinity_psu": 0.1, "soil_moisture_pct": 0.1, "water_level_cm": 1.0,
}  # fmt: skip


@dataclass(frozen=True)
class TelemetryRow:
    id: str
    node_id: str
    boot_id: str
    seq: int
    sampled_at: str
    received_at: str
    mode: str
    readings: dict[str, float]
    health: dict[str, Any]
    flags: list[dict[str, Any]]
    source: str
    replay: bool
    late: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TelemetryRow:
        return cls(**{f: row[f] for f in cls.__dataclass_fields__})

    def point(self) -> dict[str, Any]:
        """I3 ``TelemetryPoint``."""
        return {"t": self.sampled_at, "mode": self.mode, "late": self.late, "readings": self.readings}

    def latest(self) -> dict[str, Any]:
        """I3 ``Node.latest``."""
        return {
            "sampled_at": self.sampled_at, "readings": self.readings, "health": self.health,
            "flags": self.flags, "late": self.late,
        }  # fmt: skip


@dataclass
class _NodeState:
    status: str
    mode: str | None
    interval_s: float | None
    boot_id: str | None
    last_activity: datetime  # last telemetry or online status, for the silence watchdog


@dataclass
class _Outcome:
    """What one processed item asks the loop to do afterwards."""

    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    acks: list[Ack] = field(default_factory=list)


class TelemetryIngest:
    def __init__(
        self,
        repo: Repo,
        registry: Any,
        bus: EventBus,
        clock: Clock,
        settings: Settings,
        *,
        site_id: str,
        on_ack: Callable[[Ack], Any] | None = None,
    ) -> None:
        self._repo, self._registry, self._bus = repo, registry, bus
        self._clock, self._settings, self._site_id = clock, settings, site_id
        self.on_ack = on_ack
        self._mqtt: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[tuple[str, Any, Any]] | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._registry_sub: Any = None
        self._nodes: dict[str, _NodeState] = {}
        self._handled: Counter[tuple[str, str]] = Counter()
        self._handled_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._versions: dict[str, int] | None = None
        self.ready = False  # subscribed and the initial configs are out
        self._busy = False

    # ---- lifecycle ---------------------------------------------------------------------------------
    async def start(self, mqtt: Any) -> None:
        """Subscribe to the four node channels on ``mqtt`` (an MqttBus with the ``bcs-gs`` identity),
        connect it, start the worker, the silence watchdog and the registry watcher, and publish the
        retained config of every active node once the subscriptions are acknowledged."""
        self._mqtt = mqtt
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        for channel in CHANNELS:
            mqtt.subscribe(f"bcs/v1/+/nodes/+/{channel}", self._on_message)
        self._tasks = [
            asyncio.create_task(self._worker(), name="ingest-worker"),
            asyncio.create_task(self._watchdog(), name="ingest-watchdog"),
        ]
        await mqtt.connect()
        self._tasks.append(asyncio.create_task(self._after_connect(), name="ingest-ready"))

    async def _after_connect(self) -> None:
        while not await self._mqtt.wait_subscribed(5):
            log.info("telemetry ingest waiting for the broker")
        # Registry changes from here on publish configs; everything registered before is covered now.
        # The worker loads the online nodes and publishes every config, then marks the ingest ready.
        self._registry_sub = self._bus.subscribe(1000)
        self._enqueue("init", None, None)
        async for event in self._registry_sub:
            if event.type == "node.registry":
                self._enqueue("registry", event.data, None)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        if self._registry_sub is not None:
            self._registry_sub.close()
        if self._mqtt is not None:
            await asyncio.to_thread(self._mqtt.close)
        self.ready = False

    def reset(self) -> None:
        """Forget the in-memory node state and config versions (test reset clears the tables)."""
        self._enqueue("reset", None, None)

    # ---- intake --------------------------------------------------------------------------------------
    async def _on_message(self, topic_str: str, payload: bytes) -> None:
        self._enqueue("message", topic_str, payload)

    def _enqueue(self, kind: str, a: Any, b: Any) -> None:
        """Queue an item; safe from any thread (the queue belongs to the loop ``start`` ran on)."""
        queue, loop = self._queue, self._loop
        if queue is None or loop is None:
            return
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            queue.put_nowait((kind, a, b))
        elif not loop.is_closed():
            loop.call_soon_threadsafe(queue.put_nowait, (kind, a, b))

    def handled(self, node_id: str, channel: str) -> int:
        """How many messages from ``node_id`` on ``channel`` were fully processed (a test hook)."""
        with self._handled_lock:
            return self._handled[(node_id, channel)]

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            kind, a, b = await self._queue.get()
            self._busy = True
            try:
                if kind == "message":
                    outcome = await asyncio.to_thread(self._process_message, a, b, self._clock.now())
                elif kind == "tick":
                    outcome = await asyncio.to_thread(self._check_silence, self._clock.now())
                elif kind == "registry":
                    outcome = await asyncio.to_thread(self._on_registry, a)
                elif kind == "init":
                    await asyncio.to_thread(self._publish_all_configs)
                    self.ready = True
                    log.info("telemetry ingest ready")
                    outcome = _Outcome()
                else:
                    self._nodes.clear()
                    with self._config_lock:
                        self._versions = None
                    outcome = _Outcome()
                await self._deliver(outcome)
            except Exception:
                log.exception("ingest failed on a %s item", kind)
            finally:
                self._busy = False
                if kind == "message":
                    self._count(a)

    @property
    def idle(self) -> bool:
        """Nothing queued or in progress (a test hook; read from any thread)."""
        return self._queue is not None and self._queue.empty() and not self._busy

    def _count(self, topic_str: str) -> None:
        parts = topic_str.split("/")
        if len(parts) == 6:
            with self._handled_lock:
                self._handled[(parts[4], parts[5])] += 1

    async def _deliver(self, outcome: _Outcome) -> None:
        for type_, data in outcome.events:
            self._bus.publish(type_, data)
        for ack in outcome.acks:
            hook = self.on_ack
            if hook is None:
                log.info("ack for %s from %s with no tasking hook", ack.command_id, ack.node_id)
                continue
            try:
                result = hook(ack)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("on_ack hook failed")

    async def _watchdog(self) -> None:
        """Every second of clock time, queue a silence check (G5: 3 x interval without telemetry)."""
        while True:
            await self._clock.sleep(WATCHDOG_PERIOD_S)
            self._enqueue("tick", None, None)

    # ---- processing (worker thread) ------------------------------------------------------------------
    def _process_message(self, topic_str: str, payload: bytes, received: datetime) -> _Outcome:
        out = _Outcome()
        try:
            site_id, node_id, channel = parse_topic(topic_str)
        except ValueError:
            log.warning("ignoring a message on a foreign topic")
            return out
        device = self._repo.get("devices", {"id": node_id})
        if device is None or device.get("kind") != "sentinel_node":
            log.warning("message from unregistered node %s on %s ignored", node_id, channel)
            return out
        try:
            msg = parse_message(channel, payload)
            errors = self._consistency(msg, site_id, node_id, channel, device, received)
        except ProtocolError as exc:
            errors = exc.errors
        if errors:
            if channel == "status" and device["status"] == "decommissioned":
                return out  # its retained status lingers on the broker; nothing to report
            self._malformed(out, node_id, channel, errors, payload, received)
            return out
        inner = getattr(msg, "root", msg)
        if channel == "telemetry":
            self._telemetry(out, inner, device, received)
        elif channel == "status":
            self._status(out, inner, device, received)
        elif channel == "event":
            self._node_event(out, inner)
        elif channel == "ack":
            out.acks.append(inner)
        return out

    def _consistency(
        self, msg: Any, site_id: str, node_id: str, channel: str, device: dict[str, Any], received: datetime
    ) -> list[str]:
        inner = getattr(msg, "root", msg)
        errors = []
        if inner.site_id != site_id:
            errors.append(f"site_id: {inner.site_id!r} does not match the topic's {site_id!r}")
        if inner.node_id != node_id:
            errors.append(f"node_id: {inner.node_id!r} does not match the topic's {node_id!r}")
        if site_id != device["site_id"]:
            errors.append(f"site_id: {node_id} is registered at {device['site_id']!r}")
        if device["status"] == "decommissioned":
            errors.append(f"node_id: {node_id} is decommissioned")
        if channel == "telemetry":
            if inner.node_type != device["node_type"]:
                errors.append(f"node_type: {inner.node_type!r} but {node_id} is a {device['node_type']!r}")
            ahead = (from_iso(inner.sampled_at) - received).total_seconds()
            if ahead > FUTURE_TOLERANCE_S:
                errors.append(f"sampled_at: {ahead:.0f} s after receipt (limit {FUTURE_TOLERANCE_S} s)")
        return errors

    def _malformed(
        self, out: _Outcome, node_id: str, channel: str, errors: list[str], payload: bytes, received: datetime
    ) -> None:
        excerpt = payload[:EXCERPT_MAX_BYTES].decode("utf-8", errors="replace")
        while len(excerpt.encode("utf-8")) > EXCERPT_MAX_BYTES:
            excerpt = excerpt[:-1]
        details = {"channel": channel, "errors": [e[:300] for e in errors[:20]], "excerpt": excerpt}
        log.info("malformed %s from %s: %s", channel, node_id, "; ".join(errors)[:300])
        self._gs_event(out, node_id, "malformed", details, received)

    def _gs_event(
        self, out: _Outcome, node_id: str, kind: str, details: dict[str, Any], at: datetime
    ) -> None:
        row = {
            "id": uuid7(), "node_id": node_id, "at": to_iso(at), "origin": "ground_station", "kind": kind,
            "parameter": None, "value": None, "score": None, "details": details, "boot_id": None, "seq": None,
        }  # fmt: skip
        self._repo.insert("node_events", row)
        out.events.append(("node.event", _event_data(row)))

    def _state(self, device: dict[str, Any], now: datetime) -> _NodeState:
        st = self._nodes.get(device["id"])
        if st is None:
            st = _NodeState(device["status"], device["mode"], device["interval_s"], device["boot_id"], now)
            self._nodes[device["id"]] = st
        return st

    def _interval(self, st: _NodeState, mode: str | None = None) -> float:
        """The node's current interval: its reported one, else the configured one for the mode."""
        demo = self._settings.demo_values()
        mode = mode or st.mode or "baseline"
        if st.interval_s and (st.mode is None or st.mode == mode):
            return float(st.interval_s)
        return float(demo.investigation_interval_s if mode == "investigation" else demo.baseline_interval_s)

    def _telemetry(self, out: _Outcome, t: Any, device: dict[str, Any], received: datetime) -> None:
        st = self._state(device, received)
        interval = self._interval(st, t.mode)
        sampled = from_iso(t.sampled_at)
        late = (received - sampled).total_seconds() > 2 * interval
        row = {
            "id": uuid7(), "node_id": t.node_id, "boot_id": t.boot_id, "seq": t.seq, "sampled_at": t.sampled_at,
            "received_at": to_iso(received), "mode": t.mode, "readings": t.readings.model_dump(),
            "health": t.health.model_dump(), "flags": [f.model_dump() for f in t.flags], "source": t.source,
            "replay": t.replay, "late": late,
        }  # fmt: skip
        try:
            self._repo.insert("telemetry", row)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                return  # a duplicate (node, boot, seq): dropped silently
            raise
        out.events.append(("node.telemetry", {k: row[k] for k in TELEMETRY_EVENT_KEYS}))
        st.last_activity = received
        new_interval = st.interval_s if st.mode == t.mode and st.interval_s else interval
        self._transition(
            out, st, t.node_id, "online", t.mode, new_interval, received, reason=None, why="telemetry",
            boot_id=t.boot_id, fw_version=t.health.fw_version,
        )  # fmt: skip

    def _status(self, out: _Outcome, s: Status, device: dict[str, Any], received: datetime) -> None:
        st = self._state(device, received)
        if s.state == "online":
            new_boot = st.boot_id != s.boot_id
            was_online = st.status == "online"
            st.last_activity = received
            self._transition(
                out, st, s.node_id, "online", s.mode, s.interval_s, from_iso(s.at), reason=None, why="status",
                boot_id=s.boot_id, fw_version=s.fw_version,
            )  # fmt: skip
            if not was_online or new_boot:
                self.publish_config(s.node_id)
        else:
            at = received if s.reason == "last_will" else from_iso(s.at)  # G3: a will's `at` is stale
            self._transition(
                out, st, s.node_id, "offline", None, st.interval_s, at, reason=s.reason,
                why=s.reason or "status", fw_version=s.fw_version,
            )  # fmt: skip

    def _transition(
        self,
        out: _Outcome,
        st: _NodeState,
        node_id: str,
        state: str,
        mode: str | None,
        interval_s: float | None,
        at: datetime,
        *,
        reason: str | None,
        why: str,
        boot_id: str | None = None,
        fw_version: str | None = None,
    ) -> None:
        """Apply a state/mode/interval change: the devices row, a GS node event on an online/offline
        transition, and ``node.status`` when state, mode or interval changed."""
        changed_state = st.status != state
        changed = changed_state or st.mode != mode or (st.interval_s or None) != (interval_s or None)
        st.status, st.mode, st.interval_s = state, mode, interval_s
        if boot_id:
            st.boot_id = boot_id
        changes: dict[str, Any] = {"status": state, "mode": mode, "updated_at": to_iso(self._clock.now())}
        if interval_s is not None:
            changes["interval_s"] = round(interval_s)
        if state == "online":
            changes["last_seen_at"] = to_iso(self._clock.now())
        if boot_id:
            changes["boot_id"] = boot_id
        if fw_version:
            changes["fw_version"] = fw_version
        with self._repo.transaction():
            self._repo.update_if("devices", {"id": node_id}, changes, {})
            if changed_state:
                self._gs_event(out, node_id, state, {"reason": why}, at)
        if changed:
            out.events.append(
                ("node.status", {
                    "node_id": node_id, "state": state, "mode": mode, "interval_s": interval_s,
                    "at": to_iso(at), "reason": reason if state == "offline" else None,
                })
            )  # fmt: skip
        if changed_state and state == "online" and why == "telemetry":
            self.publish_config(node_id)

    def _node_event(self, out: _Outcome, e: NodeEvent) -> None:
        row = {
            "id": uuid7(), "node_id": e.node_id, "at": e.at, "origin": "node", "kind": e.kind,
            "parameter": e.parameter, "value": e.value, "score": e.score, "details": e.details,
            "boot_id": e.boot_id, "seq": e.seq,
        }  # fmt: skip
        try:
            self._repo.insert("node_events", row)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                return
            raise
        out.events.append(("node.event", _event_data(row)))

    def _check_silence(self, now: datetime) -> _Outcome:
        out = _Outcome()
        for node_id, st in list(self._nodes.items()):
            if st.status != "online":
                continue
            limit = self._settings.demo_time.common.get("offline_after_intervals", 3) * self._interval(st)
            if (now - st.last_activity).total_seconds() > limit:
                self._transition(
                    out, st, node_id, "offline", None, st.interval_s, now, reason="silence", why="silence"
                )
        return out

    def _on_registry(self, data: dict[str, Any]) -> _Outcome:
        change, ids = data.get("change"), list(data.get("node_ids") or [])
        if change in ("installed", "commissioned", "re_commissioned"):
            for nid in ids:
                self.publish_config(nid)
        elif change == "decommissioned":
            for nid in ids:
                self._nodes.pop(nid, None)
                self._clear_config(nid)
        return _Outcome()

    def _load_online_nodes(self) -> None:
        """Watch nodes the store says are online (e.g. across a restart) from now on."""
        now = self._clock.now()
        for row in self._registry.nodes():
            if row.status == "online" and row.id not in self._nodes:
                self._nodes[row.id] = _NodeState(row.status, row.mode, row.interval_s, row.boot_id, now)

    # ---- retained configuration ----------------------------------------------------------------------
    def config_payload(self, node_id: str, node_type: str, version: int) -> dict[str, Any]:
        demo = self._settings.demo_values()
        keys = READING_KEYS[node_type]
        return {
            "schema": "bcs.config.v1",
            "site_id": self._site_id,
            "node_id": node_id,
            "config_version": version,
            "issued_at": to_iso(self._clock.now()),
            "demo_time_scale": self._settings.demo_time_scale == "on",
            "baseline_interval_s": int(demo.baseline_interval_s),
            "investigation_interval_s": int(demo.investigation_interval_s),
            "anomaly": {**ANOMALY, "stuck_epsilon": {k: STUCK_EPSILON[k] for k in keys}},
            "critical_bands": {k: dict(CRITICAL_BANDS[k]) for k in keys if k in CRITICAL_BANDS},
            "battery_low_pct": float(self._settings.demo_time.common.get("battery_low_pct", 15)),
        }

    def publish_config(self, node_id: str) -> int | None:
        """Publish the node's retained ``bcs.config.v1`` with the next ``config_version``. Returns the
        version, or None when the node is unknown or inactive or MQTT is not attached."""
        if self._mqtt is None:
            return None
        row = self._registry.get(node_id)
        if row is None or row.kind != "sentinel_node" or row.status == "decommissioned":
            return None
        with self._config_lock:
            versions = self._load_versions()
            version = versions.get(node_id, 0) + 1
            # Validated against the schema, then sent as built: absent bands stay absent rather than null.
            payload = json.dumps(self.config_payload(node_id, row.node_type, version)).encode()
            parse_message("config", payload)
            versions[node_id] = version
            self._repo.upsert(
                "settings", {"key": VERSIONS_KEY, "value": versions, "updated_at": to_iso(self._clock.now())},
                sync=False,
            )  # fmt: skip
            self._mqtt.publish(topic(self._site_id, node_id, "config"), payload, retain=True)
        return version

    def _clear_config(self, node_id: str) -> None:
        if self._mqtt is not None:
            self._mqtt.publish(topic(self._site_id, node_id, "config"), b"", retain=True)

    def _load_versions(self) -> dict[str, int]:
        if self._versions is None:
            row = self._repo.get("settings", {"key": VERSIONS_KEY})
            self._versions = dict(row["value"]) if row else {}
        return self._versions

    def _publish_all_configs(self) -> None:
        self._load_online_nodes()
        for row in self._registry.nodes():
            self.publish_config(row.id)

    def set_demo_time_scale(self, on: bool) -> None:
        """Switch demo time (N12) and republish every active node's config (blocking)."""
        self._settings.demo_time_scale = "on" if on else "off"
        for row in self._registry.nodes():
            self.publish_config(row.id)

    # ---- reads (blocking) ------------------------------------------------------------------------
    def latest(self, node_id: str) -> TelemetryRow | None:
        rows = self._repo.query(
            "SELECT * FROM telemetry WHERE node_id = ? ORDER BY sampled_at DESC, seq DESC LIMIT 1",
            (node_id,), table="telemetry",
        )  # fmt: skip
        return TelemetryRow.from_row(rows[0]) if rows else None

    def latest_all(self) -> dict[str, TelemetryRow]:
        rows = self._repo.query(
            "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY node_id ORDER BY sampled_at DESC, seq DESC)"
            " AS rn FROM telemetry) WHERE rn = 1",
            table="telemetry",
        )
        return {r["node_id"]: TelemetryRow.from_row(r) for r in rows}

    def window(self, node_id: str, since: datetime, until: datetime | None = None) -> list[TelemetryRow]:
        """Samples with ``since <= sampled_at`` (``<= until``), oldest first."""
        sql = "SELECT * FROM telemetry WHERE node_id = ? AND sampled_at >= ?"
        params: list[Any] = [node_id, to_iso(since)]
        if until is not None:
            sql += " AND sampled_at <= ?"
            params.append(to_iso(until))
        rows = self._repo.query(sql + " ORDER BY sampled_at, seq", tuple(params), table="telemetry")
        return [TelemetryRow.from_row(r) for r in rows]

    def recent(self, node_id: str, limit: int) -> list[TelemetryRow]:
        """The newest ``limit`` samples, oldest first."""
        rows = self._repo.query(
            "SELECT * FROM telemetry WHERE node_id = ? ORDER BY sampled_at DESC, seq DESC LIMIT ?",
            (node_id, limit), table="telemetry",
        )  # fmt: skip
        return [TelemetryRow.from_row(r) for r in reversed(rows)]

    def robust(self, node_id: str, parameter: str, mode: str) -> float | None:
        """N1 robust value: the median of the last 5 samples (baseline) or of the last 60 s (investigation)."""
        return self.robust_all(node_id, mode).get(parameter)

    def robust_all(self, node_id: str, mode: str) -> dict[str, float]:
        """The N1 robust value of every parameter the node reported in the window (one query)."""
        if mode == "investigation":
            rows = self.window(node_id, self._clock.now() - timedelta(seconds=60))
        else:
            rows = self.recent(node_id, 5)
        values: dict[str, list[float]] = {}
        for r in rows:
            for p, v in r.readings.items():
                if v is not None:
                    values.setdefault(p, []).append(v)
        return {p: float(statistics.median(vs)) for p, vs in values.items()}

    def events(self, node_id: str, limit: int) -> list[dict[str, Any]]:
        """I3 ``NodeEvent`` list, newest first."""
        rows = self._repo.query(
            "SELECT * FROM node_events WHERE node_id = ? ORDER BY at DESC, rowid DESC LIMIT ?",
            (node_id, limit), table="node_events",
        )  # fmt: skip
        return [_event_data(r) for r in rows]

    def series(
        self, node_id: str, since: datetime, until: datetime | None, max_points: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """TelemetryPoints in time order; above ``max_points`` they are averaged per equal time bucket."""
        rows = self.window(node_id, since, until)
        if len(rows) <= max_points:
            return [r.point() for r in rows], False
        t0 = from_iso(rows[0].sampled_at)
        span = (from_iso(rows[-1].sampled_at) - t0).total_seconds() or 1.0
        buckets: list[list[TelemetryRow]] = [[] for _ in range(max_points)]
        for r in rows:
            i = min(max_points - 1, int((from_iso(r.sampled_at) - t0).total_seconds() / span * max_points))
            buckets[i].append(r)
        points = []
        for b in buckets:
            if not b:
                continue
            mean_t = sum((from_iso(r.sampled_at) - t0).total_seconds() for r in b) / len(b)
            keys = {k for r in b for k in r.readings}
            readings = {
                k: statistics.fmean(r.readings[k] for r in b if k in r.readings) for k in sorted(keys)
            }
            points.append({
                "t": to_iso(t0 + timedelta(seconds=mean_t)), "mode": b[-1].mode,
                "late": any(r.late for r in b), "readings": readings,
            })  # fmt: skip
        return points, True


def _event_data(row: dict[str, Any]) -> dict[str, Any]:
    """I3 ``NodeEvent`` from a ``node_events`` row."""
    return {
        k: row[k] for k in ("id", "node_id", "at", "origin", "kind", "parameter", "value", "score", "details")
    }
