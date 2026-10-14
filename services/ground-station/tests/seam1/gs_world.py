"""The seam-1 ``world`` (Tasks 9-11): a Ground Station against a real Mosquitto with telemetry ingest
running and the 8 standard simulated nodes registered, plus test publishers that act as those nodes.

- ``world.node(id)``: a ``TestNode`` connected with the node's real credentials (client ID = node ID,
  retained last will, retained ``online`` status on connect). ``publish_telemetry(seq, sampled_at=...)``,
  ``publish_event(kind)``, ``publish_ack(command_id)``, ``publish_raw(channel, bytes)`` return once the
  ingest has handled the message; ``drop()`` closes the socket without DISCONNECT (the last will fires).
- ``world.events()`` (async context; ``wait_for(type, pred(data))`` sees events from then on),
  ``world.wait_event(type, pred(data))`` (every event since the world started),
  ``world.wait_status(id, state)``, ``world.rows(table, **filters)`` (insertion order),
  ``world.retained(topic)``, ``world.ingest``, ``world.http``, ``world.clock`` (ManualClock),
  ``world.registry``, ``world.gs`` (the GsBroker), ``await world.publish_node_event(id, kind, **over)``,
  ``await world.raise_alert(type, **kw)`` (AlertService in-process, no HTTP route).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import threading
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
import pytest
from bcs_protocol.timefmt import to_iso
from gs_seam1_helpers import STANDARD_8
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

READINGS: dict[str, dict[str, float]] = {
    "water_quality": {"salinity_psu": 28.0, "turbidity_ntu": 12.0, "do_mg_l": 6.5, "temp_c": 29.0, "ph": 7.6},
    "soil_probe": {"porewater_salinity_psu": 35.0, "soil_moisture_pct": 60.0},
    "tide_gauge": {"water_level_cm": 20.0},
}
HEALTH = {"battery_pct": 90.0, "rssi_dbm": -60.0, "uptime_s": 10.0, "fw_version": "test-1.0.0"}


class EventRecorder:
    """Every ``/ws/events`` envelope since the world started; waits match ``pred(data)``."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.items: list[dict[str, Any]] = []
        self._new = asyncio.Event()
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        from websockets.asyncio.client import connect

        self._ws = await connect(self._url)
        self._task = asyncio.create_task(self._pump())
        await self.wait("hello")

    async def _pump(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self._ws:
                self.items.append(json.loads(raw))
                self._new.set()

    async def stop(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def wait(
        self, type: str, pred: Any = None, *, start: int = 0, timeout: float = 5
    ) -> dict[str, Any]:
        i = start
        deadline = time.monotonic() + timeout
        while True:
            while i < len(self.items):
                e = self.items[i]
                i += 1
                if e["type"] == type and (pred is None or pred(e["data"])):
                    return e
            self._new.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"no {type} event matched within {timeout} s")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._new.wait(), remaining)


class EventView:
    """Events recorded from the moment the view was opened."""

    def __init__(self, rec: EventRecorder) -> None:
        self._rec = rec
        self.start = len(rec.items)

    async def wait_for(self, type: str, pred: Any = None, timeout: float = 5) -> dict[str, Any]:
        return await self._rec.wait(type, pred, start=self.start, timeout=timeout)

    def all(self, type: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self._rec.items[self.start :] if type is None or e["type"] == type]


class TestNode:
    """A test publisher acting as a registered node."""

    __test__ = False

    def __init__(self, world: World, node_id: str, node_type: str, password: str) -> None:
        self.world, self.node_id, self.node_type = world, node_id, node_type
        self.site_id = world.site_id
        self.boot_id = secrets.token_hex(6)
        self.event_seq = 0
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node_id, protocol=mqtt.MQTTv5)
        c.username_pw_set(node_id, password)
        c.will_set(self.topic("status"), self._status("offline", "last_will"), qos=1, retain=True)
        connected = threading.Event()
        c.on_connect = lambda *_a: connected.set()
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = 0
        c.connect(world.broker.host, world.broker.port, keepalive=30, clean_start=True, properties=props)
        c.loop_start()
        if not connected.wait(5):
            raise RuntimeError(f"{node_id} could not connect")
        self.client = c
        self._publish("status", self._status("online", None), retain=True)

    def topic(self, channel: str) -> str:
        return f"bcs/v1/{self.site_id}/nodes/{self.node_id}/{channel}"

    def _status(self, state: str, reason: str | None, **over: Any) -> bytes:
        online = state == "online"
        doc = {
            "schema": "bcs.status.v1", "site_id": self.site_id, "node_id": self.node_id, "state": state,
            "at": to_iso(self.world.clock.now()), "reason": reason, "mode": "baseline" if online else None,
            "interval_s": 30.0 if online else None, "fw_version": "test-1.0.0", "boot_id": self.boot_id,
            "source": "simulated", "replay": False,
        }  # fmt: skip
        doc.update(over)
        return json.dumps(doc).encode()

    def _publish(self, channel: str, payload: bytes, *, retain: bool = False, wait: bool = True) -> None:
        ingest = self.world.ingest
        before = ingest.handled(self.node_id, channel)
        self.client.publish(self.topic(channel), payload, qos=1, retain=retain).wait_for_publish(5)
        if not wait:
            return
        deadline = time.monotonic() + 5
        while ingest.handled(self.node_id, channel) <= before:
            if time.monotonic() > deadline:
                raise AssertionError(f"ingest did not handle {self.node_id}/{channel}")
            time.sleep(0.005)

    def telemetry(self, seq: int, sampled_at: datetime | None = None, **over: Any) -> dict[str, Any]:
        doc = {
            "schema": "bcs.telemetry.v1", "site_id": self.site_id, "node_id": self.node_id,
            "node_type": self.node_type, "boot_id": self.boot_id, "seq": seq,
            "sampled_at": to_iso(sampled_at or self.world.clock.now()), "mode": "baseline",
            "readings": dict(READINGS[self.node_type]), "health": dict(HEALTH), "flags": [],
            "source": "simulated", "replay": False,
        }  # fmt: skip
        doc.update(over)
        return doc

    def publish_telemetry(self, seq: int, sampled_at: datetime | None = None, **over: Any) -> None:
        self._publish("telemetry", json.dumps(self.telemetry(seq, sampled_at, **over)).encode())

    def publish_status(self, state: str = "online", reason: str | None = None, **over: Any) -> None:
        self._publish("status", self._status(state, reason, **over), retain=True)

    def publish_event(self, kind: str, *, seq: int | None = None, **over: Any) -> int:
        if seq is None:
            seq, self.event_seq = self.event_seq, self.event_seq + 1
        doc = {
            "schema": "bcs.event.v1", "site_id": self.site_id, "node_id": self.node_id, "boot_id": self.boot_id,
            "seq": seq, "at": to_iso(self.world.clock.now()), "kind": kind, "parameter": None, "value": None,
            "score": None, "details": {}, "source": "simulated", "replay": False,
        }  # fmt: skip
        doc.update(over)
        self._publish("event", json.dumps(doc).encode())
        return seq

    def publish_ack(self, command_id: str, status: str = "accepted") -> None:
        doc = {
            "schema": "bcs.ack.v1", "site_id": self.site_id, "node_id": self.node_id, "command_id": command_id,
            "at": to_iso(self.world.clock.now()), "status": status, "reason": None, "source": "simulated",
            "replay": False,
        }  # fmt: skip
        self._publish("ack", json.dumps(doc).encode())

    def publish_raw(self, channel: str, payload: bytes, *, retain: bool = False) -> None:
        self._publish(channel, payload, retain=retain)

    def drop(self) -> None:
        """Close the socket without DISCONNECT: the broker publishes the last will."""
        c = self.client
        c.loop_stop()
        sock = c.socket()
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.client.disconnect()
            self.client.loop_stop()


class World:
    def __init__(self, gsb: Any, keys: dict[str, str], types: dict[str, str], rec: EventRecorder) -> None:
        self.gs = gsb
        self.broker = gsb.mqtt
        self.keys, self.types = keys, types
        self.recorder = rec
        self.site_id = gsb.services.site.site().id
        self._nodes: dict[str, TestNode] = {}
        self._observer: tuple[str, str] | None = None

    @property
    def ingest(self) -> Any:
        return self.gs.services.ingest

    @property
    def http(self) -> Any:
        return self.gs.http

    @property
    def clock(self) -> Any:
        return self.gs.clock

    @property
    def registry(self) -> Any:
        return self.gs.services.nodes

    @property
    def cloud(self) -> Any:
        return self.gs.cloud

    @property
    def sync(self) -> Any:
        """``await world.sync.drain_once()``: one sync pass on the Ground Station's loop."""
        from gs_forecast import on_gs_loop

        worker = self.gs.services.sync

        class _Sync:
            @staticmethod
            async def drain_once() -> Any:
                return await on_gs_loop(self, worker.drain_once)

        return _Sync()

    def node(self, node_id: str) -> TestNode:
        if node_id not in self._nodes:
            self._nodes[node_id] = TestNode(self, node_id, self.types[node_id], self.keys[node_id])
        return self._nodes[node_id]

    def events(self) -> Any:
        @contextlib.asynccontextmanager
        async def view() -> AsyncIterator[EventView]:
            yield EventView(self.recorder)

        return view()

    async def publish_node_event(self, node_id: str, kind: str = "anomaly", **over: Any) -> int:
        """A node event as the (test) node publishes it; returns once the ingest has handled it."""
        return await asyncio.to_thread(lambda: self.node(node_id).publish_event(kind, **over))

    async def raise_alert(self, type: str, **kw: Any) -> dict[str, Any]:
        """Raise an alert through AlertService in-process (no HTTP route) and return it as an Alert dict."""
        svc = self.gs.services
        kw.setdefault("message", f"test {type}")

        async def go() -> dict[str, Any]:
            return svc.alerts.raise_(type, **kw).model_dump(mode="json")

        loop = svc.tasking.loop
        assert loop is not None, "services not started"
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(go(), loop))

    async def wait_event(self, type: str, pred: Any = None, timeout: float = 5) -> dict[str, Any]:
        return await self.recorder.wait(type, pred, timeout=timeout)

    async def wait_status(self, node_id: str, state: str, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while True:
            row = await asyncio.to_thread(self.registry.get, node_id)
            if row is not None and row.status == state:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"{node_id} status {row.status if row else None!r}, wanted {state!r}")
            await asyncio.sleep(0.02)

    async def rows(self, table: str, **filters: Any) -> list[dict[str, Any]]:
        where = " AND ".join(f'"{k}" = ?' for k in filters)
        sql = f'SELECT * FROM "{table}"' + (f" WHERE {where}" if where else "") + " ORDER BY rowid"
        return await asyncio.to_thread(self.gs.repo.query, sql, tuple(filters.values()), table=table)

    def _observer_identity(self) -> tuple[str, str]:
        if self._observer is None:
            from bcs_gs.nodes.broker_admin import BrokerAdmin

            pw = secrets.token_urlsafe(24)
            acls = [
                {"acltype": t, "topic": "bcs/#", "priority": 0, "allow": True}
                for t in ("subscribePattern", "publishClientReceive")
            ]
            b = self.broker
            BrokerAdmin(b.host, b.port, b.admin_user, b.admin_password)._ensure_client(
                "observer", pw, "observer", acls, bind_clientid=False
            )
            self._observer = ("observer", pw)
        return self._observer

    async def retained(self, topic: str, timeout: float = 5) -> dict[str, Any]:
        """The retained (or next) message on ``topic``, decoded as JSON."""
        user, pw = await asyncio.to_thread(self._observer_identity)

        def fetch() -> bytes | None:
            got: list[bytes] = []
            done = threading.Event()
            c = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=f"observer-{secrets.token_hex(4)}",
                protocol=mqtt.MQTTv5,
            )  # fmt: skip
            c.username_pw_set(user, pw)
            c.on_connect = lambda cl, *_a: cl.subscribe(topic, qos=1)

            def on_message(_c: Any, _u: Any, msg: Any) -> None:
                if msg.payload:
                    got.append(bytes(msg.payload))
                    done.set()

            c.on_message = on_message
            c.connect(self.broker.host, self.broker.port, keepalive=30)
            c.loop_start()
            try:
                done.wait(timeout)
                return got[0] if got else None
            finally:
                c.disconnect()
                c.loop_stop()

        raw = await asyncio.to_thread(fetch)
        if raw is None:
            raise AssertionError(f"nothing retained on {topic}")
        return json.loads(raw)

    def close(self) -> None:
        for n in self._nodes.values():
            n.close()


@pytest.fixture
async def world(gs_broker: Any) -> AsyncIterator[World]:
    """See the module docstring. The ManualClock starts at T0 and only moves when a test advances it."""
    reg = gs_broker.registry
    keys: dict[str, str] = {}
    types: dict[str, str] = {}
    for node_type, e_m, s_m in STANDARD_8:
        row, key = await asyncio.to_thread(reg.install, node_type, "simulated", e_m, s_m)
        keys[row.id], types[row.id] = key, node_type
    ingest = gs_broker.services.ingest
    deadline = time.monotonic() + 30
    idle_polls = 0
    while idle_polls < 3:  # ready, then idle three polls running: the install events are processed
        if time.monotonic() > deadline:
            raise RuntimeError("telemetry ingest did not become ready")
        idle_polls = idle_polls + 1 if ingest.ready and ingest.idle else 0
        await asyncio.sleep(0.05)
    rec = EventRecorder(f"ws://127.0.0.1:{gs_broker.port}/ws/events")
    await rec.start()
    w = World(gs_broker, keys, types, rec)
    try:
        yield w
    finally:
        await asyncio.to_thread(w.close)
        await rec.stop()
