"""LiveGateway: fan height frames out to ``/ws/live`` clients with latest-frame-wins backpressure.

Each client owns one send slot. ``offer`` never awaits: an idle client starts sending at once,
a busy client's slot is overwritten by the newest frame, so a slow client costs the producer and
the other clients nothing. The raster JPEG is encoded once per frame and shared.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import cv2
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.reality.layer import HeightFrame

from .codec import encode_frame

log = logging.getLogger("bcs_gs.live")

JPEG_QUALITY = 80
MAX_RELIEF_M = 40
MAX_FPS_LIMIT = 60.0


class Transport(Protocol):
    async def send_bytes(self, data: bytes) -> None: ...


class _Encoded:
    """One frame's bytes: the JPEG once, the full message once per (raster, height) combination."""

    def __init__(self, frame: HeightFrame) -> None:
        self.frame = frame
        self._jpeg: bytes | None = None
        self._messages: dict[tuple[bool, bool], bytes] = {}

    def jpeg(self) -> bytes:
        if self._jpeg is None:
            bgr = cv2.cvtColor(np.ascontiguousarray(self.frame.raster_rgb), cv2.COLOR_RGB2BGR)
            ok, enc = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                raise RuntimeError("JPEG encode failed")
            self._jpeg = enc.tobytes()
        return self._jpeg

    def message(self, raster: bool, height: bool) -> bytes:
        key = (raster, height)
        if key not in self._messages:
            f = self.frame
            header = {
                "seq": f.seq, "frame_seq": f.frame_seq,
                "captured_at": to_iso(f.captured_at), "processed_at": to_iso(f.processed_at),
                "latency_ms": round((f.processed_at - f.captured_at).total_seconds() * 1000),
                "mode": f.mode, "quality": round(float(f.quality), 3),
                "raster_w": 512, "raster_h": 512, "height_w": 256, "height_h": 256,
                "max_relief_m": MAX_RELIEF_M, "calibration_id": f.calibration_id,
            }  # fmt: skip
            self._messages[key] = encode_frame(
                header, self.jpeg() if raster else None, f.height_u16 if height else None
            )
        return self._messages[key]


@dataclass(eq=False)
class LiveClient:
    transport: Transport
    max_fps: float
    raster: bool = True
    height: bool = True
    slot: _Encoded | None = None
    busy: bool = False
    last_start: float = field(default=-1e9)
    task: asyncio.Task[None] | None = None
    closed: bool = False


class LiveGateway:
    def __init__(self, reality: Any, settings: Any) -> None:
        self._reality = reality
        self._default_fps = float(settings.live_max_fps)
        self._clients: list[LiveClient] = []
        self._current: _Encoded | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    # ---- introspection ---------------------------------------------------------------------
    @property
    def client_count(self) -> int:
        return len(self._clients)

    def client_configs(self) -> list[tuple[float, bool, bool]]:
        return [(c.max_fps, c.raster, c.height) for c in self._clients]

    # ---- clients ---------------------------------------------------------------------------
    async def add_client(self, transport: Transport) -> LiveClient:
        """Register a client; the newest frame (if any) goes out at once (J3 resync)."""
        self.loop = asyncio.get_running_loop()
        client = LiveClient(transport, self._default_fps)
        self._clients.append(client)
        latest = self._reality.latest() if self._reality is not None else None
        if latest is not None:
            self._deliver(client, self._encoded_for(latest))
        return client

    def remove_client(self, client: LiveClient) -> None:
        client.closed = True
        client.slot = None
        if client in self._clients:
            self._clients.remove(client)
        task = client.task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def configure(self, client: LiveClient, msg: Any) -> None:
        """Apply a ``{"type": "config", ...}`` message; anything invalid is ignored whole."""
        if not isinstance(msg, dict) or msg.get("type") != "config":
            log.debug("live: ignoring non-config message")
            return
        fps, raster, height = msg.get("max_fps"), msg.get("raster"), msg.get("height")
        if fps is not None and (
            isinstance(fps, bool) or not isinstance(fps, int | float) or not 0 < fps <= MAX_FPS_LIMIT
        ):
            log.debug("live: ignoring config with bad max_fps")
            return
        if any(v is not None and not isinstance(v, bool) for v in (raster, height)):
            log.debug("live: ignoring config with bad toggle")
            return
        if fps is not None:
            client.max_fps = float(fps)
        if raster is not None:
            client.raster = raster
        if height is not None:
            client.height = height

    # ---- frames ----------------------------------------------------------------------------
    def _encoded_for(self, frame: HeightFrame) -> _Encoded:
        if self._current is None or self._current.frame is not frame:
            self._current = _Encoded(frame)
        return self._current

    def offer(self, frame: HeightFrame) -> None:
        """Hand a new frame to every client; never blocks. Call on the event loop."""
        enc = self._encoded_for(frame)
        for client in list(self._clients):
            self._deliver(client, enc)

    def _deliver(self, client: LiveClient, enc: _Encoded) -> None:
        if client.busy:
            client.slot = enc  # replaces any unsent frame
            return
        client.busy = True
        client.task = asyncio.get_running_loop().create_task(self._drain_client(client, enc))

    async def _drain_client(self, client: LiveClient, enc: _Encoded) -> None:
        try:
            while True:
                wait = client.last_start + 1.0 / client.max_fps - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                    if client.slot is not None:  # a newer frame arrived while throttled
                        enc, client.slot = client.slot, None
                client.last_start = time.monotonic()
                await client.transport.send_bytes(enc.message(client.raster, client.height))
                if client.slot is None:
                    return
                enc, client.slot = client.slot, None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("live client dropped: %s", type(exc).__name__)
            self.remove_client(client)
        finally:
            client.busy = False

    async def drain(self, client: LiveClient | None = None, timeout: float = 5.0) -> None:
        """Wait until one client (or every client) has nothing left to send."""
        deadline = time.monotonic() + timeout
        while any(c.busy for c in ([client] if client else self._clients)):
            if time.monotonic() > deadline:
                raise TimeoutError("live gateway did not drain")
            await asyncio.sleep(0.005)

    # ---- lifecycle -------------------------------------------------------------------------
    async def run(self) -> None:
        """Pump: reality frames -> ``offer``. Ends when the reality layer stops."""
        self.loop = asyncio.get_running_loop()
        async for frame in self._reality.subscribe():
            self.offer(frame)

    async def close(self) -> None:
        for client in list(self._clients):
            self.remove_client(client)
        await asyncio.sleep(0)
