"""``sim_world`` (Task 12): the whole simulator stack against a real Ground Station and Mosquitto.

- A Ground Station (the Ground Station's own seam-1 harness, loaded from its ``tests/conftest.py``) against
  the fixture broker, with the 8 standard simulated nodes installed at fixed positions (``NODES_8``:
  WQ-02 lies in B3; no WQ or SP node reaches E5).
- A simulator ``Runtime`` on the Ground Station's ManualClock, stepping in the background (200 ms); the
  fixture yields once every node's first sample has reached the Ground Station.
- The simulator control API (``create_sim_app``) served by uvicorn on a free loopback port.

``sim_world.http`` (the simulator API), ``sim_world.gs_http``, ``sim_world.clock``, ``sim_world.runtime``,
``sim_world.gs``; ``async with sim_world.ws() as ws`` (``await ws.collect(type, n, timeout)``: the first n
of that type, fewer on timeout; ``await ws.next_of(type)``); ``await sim_world.gs_task(zone_id)``; ``sim_world.run_for(seconds)``.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import sys
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from helpers import NODES_8

GS_CONFTEST = Path(__file__).resolve().parents[3] / "ground-station" / "tests" / "conftest.py"
SIM_TOKEN = "sim-shared-secret"  # the Ground Station harness's test token


def _gs_harness() -> Any:
    """The Ground Station's seam-1 harness module (GroundStation, _test_settings), loaded under its own name."""
    name = "bcs_gs_seam1_harness"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, GS_CONFTEST)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


class SimServer:
    """The simulator app on a free loopback port in a background thread."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.port = 0
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        config = uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("simulator test server failed to start")
            time.sleep(0.01)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)


class WsReader:
    """The simulator ``/ws`` stream: every message is kept in ``items``."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.items: list[dict[str, Any]] = []
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None
        self._new = asyncio.Event()

    async def __aenter__(self) -> WsReader:  # noqa: PYI034
        from websockets.asyncio.client import connect

        self._ws = await connect(self.url, max_size=None)
        self._task = asyncio.create_task(self._pump())
        await self.collect("sim.status", 1)
        return self

    async def __aexit__(self, *exc: object) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _pump(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self._ws:
                self.items.append(json.loads(raw))
                self._new.set()

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.items if m["type"] == type_]

    async def next_of(self, type_: str, timeout: float = 5.0) -> dict[str, Any]:
        """The next message of ``type_`` received from now on."""
        start = len(self.of(type_))
        deadline = time.monotonic() + timeout
        while len(self.of(type_)) <= start:
            if time.monotonic() >= deadline:
                raise AssertionError(f"no {type_} message within {timeout} s")
            await self._wait(deadline)
        return self.of(type_)[start]

    async def collect(self, type_: str, n: int, timeout: float = 5.0) -> list[dict[str, Any]]:
        """The first ``n`` messages of ``type_`` (fewer if the timeout passes first)."""
        deadline = time.monotonic() + timeout
        while len(self.of(type_)) < n and time.monotonic() < deadline:
            await self._wait(deadline)
        return self.of(type_)[:n]

    async def _wait(self, deadline: float) -> None:
        self._new.clear()
        left = deadline - time.monotonic()
        if left <= 0:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._new.wait(), left)


class SimWorld:
    def __init__(self, gs: Any, runtime: Any, server: SimServer, gs_client: Any) -> None:
        self.gs = gs
        self.runtime = runtime
        self.server = server
        self.gs_client = gs_client
        self.http = httpx.AsyncClient(base_url=server.url, timeout=15)

    @property
    def clock(self) -> Any:
        return self.gs.clock

    @property
    def gs_http(self) -> httpx.AsyncClient:
        return self.gs.http

    def ws(self) -> WsReader:
        return WsReader(f"ws://127.0.0.1:{self.server.port}/ws")

    async def gs_task(self, zone_id: str) -> dict[str, Any]:
        """A manual task on the Ground Station (commands go down to the simulated nodes)."""
        r = await self.gs_http.post("/api/v1/tasks", json={"zone_id": zone_id, "reason": "test"})
        assert r.status_code == 200, r.text
        return r.json()

    def run_for(self, seconds: float, step_s: float = 1.0) -> None:
        """Advance the shared ManualClock in steps, stepping the simulator at each (due samples are made)."""
        done = 0.0
        while done < seconds:
            dt = min(step_s, seconds - done)
            self.clock.advance(dt)
            self.runtime.step(self.clock.now())
            done += dt


async def _wait_ingest_ready(ingest: Any) -> None:
    deadline = time.monotonic() + 30
    idle = 0
    while idle < 3:
        if time.monotonic() > deadline:
            raise RuntimeError("telemetry ingest did not become ready")
        idle = idle + 1 if ingest.ready and ingest.idle else 0
        await asyncio.sleep(0.05)


async def _wait_first_samples(ingest: Any, n: int) -> None:
    """Until every node's first sample (with its boot and config events) has reached the Ground Station,
    so a test starts on a quiet network (the ManualClock does not move by itself)."""
    deadline = time.monotonic() + 30
    while len(await asyncio.to_thread(ingest.latest_all)) < n:
        if time.monotonic() > deadline:
            raise RuntimeError("the simulated nodes did not deliver their first samples")
        await asyncio.sleep(0.05)
    await _wait_ingest_ready(ingest)


@pytest.fixture
async def sim_world(tmp_path: Path, mosquitto: Any) -> AsyncIterator[SimWorld]:
    from bcs_sim.app import create_sim_app
    from bcs_sim.config import load_sim_config, load_sim_settings
    from bcs_sim.gs_client import GsClient
    from bcs_sim.runtime import Runtime

    h = _gs_harness()
    over = {
        "broker_port": mosquitto.port,
        "broker_admin_user": mosquitto.admin_user,
        "broker_admin_password": mosquitto.admin_password,
    }
    (tmp_path / "gs").mkdir()
    async for gs in h._make_gs(tmp_path / "gs", failing=False, settings_over=over):
        reg = gs.services.nodes
        for _nid, node_type, e_m, s_m, _zone in NODES_8:
            await asyncio.to_thread(reg.install, node_type, "simulated", e_m, s_m)
        await _wait_ingest_ready(gs.services.ingest)
        client = GsClient(gs.url, SIM_TOKEN)
        rt = Runtime(
            load_sim_config(), client, gs.clock, seed=42,
            broker_host=mosquitto.host, broker_port=mosquitto.port,
            sessions_dir=tmp_path / "sessions", watch_registry=False,
        )  # fmt: skip
        server: SimServer | None = None
        world: SimWorld | None = None
        try:
            await asyncio.to_thread(rt.start)
            rt.run_background()
            await _wait_first_samples(gs.services.ingest, len(NODES_8))
            app = create_sim_app(load_sim_settings(None, gs_url=gs.url), runtime=rt)
            server = SimServer(app)
            await asyncio.to_thread(server.start)
            world = SimWorld(gs, rt, server, client)
            yield world
        finally:
            if world is not None:
                await world.http.aclose()
            if server is not None:
                await asyncio.to_thread(server.stop)
            await asyncio.to_thread(rt.stop)
            client.close()
