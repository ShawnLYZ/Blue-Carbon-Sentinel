"""Shared fixtures. ``gs`` is the seam-1 harness of addendum P1: the real app on a free loopback
port in a background thread, with a temporary data directory, a ManualClock, a FakeCloudTarget and
no camera. The ``mosquitto`` broker fixtures live in the repository-root ``conftest.py``.
It never reads the real ``.env`` and never reaches the hosted Supabase project."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from bcs_gs.api.app import Overrides, create_app
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.config import Settings, load_settings
from bcs_gs.core.events import EventBus
from bcs_gs.status.probes import FakeProbes
from bcs_gs.store.cloud import FakeCloudTarget
from websockets.asyncio.client import connect

REPO_ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)


class EventsClient:
    """``/ws/events`` collector with ``next()`` and ``wait_for(type, pred=None, timeout=5)``."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: Any = None
        self.received: list[dict[str, Any]] = []

    async def __aenter__(self) -> EventsClient:  # noqa: PYI034
        self._ws = await connect(self._url)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._ws.close()

    async def next(self, timeout: float = 5) -> dict[str, Any]:
        msg = json.loads(await asyncio.wait_for(self._ws.recv(), timeout))
        self.received.append(msg)
        return msg

    async def wait_for(self, type: str, pred: Any = None, timeout: float = 5) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            msg = await self.next(max(0.01, deadline - time.monotonic()))
            if msg["type"] == type and (pred is None or pred(msg)):
                return msg

    @property
    def close_code(self) -> int | None:
        return None if self._ws is None else (self._ws.close_code)


class GroundStation:
    def __init__(
        self,
        settings: Settings,
        cloud: FakeCloudTarget,
        clock: ManualClock,
        data_dir: Path,
        illustrator: Any = None,
    ) -> None:
        self.settings = settings
        self.cloud = cloud
        self.clock = clock
        self.data_dir = data_dir
        self.app = create_app(
            settings,
            overrides=Overrides(
                clock=clock, cloud=cloud, camera_enabled=False, test_mode=True, probes=FakeProbes(),
                illustrator=illustrator,
            ),
        )
        self.services: Any = None
        self.port = 0
        self.http: httpx.AsyncClient
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def events(self) -> EventsClient:
        return EventsClient(f"ws://127.0.0.1:{self.port}/ws/events")

    def start(self) -> None:
        config = uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Ground Station test server failed to start")
            time.sleep(0.01)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        self.services = self.app.state.services

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)


def _test_settings(tmp_path: Path, **over: Any) -> Settings:
    return load_settings(
        REPO_ROOT,
        env_file=None,
        data_dir=tmp_path,
        mapbox_public_token="pk.test-mapbox-public-token",
        supabase_url="https://example-project.supabase.co",
        supabase_service_role_key="sb-service-role-secret",
        supabase_anon_key="sb-anon-secret",
        nvidia_api_key="nvapi-secret-value",
        gemini_api_key_1="gem-secret-one",
        gs_mqtt_password="gs-mqtt-secret",
        supabase_access_token="sbp-access-secret",
        sim_shared_token="sim-shared-secret",
        camera_token="cam-token-secret",
        **{"auto_commission": False, **over},  # tests start with an empty registry unless asked
    )


async def _make_gs(
    tmp_path: Path,
    *,
    failing: bool,
    settings_over: dict[str, Any] | None = None,
    illustrator: Any = None,
) -> AsyncIterator[GroundStation]:
    settings = _test_settings(tmp_path, **(settings_over or {}))
    gs = GroundStation(settings, FakeCloudTarget(failing=failing), ManualClock(T0), tmp_path, illustrator)
    await asyncio.to_thread(gs.start)
    gs.http = httpx.AsyncClient(base_url=gs.url, timeout=10)
    try:
        yield gs
    finally:
        await gs.http.aclose()
        await asyncio.to_thread(gs.stop)


@pytest.fixture
async def gs(tmp_path: Path) -> AsyncIterator[GroundStation]:
    async for g in _make_gs(tmp_path, failing=False):
        yield g


class GsBroker:
    """The ``gs`` harness configured against a real Mosquitto: ``mqtt`` is the broker handle (host, port,
    admin credentials), ``registry`` the NodeRegistry (empty at start), ``repo`` the Ground Station's
    repository and ``http`` its client. Everything else is forwarded to the GroundStation."""

    def __init__(self, gs: GroundStation, mqtt: Any) -> None:
        self._gs = gs
        self.mqtt = mqtt

    @property
    def registry(self) -> Any:
        return self._gs.services.nodes

    @property
    def repo(self) -> Any:
        return self._gs.services.repo

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gs, name)

    async def rows(self, table: str) -> list[dict[str, Any]]:
        """Every row of a local table (decoded)."""
        return await asyncio.to_thread(self.repo.query, f'SELECT * FROM "{table}"', (), table=table)

    async def set_latest_class_map(self, classes: Any) -> str:
        """Store ``classes`` (512 x 512 class codes) as the class map of a new evidence-grade capture,
        which becomes the latest one. Returns the capture ID."""
        from bcs_gs.capture.artefacts import BUCKET, CONTENT_TYPES, indexed_png, media_keys
        from bcs_protocol.timefmt import from_iso

        svc = self._gs.services
        cap = await svc.capture.seed_capture({}, True, None, "manual")
        key = media_keys(cap.id, from_iso(cap.taken_at))["classes"]

        def store() -> None:
            svc.media.put(BUCKET, key, indexed_png(classes), CONTENT_TYPES["classes"], cloud=False)
            row = svc.repo.get("captures", {"id": cap.id})
            svc.repo.upsert("captures", {**row, "media": {**(row["media"] or {}), "classes": key}}, sync=False)

        await asyncio.to_thread(store)
        return cap.id


@pytest.fixture
def gs_illustrator() -> Any:
    """The ImageIllustrator injected through ``Overrides`` into ``gs_broker`` (M5): None means test mode's
    DisabledIllustrator. A test module overrides this fixture to inject a fake."""
    return None


@pytest.fixture
async def gs_broker(tmp_path: Path, mosquitto: Any, gs_illustrator: Any) -> AsyncIterator[GsBroker]:
    """The Ground Station against a real broker with an EMPTY node registry. Reused by M3 seam-1 tests."""
    over = {
        "broker_port": mosquitto.port,
        "broker_admin_user": mosquitto.admin_user,
        "broker_admin_password": mosquitto.admin_password,
    }
    (tmp_path / "gs").mkdir()
    async for g in _make_gs(tmp_path / "gs", failing=False, settings_over=over, illustrator=gs_illustrator):
        yield GsBroker(g, mosquitto)


@pytest.fixture
async def gs_broker_fresh(tmp_path: Path, mosquitto: Any) -> AsyncIterator[GsBroker]:
    """Like ``gs_broker`` but with auto-commissioning on and no capture: the Ground Station installs the
    8 nodes of the low-confidence fallback layout at start. Yields once that first run exists."""
    over = {
        "broker_port": mosquitto.port,
        "broker_admin_user": mosquitto.admin_user,
        "broker_admin_password": mosquitto.admin_password,
        "auto_commission": True,
    }
    (tmp_path / "gs").mkdir()
    async for g in _make_gs(tmp_path / "gs", failing=False, settings_over=over):
        deadline = time.monotonic() + 60
        while (await g.http.get("/api/v1/commissioning")).status_code != 200:
            if time.monotonic() > deadline:
                raise RuntimeError("auto-commissioning did not finish")
            await asyncio.sleep(0.05)
        yield GsBroker(g, mosquitto)


@pytest.fixture
async def gs_failing_cloud(tmp_path: Path) -> AsyncIterator[GroundStation]:
    async for g in _make_gs(tmp_path, failing=True):
        yield g


class _FakeLiveTransport:
    """A controllable client transport for the LiveGateway: it records what the gateway sends and
    can hold a send open (``block``) or refuse it (``fail``). It carries no imagery of its own."""

    def __init__(self, gateway: Any) -> None:
        self._gw = gateway
        self._open = asyncio.Event()
        self._open.set()
        self._failing = False
        self._frames: list[Any] = []
        self.handle: Any = None

    def block(self) -> None:
        self._open.clear()

    def unblock(self) -> None:
        self._open.set()

    def fail(self) -> None:
        self._failing = True

    async def send_bytes(self, data: bytes) -> None:
        await self._open.wait()
        if self._failing:
            raise ConnectionError("client went away")
        from types import SimpleNamespace

        from bcs_gs.live.codec import decode_frame

        header, jpeg, height = decode_frame(data)
        self._frames.append(SimpleNamespace(header=header, jpeg=jpeg, height=height))

    async def received(self) -> list[Any]:
        """Everything delivered so far, once the gateway has nothing left to send."""
        await self._gw.drain(self.handle, timeout=5)
        out, self._frames = self._frames, []
        return out


class LiveGatewayWorld:
    """A LiveGateway over a real RealityLayer (no source attached, so no frames flow by themselves)."""

    def __init__(self, tmp_path: Path) -> None:
        from bcs_gs.live.gateway import LiveGateway
        from bcs_gs.reality import RealityLayer

        settings = _test_settings(tmp_path)
        self.reality = RealityLayer(None, None, EventBus(), settings)
        self.gateway = LiveGateway(self.reality, settings)

    async def add_client(self) -> _FakeLiveTransport:
        t = _FakeLiveTransport(self.gateway)
        t.handle = await self.gateway.add_client(t)
        return t


@pytest.fixture
async def live_gateway_world(tmp_path: Path) -> AsyncIterator[tuple[Any, _FakeLiveTransport]]:
    world = LiveGatewayWorld(tmp_path)
    gw = world.gateway
    gw.world_add_client = world.add_client  # type: ignore[attr-defined]
    client = await world.add_client()
    try:
        yield gw, client
    finally:
        await gw.close()


@pytest.fixture
async def start_gs_with(tmp_path: Path) -> AsyncIterator[Any]:
    """``await start_gs_with(cloud=..., data_dir=...)``: a Ground Station (no broker, no camera) on
    ``data_dir`` against the given cloud target, e.g. a fresh machine against a cloud with history.
    Every one started is stopped at teardown."""
    started: list[GroundStation] = []

    async def start(*, cloud: FakeCloudTarget, data_dir: Path, **settings_over: Any) -> GroundStation:
        gs = GroundStation(_test_settings(data_dir, **settings_over), cloud, ManualClock(T0), data_dir)
        await asyncio.to_thread(gs.start)
        gs.http = httpx.AsyncClient(base_url=gs.url, timeout=10)
        started.append(gs)
        return gs

    yield start
    for gs in started:
        await gs.http.aclose()
        await asyncio.to_thread(gs.stop)
