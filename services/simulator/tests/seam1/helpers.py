"""Seam-1 helpers for the simulator runtime: a fake Ground Station client over the fixture broker,
MQTT observers and a few waiting helpers. Test code only (it may import ``bcs_gs``)."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from bcs_gs.nodes.broker_admin import BrokerAdmin
from bcs_sim.clock import ManualClock
from bcs_sim.config import SimConfig, load_sim_config
from bcs_sim.gs_client import SimNodeSpec
from bcs_sim.runtime import Runtime

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)
SITE = "KSL"
TICK_S = 0.2

# Fixed positions (metres east/south of the site origin), zones of the 5 x 5 grid.
NODES_8: list[tuple[str, str, float, float, str]] = [
    ("WQ-01", "water_quality", 50.0, 50.0, "A1"),
    ("WQ-02", "water_quality", 160.0, 250.0, "B3"),
    ("WQ-03", "water_quality", 350.0, 150.0, "D2"),
    ("WQ-04", "water_quality", 250.0, 400.0, "C5"),
    ("SP-01", "soil_probe", 150.0, 150.0, "B2"),
    ("SP-02", "soil_probe", 140.0, 260.0, "B3"),
    ("SP-03", "soil_probe", 150.0, 370.0, "B4"),
    ("TG-01", "tide_gauge", 250.0, 250.0, "C3"),
]


def cfg() -> SimConfig:
    return load_sim_config()


def specs_8() -> list[SimNodeSpec]:
    return [SimNodeSpec(n, t, e, s, z, SITE) for n, t, e, s, z in NODES_8]


def admin_for(broker: Any) -> BrokerAdmin:
    return BrokerAdmin(broker.host, broker.port, broker.admin_user, broker.admin_password)


class FakeGs:
    """A GsClient stand-in: fixed registry; ``credentials`` creates/updates broker identities."""

    def __init__(self, broker: Any, specs: list[SimNodeSpec] | None = None) -> None:
        self.broker = broker
        self.specs = list(specs if specs is not None else specs_8())
        self.uploads: list[tuple[dict[str, Any], Path]] = []
        self.issued: dict[str, str] = {}

    def registry(self) -> list[SimNodeSpec]:
        return list(self.specs)

    def credentials(self, node_ids: list[str] | None = None) -> dict[str, str]:
        ids = node_ids if node_ids is not None else [s.node_id for s in self.specs]
        admin = admin_for(self.broker) if self.broker is not None else None
        out: dict[str, str] = {}
        for nid in ids:
            pw = secrets.token_urlsafe(24)
            if admin is not None:
                site = next((s.site_id for s in self.specs if s.node_id == nid), SITE)
                admin.ensure_node(nid, site, pw)
            out[nid] = pw
        self.issued.update(out)
        return out

    def upload_session(self, meta: dict[str, Any], path: Path) -> dict[str, Any]:
        self.uploads.append((meta, Path(path)))
        return {"id": meta["id"]}

    def watch_registry(self, callback: Callable[[dict[str, Any]], None]) -> Any:
        return None


# ---- runtime driving ----------------------------------------------------------------------------
def start_rt(broker: Any, gs: Any, **kw: Any) -> tuple[Runtime, ManualClock]:
    clock = ManualClock(T0)
    rt = Runtime(cfg(), gs, clock, seed=42, broker_host=broker.host, broker_port=broker.port, **kw)
    rt.start()
    _RUNTIMES.append(rt)
    return rt, clock


def run_for(rt: Runtime, clock: ManualClock, seconds: float) -> None:
    for _ in range(round(seconds / TICK_S)):
        clock.advance(TICK_S)
        rt.step(clock.now())


async def eventually(pred: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if pred():
            return
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


def topic_node(topic: str) -> str:
    return topic.split("/")[4]


# ---- observers ------------------------------------------------------------------------------------
_OBSERVERS: list[mqtt.Client] = []
_RUNTIMES: list[Runtime] = []
_ids = itertools.count()
_observer_pw: dict[int, str] = {}


def _observer_identity(broker: Any) -> tuple[str, str]:
    """An observer identity allowed to subscribe to (and receive) every ``bcs/`` topic."""
    key = broker.port
    if key not in _observer_pw:
        pw = secrets.token_urlsafe(24)
        acls = [
            {"acltype": t, "topic": "bcs/#", "priority": 0, "allow": True}
            for t in ("subscribePattern", "publishClientReceive")
        ]
        admin_for(broker)._ensure_client("observer", pw, "observer", acls, bind_clientid=False)
        _observer_pw[key] = pw
    return "observer", _observer_pw[key]


@dataclass
class Captured:
    topic: str
    payload: bytes
    retain: bool


def _observe(broker: Any, topic_filter: str, on_msg: Callable[[Captured], None]) -> mqtt.Client:
    user, pw = _observer_identity(broker)
    c = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"observer-{next(_ids)}", protocol=mqtt.MQTTv5
    )
    c.username_pw_set(user, pw)
    subscribed = threading.Event()

    def on_connect(cl: Any, _u: Any, _f: Any, rc: Any, _p: Any) -> None:
        if not rc.is_failure:
            cl.subscribe(topic_filter, qos=1)

    def on_subscribe(*_a: Any) -> None:
        subscribed.set()

    def on_message(_c: Any, _u: Any, msg: Any) -> None:
        on_msg(Captured(msg.topic, bytes(msg.payload), bool(msg.retain)))

    c.on_connect, c.on_subscribe, c.on_message = on_connect, on_subscribe, on_message
    c.connect(broker.host, broker.port, keepalive=30)
    c.loop_start()
    if not subscribed.wait(5):
        raise RuntimeError("observer could not subscribe")
    _OBSERVERS.append(c)
    return c


def subscribe_all(broker: Any, topic_filter: str) -> list[str]:
    """A live list of the topics of every message published on ``topic_filter`` from now on."""
    got: list[str] = []
    _observe(broker, topic_filter, lambda m: got.append(m.topic))
    return got


def capture_published(broker: Any) -> list[Captured]:
    got: list[Captured] = []
    _observe(broker, "bcs/#", got.append)
    return got


def retained_status(broker: Any, node_id: str, site: str = SITE) -> dict[str, Any]:
    got: list[Captured] = []
    c = _observe(broker, f"bcs/v1/{site}/nodes/{node_id}/status", got.append)
    deadline = time.monotonic() + 1.0
    while not got and time.monotonic() < deadline:
        time.sleep(0.02)
    _OBSERVERS.remove(c)
    c.disconnect()
    c.loop_stop()
    return json.loads(got[-1].payload) if got else {"state": None}


def gs_publisher(broker: Any) -> mqtt.Client:
    """A connected client with the Ground Station's ``bcs-gs`` identity (publishes cmd/config)."""
    pw = secrets.token_urlsafe(24)
    admin_for(broker).ensure_service_identity("bcs-gs", pw)
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bcs-gs-{next(_ids)}", protocol=mqtt.MQTTv5)
    c.username_pw_set("bcs-gs", pw)
    ready = threading.Event()
    c.on_connect = lambda *_a: ready.set()
    c.connect(broker.host, broker.port, keepalive=30)
    c.loop_start()
    if not ready.wait(5):
        raise RuntimeError("bcs-gs publisher could not connect")
    _OBSERVERS.append(c)
    return c


def original_boot_ids(meta: Any) -> set[str]:
    lines = Path(meta.path).read_text(encoding="utf-8").splitlines()[1:]
    out: set[str] = set()
    for line in lines:
        p = json.loads(line)["payload"]
        if isinstance(p, dict) and "boot_id" in p:
            out.add(p["boot_id"])
    return out


def cleanup() -> None:
    while _RUNTIMES:
        with contextlib.suppress(Exception):  # best effort teardown
            _RUNTIMES.pop().stop()
    while _OBSERVERS:
        c = _OBSERVERS.pop()
        c.disconnect()
        c.loop_stop()
    _observer_pw.clear()
