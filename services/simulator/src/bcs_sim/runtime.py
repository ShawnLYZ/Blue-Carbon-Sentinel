"""The simulator runtime: every simulated node, driven one ``step(now)`` at a time.

Per step (under ``self.lock``):
1. inbound ``cmd`` / ``config`` received since the last step are applied (``EdgeLogic.handle`` /
   ``apply_config``); acks are published to ``ack``;
2. per node: an active ``offline`` fault drops the connection without DISCONNECT (the broker fires
   the retained last will) and the node does nothing else; clearing the fault reconnects. Otherwise:
   ``EdgeLogic.tick`` (acks published) -> if due: readings pipeline -> ``FaultSet.shape_readings`` ->
   ``EdgeLogic.sample`` -> telemetry + events, plus ``drain_events()`` -> ``FaultSet.shape_outgoing``
   (called on every step, so held ``late`` messages are released) -> publish; a retained ``online``
   status is re-published when boot, mode or interval changes;
3. the replayer publishes its due lines (nodes being replayed pause live sampling meanwhile).

Acks and status go straight to the link (not through delivery faults); telemetry and events go
through them. A node whose link is not connected does not sample.

Transports are pluggable: ``client_factory`` (default ``NodeClient``; ``MemoryHub().factory`` needs no
broker). Credentials come from the Ground Station and live only in memory (``self.credentials``).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal, Protocol

from bcs_protocol.generated.config_schema import NodeConfig
from bcs_protocol.timefmt import to_iso
from bcs_protocol.validate import Command, ProtocolError, parse_message
from pydantic import BaseModel

from .client import ClientFactory, NodeClient, NodeLink, status_payload
from .clock import Clock
from .config import SimConfig
from .edge import EdgeLogic
from .environment import Environment
from .faults import FaultSet, OutgoingMsg
from .gs_client import SimNodeSpec
from .inspector import InspectorTap
from .nodes.battery import Battery
from .nodes.models import FW_VERSION, SimNode, produce_readings
from .overrides import Overrides
from .recorder import DEFAULT_SESSIONS_DIR, Recorder, Replayer
from .scenarios import ScenarioBook, grid_zone_bounds

log = logging.getLogger("bcs_sim.runtime")

TYPE_ORDER = {"water_quality": 0, "soil_probe": 1, "tide_gauge": 2}  # SimNode list order
ELEVATION_CM = {"water_quality": 0.0, "soil_probe": 80.0, "tide_gauge": 100.0}
LOW_BATTERY_DEFAULT_PCT = 10.0
STEP_S = 0.2
DEMO_INTERVALS = (30, 2)
PROTOCOL_INTERVALS = (900, 30)


class GsLike(Protocol):
    def registry(self) -> list[SimNodeSpec]: ...

    def credentials(self, node_ids: list[str] | None = None) -> dict[str, str]: ...

    def upload_session(self, meta: dict[str, Any], path: Path) -> Any: ...


# ---- K1 SimNode view ----------------------------------------------------------------------------------
class Position(BaseModel):
    e_m: float
    s_m: float


class LastCommand(BaseModel):
    id: str
    type: str
    at: str


class LastAck(BaseModel):
    status: str
    at: str


class OverrideView(BaseModel):
    value: float
    behaviour: Literal["hold", "drift"]


class SimNodeView(BaseModel):
    node_id: str
    node_type: str
    position: Position
    zone_label: str | None
    connected: bool
    mode: str
    interval_s: float
    readings: dict[str, float]
    natural: dict[str, float]
    overrides: dict[str, OverrideView]
    battery_pct: float
    rssi_dbm: float
    faults: dict[str, dict[str, Any]]
    last_command: LastCommand | None
    last_ack: LastAck | None
    source: Literal["simulated"] = "simulated"


# ---- per node ---------------------------------------------------------------------------------------------
class NodeFaults(FaultSet):
    """A FaultSet that also applies ``low_battery`` to the node's Battery when injected."""

    def __init__(self, seed: int, clock: Clock, battery: Battery) -> None:
        super().__init__(seed, clock)
        self._battery = battery

    def inject(self, kind: str, params: dict[str, Any] | None = None) -> None:
        super().inject(kind, params)
        if kind == "low_battery":
            self._battery.set(float((params or {}).get("pct", LOW_BATTERY_DEFAULT_PCT)))


@dataclass
class NodeRuntime:
    spec: SimNodeSpec
    node: SimNode
    edge: EdgeLogic
    faults: NodeFaults
    link: NodeLink
    readings: dict[str, float] = field(default_factory=dict)
    natural: dict[str, float] = field(default_factory=dict)
    last_command: LastCommand | None = None
    last_ack: LastAck | None = None
    announced_boot: str | None = None
    status_key: tuple[str, str, float] | None = None
    config_version: int | None = None
    dropped: bool = False

    @property
    def node_id(self) -> str:
        return self.spec.node_id


def default_node_config(site_id: str, node_id: str, demo_time_scale: bool, at: datetime) -> NodeConfig:
    """What a node runs before the Ground Station's retained config arrives (G3 defaults)."""
    base, inv = DEMO_INTERVALS if demo_time_scale else PROTOCOL_INTERVALS
    return NodeConfig.model_validate(
        {
            "schema": "bcs.config.v1",
            "site_id": site_id,
            "node_id": node_id,
            "config_version": 0,
            "issued_at": to_iso(at),
            "demo_time_scale": demo_time_scale,
            "baseline_interval_s": base,
            "investigation_interval_s": inv,
            "anomaly": {"window": 30, "z_threshold": 3.0, "stuck_window": 10, "stuck_epsilon": {}},
            "critical_bands": {},
            "battery_low_pct": 15,
        }
    )


def _node_seed(seed: int, node_id: str) -> int:
    return zlib.crc32(f"{seed}:{node_id}".encode())


class Runtime:
    def __init__(
        self,
        cfg: SimConfig,
        gs: GsLike,
        clock: Clock,
        seed: int,
        *,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        client_factory: ClientFactory | None = None,
        sessions_dir: Path | None = None,
        demo_time_scale: bool = True,
        zone_bounds: dict[str, tuple[float, float, float, float]] | None = None,
        connect_timeout_s: float = 10.0,
        watch_registry: bool = True,
    ) -> None:
        self.cfg = cfg
        self.gs = gs
        self.clock = clock
        self.seed = seed
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_factory: ClientFactory = client_factory or NodeClient
        self.demo_time_scale = demo_time_scale
        self.zone_bounds = zone_bounds if zone_bounds is not None else grid_zone_bounds()
        self.connect_timeout_s = connect_timeout_s
        self.watch_registry = watch_registry

        self.lock = threading.RLock()
        self.env = Environment(cfg, seed, clock)
        self.scenarios = ScenarioBook(clock)
        self.overrides = Overrides(clock)
        self.inspector = InspectorTap(clock)
        self.nodes: dict[str, NodeRuntime] = {}
        self.credentials: dict[str, str] = {}
        self.recorder = Recorder(
            clock,
            self.inspector,
            gs,
            seed=seed,
            nodes=self._session_nodes,
            sessions_dir=sessions_dir if sessions_dir is not None else DEFAULT_SESSIONS_DIR,
        )
        self.replayer = Replayer(clock, self._publish_raw, lambda: set(self.nodes))
        self.started = False
        self._inbox: queue.SimpleQueue[tuple[str, str, bytes]] = queue.SimpleQueue()
        self._registry_lock = threading.Lock()  # one registry reload at a time (watcher, API, runner)
        self._watcher: Any = None
        self._loop: threading.Thread | None = None
        self._loop_stop = threading.Event()

    # ---- lifecycle -------------------------------------------------------------------------------------
    def start(self) -> None:
        """Load the registry and credentials, then connect every node (waits up to ``connect_timeout_s``)."""
        specs = self.gs.registry()
        creds = self.gs.credentials(None)
        with self.lock:
            for spec in specs:
                if spec.node_id not in creds:
                    log.warning("%s: no credentials from the Ground Station; not started", spec.node_id)
                    continue
                self._add_node(spec, creds[spec.node_id])
            self.started = True
        self._wait_connected(list(self.nodes.values()))
        if self.watch_registry and hasattr(self.gs, "watch_registry"):
            self._watcher = self.gs.watch_registry(self._on_registry_event)

    def _wait_connected(self, nrs: list[NodeRuntime]) -> None:
        deadline = time.monotonic() + self.connect_timeout_s
        for nr in nrs:
            if not nr.link.wait_connected(max(0.0, deadline - time.monotonic())):
                log.warning("%s: not connected to the broker yet", nr.node_id)

    def run_background(self, period_s: float = STEP_S) -> threading.Thread:
        """Call ``step(clock.now())`` every ``period_s`` in a daemon thread until ``stop()``."""
        if self._loop is not None and self._loop.is_alive():
            return self._loop
        self._loop_stop.clear()

        def loop() -> None:
            while not self._loop_stop.wait(period_s):
                try:
                    self.step(self.clock.now())
                except Exception:
                    log.exception("runtime step failed")

        self._loop = threading.Thread(target=loop, name="bcs-sim-runtime", daemon=True)
        self._loop.start()
        return self._loop

    def stop(self) -> None:
        self._loop_stop.set()
        if self._loop is not None and self._loop is not threading.current_thread():
            self._loop.join(5)
        self._loop = None
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:
                log.exception("registry watcher stop failed")
            self._watcher = None
        if self.recorder.active:
            try:
                self.recorder.stop()
            except Exception:
                log.exception("recorder stop failed")
        self.replayer.stop()
        with self.lock:
            for nr in self.nodes.values():
                nr.link.close()
            self.started = False

    # ---- nodes -----------------------------------------------------------------------------------------
    def _add_node(self, spec: SimNodeSpec, password: str) -> NodeRuntime:
        nseed = _node_seed(self.seed, spec.node_id)
        node = SimNode(
            spec.node_id,
            spec.node_type,
            spec.e_m,
            spec.s_m,
            ELEVATION_CM.get(spec.node_type, 0.0),
            seed=nseed,
            site_id=spec.site_id,
        )
        now = self.clock.now()
        edge = EdgeLogic(
            node, default_node_config(spec.site_id, spec.node_id, self.demo_time_scale, now), self.clock
        )
        faults = NodeFaults(nseed, self.clock, node.battery)
        link = self._make_link(spec, password)
        nr = NodeRuntime(spec, node, edge, faults, link)
        nr.status_key = self._status_key(nr)
        self.nodes[spec.node_id] = nr
        self.credentials[spec.node_id] = password
        link.connect()
        return nr

    def _make_link(self, spec: SimNodeSpec, password: str) -> NodeLink:
        nid = spec.node_id
        return self.client_factory(
            node_id=nid,
            password=password,
            broker_host=self.broker_host,
            broker_port=self.broker_port,
            site_id=spec.site_id,
            on_cmd=partial(self._inbound, nid, "cmd"),
            on_config=partial(self._inbound, nid, "config"),
            tap=self.inspector,
            clock=self.clock,
            status_fields=partial(self._status_fields, nid),
            boot_event=partial(self._boot_event, nid),
        )

    def _remove_node(self, node_id: str) -> None:
        nr = self.nodes.get(node_id)
        if nr is not None:
            nr.link.close()  # needs the node for its shutdown status, so close before forgetting it
        self.nodes.pop(node_id, None)
        self.credentials.pop(node_id, None)
        self.overrides.clear(node_id)

    def faults(self, node_id: str) -> NodeFaults:
        return self.nodes[node_id].faults

    def _status_key(self, nr: NodeRuntime) -> tuple[str, str, float]:
        return (nr.node.boot_id, nr.edge.mode, nr.edge.interval_s())

    def _status_fields(self, node_id: str) -> dict[str, Any]:
        nr = self.nodes.get(node_id)
        if nr is None:  # removed while its transport was (re)connecting
            return {"boot_id": "0" * 12, "mode": "baseline", "interval_s": None, "fw_version": FW_VERSION}
        return {
            "boot_id": nr.node.boot_id,
            "mode": nr.edge.mode,
            "interval_s": nr.edge.interval_s(),
            "fw_version": FW_VERSION,
        }

    def _boot_event(self, node_id: str) -> bytes | None:
        """Announce each boot once (a reconnect of the same boot sends no boot event)."""
        nr = self.nodes.get(node_id)
        if nr is None or nr.announced_boot == nr.node.boot_id:
            return None
        nr.announced_boot = nr.node.boot_id
        return nr.edge.boot_event(self.clock.now()).model_dump_json(by_alias=True).encode()

    def _session_nodes(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {"node_id": n.node_id, "node_type": n.node.node_type, "e_m": n.node.e_m, "s_m": n.node.s_m}
                for n in self.nodes.values()
            ]

    # ---- registry changes ---------------------------------------------------------------------------------
    def _on_registry_event(self, data: dict[str, Any]) -> None:
        self.on_registry_change(data)

    def on_registry_change(self, change: dict[str, Any] | None = None) -> None:
        """Reload the registry: start new nodes, stop removed ones, move moved ones, and reconnect nodes
        whose key was regenerated (``change = {"change": "key_regenerated", "node_ids": [...]}``).

        Reloads are serialised: two overlapping ones would each rotate a new node's credentials, and the
        node would then connect with the older, already replaced password."""
        with self._registry_lock:
            self._reload_registry(change)

    def _reload_registry(self, change: dict[str, Any] | None) -> None:
        specs = {s.node_id: s for s in self.gs.registry()}
        with self.lock:
            for nid in [n for n in self.nodes if n not in specs]:
                self._remove_node(nid)
            for nid, nr in self.nodes.items():
                s = specs[nid]
                if (s.e_m, s.s_m, s.zone_label) != (nr.spec.e_m, nr.spec.s_m, nr.spec.zone_label):
                    nr.spec = s
                    nr.node.e_m, nr.node.s_m = s.e_m, s.s_m
            added = sorted(n for n in specs if n not in self.nodes)
            regen: list[str] = []
            if change and change.get("change") == "key_regenerated":
                regen = sorted(n for n in change.get("node_ids") or [] if n in self.nodes)
        wanted = added + regen
        if not wanted:
            return
        creds = self.gs.credentials(wanted)
        new: list[NodeRuntime] = []
        with self.lock:
            for nid in added:
                if nid in creds and nid not in self.nodes:
                    new.append(self._add_node(specs[nid], creds[nid]))
            for nid in regen:
                nr = self.nodes.get(nid)
                if nr is None or nid not in creds:
                    continue
                nr.link.close()
                nr.link = self._make_link(nr.spec, creds[nid])
                self.credentials[nid] = creds[nid]
                nr.dropped = False
                nr.link.connect()
                new.append(nr)
        self._wait_connected(new)

    # ---- inbound --------------------------------------------------------------------------------------------
    def _inbound(self, node_id: str, channel: str, payload: bytes) -> None:
        """Called by the transport (possibly on its network thread); applied at the next step."""
        self._inbox.put((node_id, channel, payload))

    def _process_inbox(self, now: datetime) -> None:
        while True:
            try:
                nid, channel, payload = self._inbox.get_nowait()
            except queue.Empty:
                return
            nr = self.nodes.get(nid)
            if nr is None:
                continue
            try:
                msg = parse_message(channel, payload)
            except ProtocolError as exc:
                log.warning("%s: ignoring invalid %s (%s)", nid, channel, "; ".join(exc.errors)[:200])
                continue
            if msg.node_id != nid or msg.site_id != nr.spec.site_id:
                log.warning("%s: ignoring %s addressed to %s/%s", nid, channel, msg.site_id, msg.node_id)
                continue
            if isinstance(msg, Command):
                nr.last_command = LastCommand(id=msg.command_id, type=msg.type, at=to_iso(now))
                for ack in nr.edge.handle(msg, now):
                    self._publish_ack(nr, ack)
            elif isinstance(msg, NodeConfig):
                if msg.config_version == nr.config_version:
                    continue  # retained re-delivery of the config already applied
                nr.edge.apply_config(msg)
                nr.config_version = msg.config_version

    def _publish_ack(self, nr: NodeRuntime, ack: Any) -> None:
        if nr.link.publish("ack", ack.model_dump_json(by_alias=True).encode()):
            nr.last_ack = LastAck(status=ack.status, at=ack.at)

    # ---- stepping ---------------------------------------------------------------------------------------------
    def step(self, now: datetime) -> None:
        with self.lock:
            self._process_inbox(now)
            paused = self.replayer.node_ids
            for nr in list(self.nodes.values()):
                self._step_node(nr, now, sample=nr.node_id not in paused)
            self.replayer.step(now)

    def _step_node(self, nr: NodeRuntime, now: datetime, *, sample: bool) -> None:
        f, edge, node = nr.faults, nr.edge, nr.node
        if f.is_offline():
            if not nr.dropped:
                nr.link.drop()
                nr.dropped = True
            return
        if nr.dropped:
            nr.dropped = False
            nr.link.connect()
        if not nr.link.connected:
            return
        for ack in edge.tick(now):
            self._publish_ack(nr, ack)
        msgs: list[OutgoingMsg] = []
        # Queued events (config_applied, boot) were created before this sample: publish them first so
        # the publish order follows the per-boot event seq.
        for ev in edge.drain_events():
            if ev.kind == "boot":
                nr.announced_boot = ev.boot_id
            msgs.append(self._out(nr, "event", ev))
        if sample and edge.due(now):
            readings = produce_readings(
                node, self.env, self.scenarios, self.overrides, self.zone_bounds, now, node.rng
            )
            nr.natural = {
                k: round(v, 3)
                for k, v in self.env.natural(
                    node.node_type, node.e_m, node.s_m, node.elevation_cm, now, node.node_id
                ).items()
            }
            readings = f.shape_readings(readings, now)
            tel, events = edge.sample(readings, node.health(now), now)
            nr.readings = dict(readings)
            msgs.append(self._out(nr, "telemetry", tel))
            msgs += [self._out(nr, "event", ev) for ev in events]
        for m in f.shape_outgoing(msgs, now, interval_s=edge.interval_s()):
            nr.link.publish(m.channel, m.payload)
        key = self._status_key(nr)
        if key != nr.status_key:
            nr.status_key = key
            nr.link.publish(
                "status",
                status_payload(
                    nr.spec.site_id, nr.node_id, "online", now, None, self._status_fields(nr.node_id)
                ),
            )

    @staticmethod
    def _out(nr: NodeRuntime, channel: str, model: Any) -> OutgoingMsg:
        return OutgoingMsg(
            nr.node_id,
            channel,
            model.model_dump_json(by_alias=True).encode(),
            getattr(model, "seq", 0),
            qos=1,
        )

    def _publish_raw(self, node_id: str, channel: str, payload: bytes) -> bool:
        nr = self.nodes.get(node_id)
        if nr is None or nr.faults.is_offline():
            return False
        return nr.link.publish(channel, payload)

    # ---- views -------------------------------------------------------------------------------------------------
    def _live(self, nr: NodeRuntime, now: datetime) -> tuple[dict[str, float], dict[str, float]]:
        """(readings, natural) the node would measure at ``now``: the readings pipeline without noise (no rng
        draw, so published values stay seed-deterministic) and the fault preview (stuck value, drift)."""
        node = nr.node
        readings = produce_readings(
            node, self.env, self.scenarios, self.overrides, self.zone_bounds, now, None, noise_scale=0.0
        )
        natural = self.env.natural(node.node_type, node.e_m, node.s_m, node.elevation_cm, now, node.node_id)
        return nr.faults.preview_readings(readings, now), {k: round(v, 3) for k, v in natural.items()}

    def state(self, live: bool = True) -> list[SimNodeView]:
        """The K1 SimNode view of every node: water quality, soil probes, then tide gauges, each by node ID. ``live``: ``readings`` and ``natural`` are
        what each node would measure now (a scenario or override shows at once, between samples); else
        the last sampled values."""
        with self.lock:
            now = self.clock.now()
            out = []
            for nr in sorted(
                self.nodes.values(), key=lambda n: (TYPE_ORDER.get(n.node.node_type, 9), n.node_id)
            ):
                readings, natural = self._live(nr, now) if live else (dict(nr.readings), dict(nr.natural))
                ovr = {
                    param: OverrideView(value=o.value, behaviour=o.behaviour)
                    for (_nid, param), o in self.overrides.active(nr.node_id).items()
                }
                out.append(
                    SimNodeView(
                        node_id=nr.node_id,
                        node_type=nr.node.node_type,
                        position=Position(e_m=nr.node.e_m, s_m=nr.node.s_m),
                        zone_label=nr.spec.zone_label,
                        connected=nr.link.connected,
                        mode=nr.edge.mode,
                        interval_s=nr.edge.interval_s(),
                        readings=readings,
                        natural=natural,
                        overrides=ovr,
                        battery_pct=round(nr.node.battery.pct, 2),
                        rssi_dbm=nr.node.rssi_dbm,
                        faults=nr.faults.active(),
                        last_command=nr.last_command,
                        last_ack=nr.last_ack,
                    )
                )
            return out


class RuntimeSupervisor:
    """Owns the runtime of ``bcs-sim run``: keeps trying ``Runtime.start()`` until the Ground Station
    answers (every ``retry_s``), then runs the 200 ms step loop. ``stop()`` ends both."""

    def __init__(
        self, factory: Callable[[], Runtime], *, retry_s: float = 5.0, period_s: float = STEP_S
    ) -> None:
        self.factory = factory
        self.retry_s = retry_s
        self.period_s = period_s
        self.runtime: Runtime | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bcs-sim-supervisor", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            rt = self.factory()
            try:
                rt.start()
            except Exception as exc:  # noqa: BLE001 - Ground Station absent or not ready yet
                msg = f"{type(exc).__name__}: {exc}"[:300]
                if msg != self.last_error:
                    log.warning("runtime start failed, retrying every %.0f s: %s", self.retry_s, msg)
                self.last_error = msg
                rt.stop()
                self._stop.wait(self.retry_s)
                continue
            self.last_error = None
            self.runtime = rt
            if self._stop.is_set():
                break
            rt.run_background(self.period_s)
            return

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(15)
        if self.runtime is not None:
            self.runtime.stop()
