"""Tasking controller and coverage-gap feed (spec §15; addendum F5, G3, G5, H2, I3, J2, N9, N12).

A trigger (a zone flag, a node anomaly, M4's ``risk_high`` / ``early_warning``, or the operator) tasks the
WQ/SP nodes covering the zone, nearest first, plus the TG (at most 4), by sending each a ``set_mode
investigation`` command for the N12 task duration. The task is then:

- ``issued`` until a node accepts, ``active`` from the first accepted ack;
- extended (not duplicated) by a new trigger for the same zone while it runs: every node gets a fresh
  ``set_mode`` and the task's ``expires_at`` moves out. Triggers are coalesced: the task is extended only
  when its end would move by at least one cooldown (N12: 30 s; at most half the task duration), so a burst
  of node anomalies (a ramp or ``spikes`` fault at 2 s sampling) changes nothing until the end would move
  by that much, then extends once (one ``extended`` note, one command per node);
- ended at ``expires_at``: ``completed`` when a node completed its latest investigation command (a late
  ``completed`` ack upgrades ``expired``), else ``expired``; a per-zone cooldown follows (automatic
  triggers during it return None);
- or ``cancelled`` (operator, all nodes released, or re-commissioning): every node of the task gets
  ``set_mode baseline`` and its investigation commands are marked ``released``, so late acks are recorded
  in the timeline but never revive the task.

Commands expire 30 s after issue; one still ``pending`` after 5 s is re-sent once (unless a newer command
to the same node has superseded it), one still pending at expiry becomes ``no_ack``. ``tick(now)`` applies retries, expiry and task ends; it runs from a loop on the
injected clock and before every read or trigger, so a jump of a manual clock is applied at once.

A flagged (or High/Critical, M4) zone is remembered as needing coverage; one without WQ/SP coverage gets no
task but a ``coverage.updated`` whose ``gaps`` carry the advice for it (``gaps(nodes)``).

Everything runs on the event loop under one asyncio lock; database work runs in worker threads.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from bcs_protocol.timefmt import from_iso, to_iso
from bcs_protocol.topics import topic
from bcs_protocol.validate import parse_message

from bcs_gs.api import models as m
from bcs_gs.core.aio import to_thread_settled
from bcs_gs.core.clock import Clock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.nodes.coverage import (
    CHANNEL,
    DEFAULT_GRID,
    TIDE,
    GapSuggestion,
    ZoneGrid,
    by_zone,
    coverage,
    covered_set,
    gap_suggestions,
)
from bcs_gs.store.repo import Repo

log = logging.getLogger("bcs_gs.tasking")

TaskTrigger = Literal["zone_flag", "node_anomaly", "risk_high", "early_warning", "manual"]
TRIGGERS = ("zone_flag", "node_anomaly", "risk_high", "early_warning", "manual")
NEEDING_KEY = "tasking.zones_needing"  # local-only ``settings`` row (H3): survives a restart
NEEDS_COVERAGE = ("zone_flag", "risk_high", "early_warning")  # §15: flagged or High/Critical zones
ANOMALY_KINDS = ("anomaly", "threshold")  # node events that task the node's zone
OPEN = ("issued", "active")
MAX_NODES = 4
RETRY_AFTER_S = 5.0  # G5
COMMAND_TTL_S = 30.0  # expires_at = issued_at + 30 s
TICK_S = 1.0
RECENT_S = 600.0  # GET /tasks default: open tasks plus those updated in the last 10 min
PRUNE_AFTER_S = 600.0
_ACK_EVENT = {"accepted": "acknowledged", "rejected": "rejected", "completed": "node_completed",
              "expired": "command_expired"}  # fmt: skip
_ACK_RANK = {"pending": 0, "no_ack": 0, "accepted": 1, "completed": 2, "rejected": 2, "expired": 2}


class TaskNotFound(LookupError):
    pass


class TaskConflict(RuntimeError):
    """The task is not open, or the request does not fit its state."""


class NoCoverage(RuntimeError):
    """No WQ/SP node covers the zone, so it cannot be tasked."""


# ---- node selection (pure) ----------------------------------------------------------------------------
def _covering(zone_id: str, cov: Any) -> set[str]:
    if isinstance(cov, m.Coverage):
        z = next((z for z in cov.zones if z.zone_id == zone_id), None)
        return set() if z is None else {*z.water, *z.soil}
    entry = cov.get(zone_id) or {}
    return {*entry.get("water", ()), *entry.get("soil", ())}


def _nid(node: Any) -> str:
    return getattr(node, "id", None) or node.node_id


def select_nodes(zone_id: str, nodes: Iterable[Any], cov: Any, *, grid: ZoneGrid = DEFAULT_GRID) -> list[str]:
    """N9/§15: the WQ/SP nodes covering ``zone_id`` (per ``cov``: an I3 Coverage or a ``by_zone`` map),
    nearest the zone centre first, then the TG; at most 4. Empty when no WQ/SP node covers the zone."""
    nodes = [n for n in nodes if getattr(n, "status", None) != "decommissioned" and n.e_m is not None]
    covering = _covering(zone_id, cov)
    ce, cs = grid.centre(zone_id)
    near = sorted(
        (n for n in nodes if _nid(n) in covering and n.node_type in CHANNEL),
        key=lambda n: (math.hypot(n.e_m - ce, n.s_m - cs), _nid(n)),
    )
    if not near:
        return []
    tg = sorted(_nid(n) for n in nodes if n.node_type == TIDE)
    picked = [_nid(n) for n in near[: MAX_NODES - 1 if tg else MAX_NODES]]
    return picked + tg[:1]


# ---- state --------------------------------------------------------------------------------------------
@dataclass
class _Task:
    row: dict[str, Any]  # a ``tasks`` row
    commands: list[dict[str, Any]] = field(default_factory=list)  # ``commands`` rows, in issue order
    released: set[str] = field(default_factory=set)
    dirty: set[str] = field(default_factory=set)  # command IDs to write

    @property
    def id(self) -> str:
        return self.row["id"]

    @property
    def open(self) -> bool:
        return self.row["status"] in OPEN

    def live_nodes(self) -> list[str]:
        return [n for n in self.row["node_ids"] if n not in self.released]

    def latest_investigation(self, node_id: str) -> dict[str, Any] | None:
        for c in reversed(self.commands):
            if (
                c["node_id"] == node_id
                and c["type"] == "set_mode"
                and c["params"].get("mode") == "investigation"
            ):
                return c
        return None

    def note(self, at: datetime, event: str, node_id: str | None = None, **details: Any) -> None:
        entry: dict[str, Any] = {"at": to_iso(at), "event": event}
        if node_id is not None:
            entry["node_id"] = node_id
        if details:
            entry["details"] = details
        self.row["timeline"].append(entry)
        self.row["updated_at"] = max(self.row["updated_at"], to_iso(at))

    def model(self) -> m.Task:
        return _to_model(self.row, self.commands)


def _to_model(row: dict[str, Any], commands: Sequence[dict[str, Any]]) -> m.Task:
    return m.Task(
        id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"], expires_at=row["expires_at"],
        trigger=row["trigger"], zone_id=row["zone_id"], node_ids=list(row["node_ids"]),
        duration_s=row["duration_s"], status=row["status"], reason=row["reason"],
        cancelled_by=row["cancelled_by"], timeline=[m.TaskTimelineEntry(**e) for e in row["timeline"]],
        commands=[
            m.Command(
                id=c["id"], node_id=c["node_id"], type=c["type"], params=c["params"], issued_at=c["issued_at"],
                expires_at=c["expires_at"], ack_status=c["ack_status"], ack_at=c["ack_at"], retries=c["retries"],
            )
            for c in commands
        ],
    )  # fmt: skip


class TaskingController:
    def __init__(
        self,
        repo: Repo,
        registry: Any,
        bus: EventBus,
        clock: Clock,
        settings: Settings,
        *,
        site: Any,
        site_id: str,
        captures: Any = None,
        grid: ZoneGrid | None = None,
    ) -> None:
        self._repo, self._registry, self._bus, self._clock = repo, registry, bus, clock
        self._settings, self._site, self._site_id, self._captures = settings, site, site_id, captures
        self.grid = grid or ZoneGrid.from_site(site)
        self._mqtt: Any = None
        self._lock = asyncio.Lock()
        self._tasks: dict[str, _Task] = {}
        self._by_command: dict[str, _Task] = {}
        self._cooldown_until: dict[str, datetime] = {}
        self._needing: dict[str, None] = {}  # insertion-ordered set of zones needing coverage
        self._bg: list[asyncio.Task[Any]] = []
        self._sub: Any = None
        self._loaded = False
        self.loop: asyncio.AbstractEventLoop | None = None  # set by start(); tests submit work to it

    # ---- lifecycle ----------------------------------------------------------------------------------
    def attach(self, mqtt: Any) -> None:
        """Send commands through ``mqtt`` (the ingest's ``bcs-gs`` MqttBus) from now on."""
        self._mqtt = mqtt

    def start(self) -> None:
        """Listen for ``zone.flagged`` and node anomalies, and run ``tick`` every second of clock time."""
        self.loop = asyncio.get_running_loop()
        self._sub = self._bus.subscribe(10000)
        self._bg = [
            asyncio.create_task(self._listen(), name="tasking-listen"),
            asyncio.create_task(self._ticker(), name="tasking-tick"),
        ]

    async def stop(self) -> None:
        if self._sub is not None:
            self._sub.close()
        for t in self._bg:
            t.cancel()
        for t in self._bg:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._bg = []

    async def cancel_work(self) -> None:
        """Cancel the work in flight and wait until it ended, then listen again (test reset; ruling R30)."""
        await self.stop()
        self.start()

    def reset(self) -> None:
        """Forget every task, cooldown and zone needing coverage (test reset clears the tables)."""
        self._tasks.clear()
        self._by_command.clear()
        self._cooldown_until.clear()
        self._needing.clear()
        self._loaded = True

    async def _ticker(self) -> None:
        while True:
            await self._clock.sleep(TICK_S)
            try:
                await self.tick(self._clock.now())
            except Exception:
                log.exception("tasking tick failed")

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                try:
                    await self._on_event(ev.type, ev.data)
                except Exception:
                    log.exception("tasking failed on %s", ev.type)
            if not sub.overflowed:
                return  # closed by stop()
            log.warning("tasking event subscription overflowed; resubscribing")
            self._sub = self._bus.subscribe(10000)

    async def _on_event(self, type_: str, data: dict[str, Any]) -> None:
        if type_ == "zone.flagged":
            kinds = ", ".join(dict.fromkeys(f["kind"] for f in data.get("flags") or [])) or "flag"
            zone = data["zone_id"]
            await self.trigger(
                zone, "zone_flag", f"{zone} flagged ({kinds}) in capture {data.get('capture_id')}"
            )
        elif type_ == "node.event" and data.get("origin") == "node" and data.get("kind") in ANOMALY_KINDS:
            node, param = data["node_id"], data.get("parameter")
            why = f"{node} {data['kind']}" + (f" on {param}" if param else "")
            await self.trigger(None, "node_anomaly", why, node_ids=[node])

    async def _ensure_loaded(self) -> None:
        """Pick up open tasks from the store once (a restart mid-task)."""
        if self._loaded:
            return
        self._loaded = True
        saved = await to_thread_settled(self._repo.get, "settings", {"key": NEEDING_KEY})
        for zone in (saved or {}).get("value") or ():
            self._needing.setdefault(zone, None)
        rows = await to_thread_settled(
            self._repo.query, "SELECT * FROM tasks WHERE status IN ('issued', 'active')", (), table="tasks"
        )
        for row in rows:
            cmds = await to_thread_settled(
                self._repo.query, "SELECT * FROM commands WHERE task_id = ? ORDER BY issued_at, rowid",
                (row["id"],), table="commands",
            )  # fmt: skip
            t = _Task(row, cmds)
            t.released = {c["node_id"] for c in cmds if c["ack_status"] == "released"}
            self._index(t)

    def _index(self, t: _Task) -> None:
        self._tasks[t.id] = t
        for c in t.commands:
            self._by_command[c["id"]] = t

    # ---- triggers ----------------------------------------------------------------------------------
    async def trigger(
        self,
        zone_id: str | None,
        trigger: TaskTrigger,
        reason: str,
        node_ids: list[str] | None = None,
        duration_s: float | None = None,
    ) -> m.Task | None:
        """Task the zone (see the module docstring). Returns the new or extended task, or None during the
        zone's cooldown (automatic triggers) or when no WQ/SP node covers the zone (a gap is reported).
        For ``node_anomaly`` without a zone, the zone is the first node's. ``manual`` may name the nodes
        and ignores the cooldown; it raises ``NoCoverage`` for an uncovered zone without nodes.
        Raises ValueError for an unknown trigger, zone or node."""
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger {trigger!r}")
        async with self._lock:
            now = self._clock.now()
            await self._tick_locked(now)
            nodes = await to_thread_settled(self._registry.nodes)
            known = {_nid(n): n for n in nodes}
            for n in node_ids or ():
                if n not in known:
                    raise ValueError(f"unknown or decommissioned node {n!r}")
            if trigger == "node_anomaly" and zone_id is None and node_ids:
                zone_id = getattr(known[node_ids[0]], "zone_id", None)
            if zone_id is not None and zone_id not in self.grid.zone_ids():
                raise ValueError(f"unknown zone {zone_id!r}")
            if zone_id is None and not node_ids:
                raise ValueError("a task needs a zone or nodes")
            duration = float(duration_s or self._demo().task_duration_s)

            if zone_id is not None and trigger in NEEDS_COVERAGE:
                await to_thread_settled(self._remember_zone, zone_id)
                if zone_id not in covered_set(nodes, self.grid):  # no task: report the gap instead
                    await self._publish_coverage(nodes)

            current = next(
                (t for t in self._tasks.values() if t.open and zone_id and t.row["zone_id"] == zone_id), None
            )
            if current is not None:
                await self._extend(current, now, duration, trigger, reason, zone_id)
                return current.model()

            until = self._cooldown_until.get(zone_id) if zone_id else None
            if trigger != "manual" and until is not None and now < until:
                log.info("tasking %s skipped: cooldown until %s", zone_id, to_iso(until))
                return None

            if trigger == "manual" and node_ids:
                selected = list(dict.fromkeys(node_ids))
            else:
                selected = (
                    select_nodes(zone_id, nodes, by_zone(nodes, self.grid), grid=self.grid) if zone_id else []
                )
                if trigger == "node_anomaly" and selected and node_ids and node_ids[0] not in selected:
                    selected = [node_ids[0], *selected[: MAX_NODES - 1]]
            if not selected:
                log.info("tasking %s: no WQ/SP coverage, no task", zone_id)
                if trigger == "manual":
                    raise NoCoverage(f"No WQ/SP node covers {zone_id}.")
                return None
            return (await self._create(zone_id, trigger, reason, selected, duration, now)).model()

    async def _create(
        self,
        zone_id: str | None,
        trigger: str,
        reason: str,
        node_ids: list[str],
        duration: float,
        now: datetime,
    ) -> _Task:
        iso = to_iso(now)
        t = _Task({
            "id": uuid7(), "created_at": iso, "updated_at": iso,
            "expires_at": to_iso(now + timedelta(seconds=duration)), "trigger": trigger, "zone_id": zone_id,
            "node_ids": node_ids, "mode": "investigation", "duration_s": _num(duration), "status": "issued",
            "reason": reason, "cancelled_by": None, "timeline": [],
        })  # fmt: skip
        t.note(now, "issued", trigger=trigger, nodes=node_ids)
        self._tasks[t.id] = t
        for n in node_ids:
            self._command(t, n, {"mode": "investigation", "duration_s": _num(duration)}, now)
        await self._save(t)
        log.info("task %s (%s) for %s: %s", t.id, trigger, zone_id, ", ".join(node_ids))
        return t

    async def _extend(
        self, t: _Task, now: datetime, duration: float, trigger: str, reason: str, zone_id: str | None = None
    ) -> None:
        """Extend ``t`` to ``now + duration`` and re-command its nodes, unless that moves its end by less
        than one cooldown (at most ``duration / 2``): such an automatic trigger is coalesced into the
        running task (a ``coalesced`` timeline note, one per window, counts them). ``manual`` is never
        coalesced; it re-commands the nodes and never shortens the task."""
        end = from_iso(t.row["expires_at"])
        gain = (now + timedelta(seconds=duration) - end).total_seconds()
        if trigger != "manual" and gain < min(float(self._demo().task_cooldown_s), duration / 2):
            last = next(
                (e for e in reversed(t.row["timeline"]) if e["event"] in ("coalesced", "extended")), None
            )
            if last is not None and last["event"] == "coalesced":
                last["details"]["count"] += 1  # in memory; written with the task's next save
                return
            t.note(
                now,
                "coalesced",
                trigger=trigger,
                reason=f"Coalesced trigger {trigger} from {zone_id or reason}"[:200],
                count=1,
            )
            await self._save(t)
            return
        new_end = max(now + timedelta(seconds=duration), end)
        t.row["expires_at"] = to_iso(new_end)
        t.row["duration_s"] = _num((new_end - from_iso(t.row["created_at"])).total_seconds())
        t.note(now, "extended", trigger=trigger, reason=reason[:200], expires_at=t.row["expires_at"])
        remaining = _num((new_end - now).total_seconds())
        for n in t.live_nodes():
            self._command(t, n, {"mode": "investigation", "duration_s": remaining}, now)
        await self._save(t)

    def _command(self, t: _Task, node_id: str, params: dict[str, Any], now: datetime) -> dict[str, Any]:
        cmd = {
            "id": uuid7(), "task_id": t.id, "node_id": node_id, "type": "set_mode", "params": params,
            "issued_at": to_iso(now), "expires_at": to_iso(now + timedelta(seconds=COMMAND_TTL_S)),
            "ack_status": "pending", "ack_at": None, "retries": 0,
        }  # fmt: skip
        t.commands.append(cmd)
        t.dirty.add(cmd["id"])
        self._by_command[cmd["id"]] = t
        self._send(t, cmd)
        return cmd

    def _send(self, t: _Task, cmd: dict[str, Any]) -> None:
        payload = json.dumps({
            "schema": "bcs.cmd.v1", "site_id": self._site_id, "node_id": cmd["node_id"],
            "command_id": cmd["id"], "type": cmd["type"], "params": cmd["params"],
            "issued_at": cmd["issued_at"], "expires_at": cmd["expires_at"], "task_id": t.id,
            "reason": (t.row["reason"] or "tasking")[:200],
        }).encode()  # fmt: skip
        parse_message("cmd", payload)  # never send a command the protocol rejects
        if self._mqtt is None:
            log.warning("command %s to %s not sent: MQTT not attached", cmd["id"], cmd["node_id"])
            return
        try:
            self._mqtt.publish(topic(self._site_id, cmd["node_id"], "cmd"), payload)
        except Exception as exc:  # noqa: BLE001 - the retry and no_ack rules cover a failed send
            log.warning("command %s to %s not sent: %s", cmd["id"], cmd["node_id"], exc)

    # ---- operator actions ----------------------------------------------------------------------------
    async def cancel(self, task_id: str, by: str | None = "operator") -> m.Task:
        async with self._lock:
            now = self._clock.now()
            await self._tick_locked(now)
            t = await self._open_task(task_id)
            self._cancel(t, now, by)
            await self._save(t)
            return t.model()

    async def cancel_all(self, reason: str) -> list[m.Task]:
        """Cancel every open task (re-commissioning), appending ``reason`` to each task's reason."""
        async with self._lock:
            now = self._clock.now()
            await self._tick_locked(now)
            out = []
            for t in [t for t in self._tasks.values() if t.open]:
                t.row["reason"] = f"{t.row['reason']}; {reason}" if t.row["reason"] else reason
                self._cancel(t, now, None, why=reason)
                await self._save(t)
                out.append(t.model())
            return out

    async def release(self, task_id: str, node_id: str) -> m.Task:
        async with self._lock:
            now = self._clock.now()
            await self._tick_locked(now)
            t = await self._open_task(task_id)
            if node_id not in t.row["node_ids"]:
                raise ValueError(f"{node_id} is not part of task {task_id}")
            if node_id in t.released:
                raise TaskConflict(f"{node_id} is already released.")
            self._release(t, node_id, now)
            t.note(now, "released", node_id)
            if not t.live_nodes():
                t.row["status"], t.row["cancelled_by"] = "cancelled", "operator"
                t.note(now, "cancelled", reason="every node released")
                self._end_zone(t, now)
            await self._save(t)
            return t.model()

    async def _open_task(self, task_id: str) -> _Task:
        t = self._tasks.get(task_id)
        if t is None:
            row = await to_thread_settled(self._repo.get, "tasks", {"id": task_id})
            if row is None:
                raise TaskNotFound(task_id)
            raise TaskConflict(f"Task {task_id} is {row['status']}.")
        if not t.open:
            raise TaskConflict(f"Task {task_id} is {t.row['status']}.")
        return t

    def _cancel(self, t: _Task, now: datetime, by: str | None, why: str | None = None) -> None:
        for n in t.live_nodes():
            self._release(t, n, now)
        t.row["status"], t.row["cancelled_by"] = "cancelled", by
        t.note(now, "cancelled", **({"by": by} if by else {}), **({"reason": why} if why else {}))
        self._end_zone(t, now)

    def _release(self, t: _Task, node_id: str, now: datetime) -> None:
        """Stop the node's investigation: its live investigation commands become ``released`` (never
        retried, late acks ignored) and it is sent ``set_mode baseline``."""
        for c in t.commands:
            if (
                c["node_id"] == node_id and c["params"].get("mode") == "investigation"
                and c["ack_status"] in ("pending", "accepted")
            ):  # fmt: skip
                c["ack_status"] = "released"
                t.dirty.add(c["id"])
        t.released.add(node_id)
        self._command(t, node_id, {"mode": "baseline"}, now)

    def _end_zone(self, t: _Task, now: datetime) -> None:
        """Start the zone's cooldown when a task ends (completed or expired at its end; cancelled now)."""
        if t.row["zone_id"] and t.row["status"] in ("completed", "expired", "cancelled"):
            cooldown = timedelta(seconds=float(self._demo().task_cooldown_s))
            self._cooldown_until[t.row["zone_id"]] = min(from_iso(t.row["expires_at"]), now) + cooldown

    # ---- acks ------------------------------------------------------------------------------------------
    async def on_ack(self, ack: Any) -> None:
        """TelemetryIngest hook: a validated ``bcs.ack.v1`` from a registered node (G5)."""
        async with self._lock:
            await self._ensure_loaded()
            t = self._by_command.get(ack.command_id)
            cmd = next((c for c in t.commands if c["id"] == ack.command_id), None) if t else None
            if cmd is None or cmd["node_id"] != ack.node_id:
                known = await to_thread_settled(self._repo.get, "commands", {"id": ack.command_id})
                if known is not None and known["node_id"] == ack.node_id:
                    log.info("late ack %s for an archived command %s", ack.status, ack.command_id)
                    return
                await self._unknown_ack(ack)
                return
            now = self._clock.now()
            prev = cmd["ack_status"]
            event = _ACK_EVENT.get(ack.status, ack.status)
            if prev == "released" or _ACK_RANK.get(ack.status, 0) < _ACK_RANK.get(prev, 0):
                t.note(now, "late_ack", ack.node_id, status=ack.status, command_id=cmd["id"])
            else:
                cmd["ack_status"], cmd["ack_at"] = ack.status, ack.at
                t.dirty.add(cmd["id"])
                details = {"command_id": cmd["id"], "mode": cmd["params"].get("mode")}
                if ack.reason:
                    details["reason"] = ack.reason[:200]
                t.note(now, event, ack.node_id, **details)
                investigation = cmd["params"].get("mode") == "investigation"
                if t.row["status"] == "issued" and ack.status == "accepted" and investigation:
                    t.row["status"] = "active"
                    t.note(now, "active")
                elif (
                    t.row["status"] == "expired" and ack.status == "completed"
                    and t.latest_investigation(ack.node_id) is cmd
                ):  # fmt: skip
                    t.row["status"] = "completed"
                    t.note(now, "completed", ack.node_id)
            await self._save(t)

    async def _unknown_ack(self, ack: Any) -> None:
        """G5: an ack for an unknown command is logged as a Ground Station node event, otherwise ignored."""
        log.info("ack from %s for unknown command %s ignored", ack.node_id, ack.command_id)
        row = {
            "id": uuid7(), "node_id": ack.node_id, "at": to_iso(self._clock.now()), "origin": "ground_station",
            "kind": "malformed", "parameter": None, "value": None, "score": None,
            "details": {"channel": "ack", "errors": [f"command_id: unknown command {ack.command_id}"],
                        "excerpt": ack.model_dump_json(by_alias=True)[:2048]},
            "boot_id": None, "seq": None,
        }  # fmt: skip
        await to_thread_settled(self._repo.insert, "node_events", row)
        self._bus.publish(
            "node.event",
            {
                k: row[k]
                for k in ("id", "node_id", "at", "origin", "kind", "parameter", "value", "score", "details")
            },
        )

    # ---- time -----------------------------------------------------------------------------------------
    async def tick(self, now: datetime | None = None) -> None:
        """Apply retries, ``no_ack``, task ends and pruning up to ``now``."""
        async with self._lock:
            await self._tick_locked(now or self._clock.now())

    async def _tick_locked(self, now: datetime) -> None:
        await self._ensure_loaded()
        for t in list(self._tasks.values()):
            changed = False
            for c in t.commands:
                if c["ack_status"] != "pending":
                    continue
                issued, expires = from_iso(c["issued_at"]), from_iso(c["expires_at"])
                if (
                    c["retries"] == 0 and now >= issued + timedelta(seconds=RETRY_AFTER_S)
                    and not _superseded(t, c)
                ):  # fmt: skip
                    c["retries"] = 1
                    t.dirty.add(c["id"])
                    if now < expires:
                        self._send(t, c)
                    t.note(
                        issued + timedelta(seconds=RETRY_AFTER_S), "retried", c["node_id"], command_id=c["id"]
                    )
                    changed = True
                if now >= expires:
                    c["ack_status"] = "no_ack"
                    t.dirty.add(c["id"])
                    t.note(expires, "no_ack", c["node_id"], command_id=c["id"])
                    changed = True
            if t.open and now >= from_iso(t.row["expires_at"]):
                done = any(
                    (c := t.latest_investigation(n)) is not None and c["ack_status"] == "completed"
                    for n in t.row["node_ids"]
                )
                t.row["status"] = "completed" if done else "expired"
                t.note(from_iso(t.row["expires_at"]), t.row["status"])
                self._end_zone(t, now)
                changed = True
            if changed:
                await self._save(t)
            elif not t.open and _quiet(t, now):
                self._forget(t)
        for zone, until in list(self._cooldown_until.items()):
            if now >= until:
                del self._cooldown_until[zone]

    def _forget(self, t: _Task) -> None:
        self._tasks.pop(t.id, None)
        for c in t.commands:
            self._by_command.pop(c["id"], None)

    # ---- persistence and events --------------------------------------------------------------------------
    async def _save(self, t: _Task) -> None:
        cmds = [c for c in t.commands if c["id"] in t.dirty]
        t.dirty.clear()
        row = {**t.row, "timeline": list(t.row["timeline"]), "node_ids": list(t.row["node_ids"])}
        await to_thread_settled(self._write, row, [dict(c) for c in cmds])
        self._bus.publish("task.updated", t.model().model_dump(mode="json"))

    def _write(self, row: dict[str, Any], cmds: list[dict[str, Any]]) -> None:
        with self._repo.transaction():
            self._repo.upsert("tasks", row)
            for c in cmds:
                self._repo.upsert("commands", c)

    async def list_tasks(
        self, status: str = "active", limit: int = 100, node_id: str | None = None
    ) -> list[m.Task]:
        """I3 Task[], newest first: ``active`` = open tasks plus those updated in the last 10 minutes;
        ``all`` = every task. ``node_id`` keeps the tasks that include that node."""
        await self.tick()
        return await to_thread_settled(self._read, status, limit, node_id, self._clock.now())

    def _read(self, status: str, limit: int, node_id: str | None, now: datetime) -> list[m.Task]:
        sql, params = "SELECT * FROM tasks", []
        where = []
        if status != "all":
            where.append("(status IN ('issued', 'active') OR updated_at >= ?)")
            params.append(to_iso(now - timedelta(seconds=RECENT_S)))
        if node_id is not None:
            where.append("EXISTS (SELECT 1 FROM json_each(tasks.node_ids) WHERE value = ?)")
            params.append(node_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        rows = self._repo.query(sql, (*params, limit), table="tasks")
        out = []
        for row in rows:
            cmds = self._repo.query(
                "SELECT * FROM commands WHERE task_id = ? ORDER BY issued_at, rowid",
                (row["id"],),
                table="commands",
            )
            out.append(_to_model(row, cmds))
        return out

    async def get(self, task_id: str) -> m.Task | None:
        await self.tick()
        found = [
            t
            for t in await to_thread_settled(self._read, "all", 1000, None, self._clock.now())
            if t.id == task_id
        ]
        return found[0] if found else None

    # ---- coverage gaps --------------------------------------------------------------------------------
    def zones_needing(self) -> list[str]:
        """Zones flagged (or High/Critical, M4) since start, in the order first seen."""
        return list(self._needing)

    def note_zone_needing(self, zone_id: str) -> None:
        self._remember_zone(zone_id)

    def _remember_zone(self, zone_id: str) -> None:
        """Add the zone to the set and persist the set (blocking; a no-op for a zone already there)."""
        if zone_id in self._needing:
            return
        self._needing[zone_id] = None
        saved = self._repo.get("settings", {"key": NEEDING_KEY})  # may not be loaded yet: never drop zones
        zones = list(dict.fromkeys([*((saved or {}).get("value") or ()), *self._needing]))
        self._repo.upsert(
            "settings",
            {"key": NEEDING_KEY, "value": zones, "updated_at": to_iso(self._clock.now())},
            sync=False,
        )

    def gaps(self, nodes: Iterable[Any] | None = None) -> list[GapSuggestion]:
        """Gap advice for the zones needing coverage that have no WQ/SP coverage (blocking)."""
        nodes = list(self._registry.nodes() if nodes is None else nodes)
        needing = [z for z in self.zones_needing() if z not in covered_set(nodes, self.grid)]
        if not needing:
            return []
        found = self._captures.latest_class_map() if self._captures is not None else None
        return gap_suggestions(needing, found[1] if found else None, nodes, grid=self.grid)

    def coverage_now(self, nodes: Iterable[Any] | None = None) -> m.Coverage:
        """I3 Coverage with the current gaps (blocking; for ``GET /coverage``)."""
        nodes = list(self._registry.nodes() if nodes is None else nodes)
        return coverage(nodes, self.gaps(nodes), site=self._site, grid=self.grid)

    async def _publish_coverage(self, nodes: list[Any]) -> None:
        cov = await to_thread_settled(self.coverage_now, nodes)
        self._bus.publish("coverage.updated", cov.model_dump(mode="json"))

    def _demo(self) -> Any:
        return self._settings.demo_values()


def _num(x: float) -> float | int:
    return int(x) if float(x).is_integer() else round(float(x), 3)


def _superseded(t: _Task, cmd: dict[str, Any]) -> bool:
    """A newer command has been issued to the same node in this task (it replaces ``cmd``: no retry)."""
    later = t.commands[t.commands.index(cmd) + 1 :]
    return any(c["node_id"] == cmd["node_id"] for c in later)


def _quiet(t: _Task, now: datetime) -> bool:
    """An ended task whose commands are all settled, last touched more than PRUNE_AFTER_S ago."""
    settled = all(c["ack_status"] != "pending" for c in t.commands)
    return settled and (now - from_iso(t.row["updated_at"])).total_seconds() > PRUNE_AFTER_S
