"""Sentinel Simulator control app (addendum K): the K1 routes (``api.py``), ``/ws`` (K2) and CORS (K3).

``/ws`` (JSON text) carries:
- ``inspector.packet``: every message a node sends ("up") or receives ("down"), validated (K2);
- ``nodes.state``: the K1 SimNode list, 4 times a second;
- ``sim.status``: runtime, broker, recording, replay and scenario-run state, on connect and on every change.

Each client has one bounded queue of 500 messages. On overflow the oldest message is dropped, and the next
message the client receives carries ``"dropped": n`` (how many were lost since the previous one).

Inspector listeners run on whatever thread published (the runtime's step thread, or paho's network thread
for "down" packets). They never take ``Runtime.lock`` (paho's thread is joined under that lock when a node
is dropped or closed); they hand the message to the event loop with ``call_soon_threadsafe``. The
``nodes.state`` snapshot is built from the loop (off-loop in a worker thread, under the lock).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from bcs_sim import __version__
from bcs_sim.api import SimContext, node_views, router, sim_status
from bcs_sim.config import SimSettings
from bcs_sim.errors import install_error_handlers
from bcs_sim.inspector import InspectorPacket

log = logging.getLogger("bcs_sim.ws")

QUEUE_SIZE = 500
STATE_PERIOD_S = 0.25  # nodes.state at 4 Hz


class WsClientQueue:
    """One client's bounded outgoing queue (loop thread only). Overflow drops the oldest message."""

    def __init__(self, maxlen: int = QUEUE_SIZE) -> None:
        self.maxlen = maxlen
        self._q: deque[dict[str, Any]] = deque()
        self._ready = asyncio.Event()
        self.dropped = 0

    def push(self, msg: dict[str, Any]) -> None:
        if len(self._q) >= self.maxlen:
            self._q.popleft()
            self.dropped += 1
        self._q.append(msg)
        self._ready.set()

    async def get(self) -> dict[str, Any]:
        while not self._q:
            self._ready.clear()
            await self._ready.wait()
        msg = self._q.popleft()
        if self.dropped:
            msg = {**msg, "dropped": self.dropped}
            self.dropped = 0
        return msg


class WsHub:
    """Fans inspector packets, node state and status out to every ``/ws`` client."""

    def __init__(
        self, ctx: SimContext, period_s: float = STATE_PERIOD_S, queue_size: int = QUEUE_SIZE
    ) -> None:
        self.ctx = ctx
        self.period_s = period_s
        self.queue_size = queue_size
        self.clients: set[WsClientQueue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._tapped: Any = None  # the runtime whose inspector we listen to
        self._last_status: dict[str, Any] | None = None

    # -- lifecycle ------------------------------------------------------------------------------------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._ticker(), name="bcs-sim-ws-ticker")

    async def stop(self) -> None:
        self._untap()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self.loop = None

    def _tap(self) -> None:
        rt = self.ctx.runtime
        if rt is self._tapped:
            return
        self._untap()
        if rt is not None:
            rt.inspector.add_listener(self._on_packet)
            self._tapped = rt

    def _untap(self) -> None:
        if self._tapped is not None:
            self._tapped.inspector.remove_listener(self._on_packet)
            self._tapped = None

    # -- fan-out --------------------------------------------------------------------------------------
    def _on_packet(self, pkt: InspectorPacket) -> None:
        """Any thread. Never takes ``Runtime.lock``."""
        loop = self.loop
        if loop is None or not self.clients:
            return
        with contextlib.suppress(RuntimeError):  # the loop is closing
            loop.call_soon_threadsafe(self.broadcast, pkt.message())

    def broadcast(self, msg: dict[str, Any]) -> None:
        """Loop thread only."""
        for c in list(self.clients):
            c.push(msg)

    def add(self) -> WsClientQueue:
        q = WsClientQueue(self.queue_size)
        self.clients.add(q)
        return q

    def remove(self, q: WsClientQueue) -> None:
        self.clients.discard(q)

    def snapshot(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """(nodes.state data, sim.status data); blocking, takes the runtime lock."""
        rt = self.ctx.runtime
        nodes: list[dict[str, Any]] = []
        if rt is not None and rt.started:
            with rt.lock:
                nodes = node_views(rt)
        return nodes, sim_status(self.ctx)

    async def _ticker(self) -> None:
        while True:
            try:
                self._tap()
                if self.clients:
                    nodes, status = await asyncio.to_thread(self.snapshot)
                    self.broadcast({"type": "nodes.state", "data": nodes})
                    if status != self._last_status:
                        self._last_status = status
                        self.broadcast({"type": "sim.status", "data": status})
            except Exception:
                log.exception("/ws ticker failed")
            await asyncio.sleep(self.period_s)


def create_sim_app(
    settings: SimSettings, *, runtime: Any = None, hub_factory: Callable[[SimContext], WsHub] = WsHub
) -> FastAPI:
    """``runtime``: a started Runtime to serve (tests); else ``app.state.runtime_supervisor.runtime``
    (``bcs-sim run`` sets the supervisor after building the app)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await app.state.hub.start()
        try:
            yield
        finally:
            await app.state.hub.stop()

    app = FastAPI(title="Blue Carbon Sentinel Simulator", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.runtime = runtime
    app.state.runtime_supervisor = None
    ctx = SimContext(settings, app.state)
    app.state.sim = ctx
    app.state.hub = hub_factory(ctx)
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        hub: WsHub = app.state.hub
        await socket.accept()
        nodes, status = await asyncio.to_thread(hub.snapshot)
        await socket.send_json({"type": "sim.status", "data": status})
        q = hub.add()
        q.push({"type": "nodes.state", "data": nodes})

        async def sender() -> None:
            while True:
                await socket.send_json(await q.get())

        send_task = asyncio.create_task(sender())
        try:
            while True:
                await socket.receive_text()  # clients send nothing; this notices the disconnect
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.remove(q)
            send_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await send_task

    return app
