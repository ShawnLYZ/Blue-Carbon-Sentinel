"""CameraLink: owns the single ESP32-CAM stream, offline detection and reconnect (addendum L3-L5).

Threads: one daemon reader (stream, decode) and one daemon monitor (offline tick, ``/status`` poll).
Everything crossing to asyncio goes through ``loop.call_soon_threadsafe``. The token is sent only
in the ``Authorization`` header and is never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import cv2
import httpx
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.core.clock import Clock
from bcs_gs.core.config import Settings
from bcs_gs.core.events import EventBus

from .discovery import resolve_camera
from .mjpeg import MjpegParser

log = logging.getLogger("bcs_gs.camera")

OFFLINE_AFTER_S = 3.0  # no frame for this long: offline (product spec s6)
POLL_FAIL_OFFLINE_S = 1.5  # a failed /status poll with no frame for this long also means offline
POLL_PERIOD_S = 2.0
TICK_PERIOD_S = 0.25
RING_SIZE = 5
FPS_WINDOW_S = 2.0
DEFAULT_BOUNDARY = b"bcsframe"
UI_SETTINGS_KEY = "ui_settings"
LOCK_KEY = "camera_lock"


def backoff_delays() -> Iterator[float]:
    """Reconnect delays: 0.5, 1, 2, 4, then 5 s forever."""
    yield from (0.5, 1, 2, 4)
    while True:
        yield 5


@dataclass(frozen=True)
class Frame:
    image_bgr: np.ndarray
    seq: int
    captured_at: datetime


@dataclass(frozen=True)
class Transition:
    kind: Literal["online", "offline"]
    since: datetime
    recovered: bool = True  # False only for the first-ever online (no offline was announced before it)


class CameraState:
    """Pure offline/online state machine. Starts offline; ``since`` is the last frame time, or the
    start time when no frame has ever arrived (so the banner always has a time)."""

    def __init__(self, start: datetime | None = None, offline_after_s: float = OFFLINE_AFTER_S) -> None:
        self.start = start
        self.online = False
        self.last_frame: datetime | None = None
        self._offline_after_s = offline_after_s
        self._offline_announced = False

    @property
    def since(self) -> datetime | None:
        return self.last_frame or self.start

    def on_frame(self, now: datetime) -> list[Transition]:
        self.last_frame = now
        if self.online:
            return []
        self.online = True
        recovered, self._offline_announced = self._offline_announced, False
        return [Transition("online", since=now, recovered=recovered)]

    def _check(self, now: datetime, limit_s: float) -> list[Transition]:
        if self.online and self.last_frame is not None and (now - self.last_frame).total_seconds() >= limit_s:
            self.online = False
            self._offline_announced = True
            return [Transition("offline", since=self.last_frame)]
        if (
            not self.online
            and not self._offline_announced
            and self.last_frame is None
            and self.start is not None
            and (now - self.start).total_seconds() >= limit_s
        ):  # down since boot: announce once
            self._offline_announced = True
            return [Transition("offline", since=self.start)]
        return []

    def tick(self, now: datetime) -> list[Transition]:
        return self._check(now, self._offline_after_s)

    def on_poll_failure(self, now: datetime) -> list[Transition]:
        return self._check(now, min(POLL_FAIL_OFFLINE_S, self._offline_after_s))


class CameraLink:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        bus: EventBus,
        *,
        repo: Any = None,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str, str | None], str | None] = resolve_camera,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._bus = bus
        self._repo = repo
        self._transport = transport
        self._resolver = resolver
        self._lock = threading.RLock()
        self._state = CameraState(start=clock.now())
        self._ring: deque[Frame] = deque(maxlen=RING_SIZE)
        self._latest: Frame | None = None
        self._frame_times: deque[datetime] = deque()
        self._seq = 0
        self._ip: str | None = None
        self._device: dict[str, Any] | None = None
        self._device_current = False  # _device was reported on the present connection
        self._mem_desired = m.CameraSettings()
        self._mem_locked = False
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Any]]] = []
        self._on_offline: list[Callable[[m.CameraStatus], None]] = []
        self._on_online: list[Callable[[m.CameraStatus], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._reconnect = threading.Event()
        self._resp: httpx.Response | None = None
        self._threads: list[threading.Thread] = []

    # ---- registration ---------------------------------------------------------------------
    def on_offline(self, cb: Callable[[m.CameraStatus], None]) -> None:
        self._on_offline.append(cb)

    def on_online(self, cb: Callable[[m.CameraStatus], None]) -> None:
        self._on_online.append(cb)

    # ---- lifecycle ------------------------------------------------------------------------
    def start(self) -> None:
        if self._threads:
            return
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        with self._lock:
            if self._state.last_frame is None:
                self._state.start = self._clock.now()
        self._stop.clear()
        for name, target in (("camera-stream", self._reader), ("camera-monitor", self._monitor)):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._close_resp()
        for t in self._threads:
            t.join(timeout=5)
        self._threads = []
        for loop, q in list(self._subs):
            try:
                loop.call_soon_threadsafe(_offer, q, None)
            except RuntimeError:
                pass

    def reconnect(self) -> None:
        self._reconnect.set()
        self._close_resp()

    def _close_resp(self) -> None:
        resp = self._resp
        if resp is not None:
            with contextlib.suppress(Exception):
                resp.close()

    # ---- frames ---------------------------------------------------------------------------
    def latest(self) -> Frame | None:
        return self._latest

    def recent(self, n: int) -> list[Frame]:
        ring = tuple(self._ring)
        return list(ring[-n:]) if n > 0 else []

    async def subscribe(self) -> AsyncIterator[Frame]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=2)
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

    def ingest(self, jpeg: bytes, seq: int | None = None) -> Frame | None:
        """Decode one JPEG and publish it. Returns ``None`` for undecodable bytes."""
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        now = self._clock.now()
        with self._lock:
            self._seq = seq if seq is not None else self._seq + 1
            frame = Frame(image, self._seq, now)
            self._latest = frame
            self._ring.append(frame)
            self._frame_times.append(now)
            self._prune_frame_times(now)
            transitions = self._state.on_frame(now)
            status = self._status_locked(now) if transitions else None
        for loop, q in list(self._subs):
            try:
                loop.call_soon_threadsafe(_offer, q, frame)
            except RuntimeError:  # loop closed
                pass
        if status is not None:
            self._emit(transitions, status)
        return frame

    # ---- state / status -------------------------------------------------------------------
    def tick(self) -> None:
        now = self._clock.now()
        with self._lock:
            transitions = self._state.tick(now)
            status = self._status_locked(now) if transitions else None
        if status is not None:
            self._emit(transitions, status)

    def _poll_failed(self) -> None:
        now = self._clock.now()
        with self._lock:
            transitions = self._state.on_poll_failure(now)
            status = self._status_locked(now) if transitions else None
        if status is not None:
            self._emit(transitions, status)

    def status(self) -> m.CameraStatus:
        self.tick()
        with self._lock:
            return self._status_locked(self._clock.now())

    def _status_locked(self, now: datetime) -> m.CameraStatus:
        st = self._state
        self._prune_frame_times(now)
        since = st.since
        return m.CameraStatus(
            online=st.online,
            since=to_iso(since or now),
            host=self._settings.camera_host,
            resolved_ip=self._ip,
            last_frame_at=to_iso(st.last_frame) if st.last_frame else None,
            fps_in=round(len(self._frame_times) / FPS_WINDOW_S, 2) if st.online else 0.0,
            locked=self.exposure_locked,
            desired=self.desired,
            device=self._device,
        )

    def _prune_frame_times(self, now: datetime) -> None:
        while self._frame_times and (now - self._frame_times[0]).total_seconds() > FPS_WINDOW_S:
            self._frame_times.popleft()

    def _emit(self, transitions: list[Transition], status: m.CameraStatus) -> None:
        for tr in transitions:
            self._call(self._bus.publish, "camera.status", status.model_dump(mode="json"))
            if tr.kind == "online" and not tr.recovered:
                continue  # first-ever online is not a recovery: no "camera back" alert
            for cb in self._on_online if tr.kind == "online" else self._on_offline:
                self._call(cb, status)

    def _call(self, fn: Callable[..., Any], *args: Any) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(fn, *args)
            except RuntimeError:
                pass
            return
        fn(*args)

    # ---- desired settings and lock (persisted in the settings table, L5) -------------------
    @property
    def desired(self) -> m.CameraSettings:
        if self._repo is not None:
            row = self._repo.get("settings", {"key": UI_SETTINGS_KEY})
            if row:
                return m.Settings.model_validate(row["value"]).camera_desired
        return self._mem_desired

    @property
    def locked(self) -> bool:
        if self._repo is not None:
            row = self._repo.get("settings", {"key": LOCK_KEY})
            if row:
                return bool(row["value"].get("locked"))
        return self._mem_locked

    @property
    def exposure_locked(self) -> bool:
        """Lock state for evidence grading and ``CameraStatus.locked`` (I3 has one boolean, so it
        reports the effective value): the desired lock AND the camera's own ``ae_locked`` and
        ``awb_locked`` from its last report on this connection. Never reported means not locked."""
        if not self.locked:
            return False
        dev = self._device
        if not self._device_current or not isinstance(dev, dict):
            return False
        return dev.get("ae_locked") is True and dev.get("awb_locked") is True

    def _persist(self, key: str, value: dict[str, Any]) -> None:
        if self._repo is not None:
            self._repo.upsert(
                "settings", {"key": key, "value": value, "updated_at": to_iso(self._clock.now())}, sync=False
            )

    def reset_desired(self) -> None:
        """Forget the in-memory desired settings and lock (test reset; the persisted rows are gone)."""
        self._mem_desired = m.CameraSettings()
        self._mem_locked = False

    def apply(self, settings: m.CameraSettings) -> None:
        """Remember ``settings`` as desired and push them to the camera (best effort)."""
        self._mem_desired = settings
        if self._repo is not None:
            row = self._repo.get("settings", {"key": UI_SETTINGS_KEY})
            ui = m.Settings.model_validate(row["value"]) if row else m.Settings()
            ui.camera_desired = settings
            self._persist(UI_SETTINGS_KEY, ui.model_dump())
        self._post_control(settings.model_dump())

    def set_lock(self, locked: bool) -> None:
        self._mem_locked = locked
        self._persist(LOCK_KEY, {"locked": locked})
        self._post_control({"ae_lock": locked, "awb_lock": locked})

    def _post_control(self, body: dict[str, Any]) -> bool:
        ip = self._ip
        if ip is None:
            return False
        try:
            with self._client(timeout=3.0) as client:
                r = client.post(f"http://{ip}/control", json=body)
                if r.status_code == 400:
                    log.warning("camera rejected control %s: %s", sorted(body), _error_text(r))
                    return False
                r.raise_for_status()
                self._store_device(r.json())
            return True
        except Exception as exc:  # noqa: BLE001  (applied again on the next reconnect)
            log.warning("camera control failed: %s", type(exc).__name__)
            return False

    def _store_device(self, data: Any) -> None:
        if isinstance(data, dict):
            self._device = data
            self._device_current = True

    def _client(self, *, timeout: float) -> httpx.Client:
        token = self._settings.camera_token
        headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
        return httpx.Client(transport=self._transport, headers=headers, timeout=timeout)

    # ---- threads --------------------------------------------------------------------------
    def _wait(self, seconds: float) -> None:
        """Back-off sleep; returns early on stop or reconnect. Tests replace it."""
        remaining = seconds
        while remaining > 0 and not self._stop.is_set() and not self._reconnect.is_set():
            step = min(0.1, remaining)
            self._stop.wait(step)
            remaining -= step

    def _reader(self) -> None:
        delays = backoff_delays()
        while not self._stop.is_set():
            try:
                if self._read_stream():
                    delays = backoff_delays()  # a real connection was made: start the schedule over
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set():
                    log.warning("camera stream error: %s", type(exc).__name__)
            if self._stop.is_set():
                return
            self._wait(next(delays))

    def _read_stream(self) -> bool:
        """One connection attempt. True when the camera accepted the stream request."""
        self._reconnect.clear()
        ip = self._ip = self._resolver(self._settings.camera_host, self._settings.camera_ip)
        if ip is None:
            return False
        with self._client(timeout=5.0) as client, client.stream("GET", f"http://{ip}:81/stream") as resp:
            if resp.status_code != 200:
                log.warning("camera stream refused: HTTP %d", resp.status_code)
                return False
            self._resp = resp
            self._device_current = False  # a new connection may be a rebooted camera: re-confirm the lock
            try:
                self._reapply()
                parser = MjpegParser(_boundary(resp.headers.get("content-type", "")))
                for chunk in resp.iter_raw():
                    if self._stop.is_set():
                        break
                    for part in parser.feed(chunk):
                        if self.ingest(part.body, _int(part.headers.get("x-frame-seq"))) is None:
                            log.debug("camera sent an undecodable frame")
            finally:
                self._resp = None
        return True

    def _reapply(self) -> None:
        """Re-apply lock state, then desired settings, on every (re)connect (addendum L5). The lock
        goes in its own request so a rejected settings body can never drop it."""
        locked = self.locked
        self._post_control({"ae_lock": locked, "awb_lock": locked})
        self._post_control(self.desired.model_dump())

    def _monitor(self) -> None:
        elapsed = POLL_PERIOD_S  # poll immediately
        while not self._stop.is_set():
            self.tick()
            if elapsed >= POLL_PERIOD_S:
                elapsed = 0.0
                self._poll_status()
            if self._stop.wait(TICK_PERIOD_S):
                return
            elapsed += TICK_PERIOD_S

    def _poll_status(self) -> None:
        ip = self._ip
        try:
            if ip is None:
                raise OSError("camera address unresolved")
            with self._client(timeout=2.0) as client:
                r = client.get(f"http://{ip}/status")
                r.raise_for_status()
                self._store_device(r.json())
        except Exception:  # noqa: BLE001
            self._poll_failed()


def _error_text(r: httpx.Response) -> str:
    """The firmware's ``{"error": ...}`` text (L5 validation messages carry no secrets)."""
    try:
        data = r.json()
    except ValueError:
        return f"HTTP {r.status_code}"
    err = data.get("error") if isinstance(data, dict) else None
    return str(err)[:200] if err else f"HTTP {r.status_code}"


def _offer(q: asyncio.Queue[Any], item: Frame | None) -> None:
    """Latest frame wins: drop the oldest queued frame when a slow subscriber is full."""
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(item)


def _boundary(content_type: str) -> bytes:
    for piece in content_type.split(";"):
        key, _, value = piece.strip().partition("=")
        if key.lower() == "boundary" and value:
            return value.strip('"').encode()
    return DEFAULT_BOUNDARY


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
