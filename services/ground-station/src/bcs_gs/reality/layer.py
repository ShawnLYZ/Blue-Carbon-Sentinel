"""RealityLayer: site rasters -> live 256 x 256 u16 height frames (addendum N10, feeds J1 /ws/live).

Threads: an asyncio intake task drains ``imagery.subscribe()`` into a one-slot hand-off; one
daemon worker takes only the newest raster (latest wins, stale ones are dropped) and runs depth
inference, smoothing and the fallback off the event loop. Results go back to asyncio subscribers
through ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import cv2
import numpy as np

from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus

from .depth import INPUT_SIZE
from .fallback import fallback_heights
from .quality import (
    FALLBACK_BELOW,
    dynamic_range01,
    ema,
    normalise_robust,
    quality_score,
    stability,
    to_height_u16,
)

log = logging.getLogger("bcs_gs.reality")

Mode = Literal["depth", "fallback"]
FPS_WINDOW_S = 2.0
RESET_GAP_S = 3.0  # a capture gap this long (camera offline, addendum L) starts a fresh surface
INTAKE_RETRY_S = 1.0


@dataclass(frozen=True)
class HeightFrame:
    seq: int  # RealityLayer's processed-frame counter
    frame_seq: int  # camera frame seq of the source raster
    captured_at: datetime  # UTC, from the camera frame
    processed_at: datetime  # UTC
    mode: Mode
    quality: float
    height_u16: np.ndarray  # 256 x 256 uint16, row 0 = north edge
    raster_rgb: np.ndarray  # 512 x 512 x 3 uint8, north-up
    calibration_id: str | None
    process_ms: float  # worker wall time for this frame


class RealityLayer:
    def __init__(self, imagery: Any, depth: Any, bus: EventBus, settings: Settings | None) -> None:
        self._imagery = imagery
        self._depth = depth
        self._bus = bus
        self._cfg = settings.thresholds if settings is not None else None
        self._cond = threading.Condition()
        self._pending: Any = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._intake: asyncio.Task[None] | None = None
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Any]]] = []
        self._on_mode: list[Callable[[Mode], Any]] = []
        self._latest: HeightFrame | None = None
        self._mode: Mode | None = None
        self._seq = 0
        self._ema: np.ndarray | None = None
        self._prev_norm: np.ndarray | None = None
        self._last_cal: str | None = None
        self._last_at: datetime | None = None
        self._times: deque[float] = deque()
        self.dropped = 0  # rasters replaced before the worker took them

    # ---- registration / state --------------------------------------------------------------
    def on_mode_change(self, cb: Callable[[Mode], Any]) -> None:
        """``cb(mode)`` runs on the event loop (or inline when there is none) on every mode change."""
        self._on_mode.append(cb)

    def latest(self) -> HeightFrame | None:
        return self._latest

    @property
    def mode(self) -> Mode | None:
        return self._mode

    @property
    def provider(self) -> str | None:
        return getattr(self._depth, "provider", None) if getattr(self._depth, "available", False) else None

    @property
    def fps(self) -> float:
        with self._cond:
            self._prune(time.monotonic())
            return round(len(self._times) / FPS_WINDOW_S, 2)

    def _prune(self, now: float) -> None:
        while self._times and now - self._times[0] > FPS_WINDOW_S:
            self._times.popleft()

    # ---- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        if self._worker is not None:
            return
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._stop.clear()
        self.reset()
        self._worker = threading.Thread(target=self._run, name="reality-worker", daemon=True)
        self._worker.start()
        if self._loop is not None and self._imagery is not None:
            self._intake = self._loop.create_task(self._consume(), name="reality-intake")

    def stop(self) -> None:
        """Safe from any thread: cancels intake, stops the worker and ends subscriber iterators."""
        self._stop.set()
        task, loop = self._intake, self._loop
        if task is not None and loop is not None and not loop.is_closed():
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(task.cancel)
        self._intake = None
        with self._cond:
            self._cond.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=5)
            self._worker = None
        for sub_loop, q in list(self._subs):
            with contextlib.suppress(RuntimeError):
                sub_loop.call_soon_threadsafe(_offer, q, None)

    async def _consume(self) -> None:
        while not self._stop.is_set():
            try:
                async for raster in self._imagery.subscribe():
                    self.submit(raster)
                return  # the source ended (camera stopped)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("reality intake failed: %s", type(exc).__name__)
                await asyncio.sleep(INTAKE_RETRY_S)

    # ---- hand-off and worker ---------------------------------------------------------------
    def submit(self, raster: Any) -> None:
        """Offer a raster to the worker; a raster still waiting is replaced (latest wins)."""
        with self._cond:
            if self._pending is not None:
                self.dropped += 1
            self._pending = raster
            self._cond.notify()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                while self._pending is None and not self._stop.is_set():
                    self._cond.wait(0.5)
                raster, self._pending = self._pending, None
            if raster is None:
                continue
            try:
                frame = self.process(raster)
            except Exception:
                log.exception("reality frame %s failed", getattr(raster, "seq", "?"))
                continue
            self._publish(frame)

    def reset(self) -> None:
        """Forget the smoothing state: the next frame starts a fresh surface (no EMA, stability 0)."""
        self._ema = self._prev_norm = None
        self._last_cal = self._last_at = None

    def _maybe_reset(self, raster: Any) -> None:
        """A new calibration warps rasters with a different homography, and a long capture gap
        means the scene may have changed: neither may blend into, or be compared with, the old
        surface. A depth/fallback switch alone deliberately keeps the EMA."""
        cal, at = raster.calibration_id, raster.captured_at
        if self._last_at is not None:
            gap_s = abs((at - self._last_at).total_seconds())
            if cal != self._last_cal or gap_s > RESET_GAP_S:
                log.info(
                    "reality smoothing reset (calibration %s -> %s, gap %.1f s)", self._last_cal, cal, gap_s
                )
                self._ema = self._prev_norm = None
        self._last_cal, self._last_at = cal, at

    def process(self, raster: Any) -> HeightFrame:
        """One raster -> one HeightFrame. Runs on the worker thread (single-threaded state)."""
        t0 = time.perf_counter()
        self._maybe_reset(raster)
        rgb = np.ascontiguousarray(raster.image[..., :3], np.uint8)
        quality, h01 = 0.0, None
        if getattr(self._depth, "available", False):
            d = None
            try:
                d = self._depth.infer(rgb)
                if not np.isfinite(d).all():
                    d = None
            except Exception as exc:  # noqa: BLE001
                log.warning("depth inference failed: %s", type(exc).__name__)
            if d is not None:
                norm = normalise_robust(d)
                quality = quality_score(dynamic_range01(d), stability(self._prev_norm, norm), True)
                self._prev_norm = norm
                if quality >= FALLBACK_BELOW:
                    h01 = norm
        mode: Mode = "depth" if h01 is not None else "fallback"
        if h01 is None:  # fallback is 256 px; bring it to the depth grid so the EMA spans modes
            fb = fallback_heights(rgb, self._cfg)
            h01 = cv2.resize(fb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
        self._ema = ema(self._ema, h01)
        height = to_height_u16(self._ema)
        self._seq += 1
        return HeightFrame(
            seq=self._seq,
            frame_seq=int(raster.seq),
            captured_at=raster.captured_at,
            processed_at=self._bus.clock.now(),
            mode=mode,
            quality=round(float(quality), 4),
            height_u16=height,
            raster_rgb=rgb,
            calibration_id=raster.calibration_id,
            process_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

    def _publish(self, frame: HeightFrame) -> None:
        now = time.monotonic()
        with self._cond:
            self._latest = frame
            self._times.append(now)
            self._prune(now)
        changed = frame.mode != self._mode
        self._mode = frame.mode
        for loop, q in list(self._subs):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_offer, q, frame)
        if changed:
            log.info("reality mode -> %s (quality %.2f)", frame.mode, frame.quality)
            for cb in self._on_mode:
                self._call(cb, frame.mode)

    def _call(self, fn: Callable[..., Any], *args: Any) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(fn, *args)
            return
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            log.warning("reality mode callback failed: %s", type(exc).__name__)

    # ---- subscribers -----------------------------------------------------------------------
    async def subscribe(self) -> AsyncIterator[HeightFrame]:
        """Height frames as they are produced; a slow subscriber sees only the newest one."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)
        entry = (loop, q)
        self._subs.append(entry)
        try:
            while True:
                frame = await q.get()
                if frame is None:
                    return
                yield frame
        finally:
            if entry in self._subs:
                self._subs.remove(entry)


def _offer(q: asyncio.Queue[Any], item: HeightFrame | None) -> None:
    """Latest wins: replace an unconsumed frame."""
    if q.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()
    q.put_nowait(item)
