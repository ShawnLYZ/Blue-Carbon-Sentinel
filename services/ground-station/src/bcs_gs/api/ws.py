"""``/ws/events`` (addendum J2): hello, then every EventBus event as a JSON envelope."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from bcs_protocol.timefmt import to_iso
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from bcs_gs.api import models as m
from bcs_gs.core.ids import uuid7

log = logging.getLogger("bcs_gs.ws")
router = APIRouter()

QUEUE_MAX = 1000
CLOSE_TRY_AGAIN_LATER = 1013


@router.websocket("/ws/events")
async def events_socket(ws: WebSocket) -> None:
    svc = ws.app.state.services
    await ws.accept()
    sub = svc.bus.subscribe(QUEUE_MAX)  # subscribe first so nothing after hello is missed
    pump: asyncio.Task | None = None
    reader: asyncio.Task | None = None
    try:
        hello = m.EventEnvelope(
            type="hello",
            id=uuid7(),
            at=to_iso(svc.clock.now()),
            data=m.HelloData(
                server_time=to_iso(svc.clock.now()), version=svc.version,
                demo_time_scale=svc.settings.demo_time_scale == "on",
            ).model_dump(),
        )  # fmt: skip
        await ws.send_json(hello.model_dump())

        async def read() -> None:
            with contextlib.suppress(WebSocketDisconnect):
                while True:
                    await ws.receive_text()  # client messages are ignored; this notices a disconnect

        async def send() -> None:
            async for event in sub:
                await ws.send_json(event.envelope())

        reader, pump = asyncio.create_task(read()), asyncio.create_task(send())
        await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
        if sub.overflowed:
            log.warning("events client too slow; closing with 1013")
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close(code=CLOSE_TRY_AGAIN_LATER)
    except WebSocketDisconnect:
        pass
    finally:
        sub.close()
        for t in (reader, pump):
            if t is not None and not t.done():
                t.cancel()
        for t in (reader, pump):
            if t is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t


class _SocketTransport:
    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)


@router.websocket("/ws/live")
async def live_socket(ws: WebSocket) -> None:
    """Binary frames (addendum J1). Text messages from the client are config; bad ones are ignored."""
    gateway = ws.app.state.services.live
    await ws.accept()
    client = await gateway.add_client(_SocketTransport(ws))
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            text = msg.get("text")
            if text is None:
                continue
            try:
                parsed = json.loads(text)
            except ValueError:
                log.debug("live: ignoring unparseable client message")
                continue
            gateway.configure(client, parsed)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        gateway.remove_client(client)
