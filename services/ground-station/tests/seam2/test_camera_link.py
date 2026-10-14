"""Camera discovery, MJPEG parser, CameraState and CameraLink. Opaque bytes and numbers only;
the one JPEG used is encoded from a generated numpy array."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path

import cv2
import httpx
import numpy as np
from bcs_gs.api.models import CameraSettings
from bcs_gs.camera.discovery import resolve_camera
from bcs_gs.camera.link import CameraLink, CameraState, Transition, backoff_delays
from bcs_gs.camera.mjpeg import MjpegParser
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.config import load_settings
from bcs_gs.core.events import EventBus

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[4]


def _part(body: bytes, seq: int) -> bytes:
    head = b"--bcsframe\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\nX-Frame-Seq: %d\r\n\r\n"
    return head % (len(body), seq) + body + b"\r\n"


def _jpeg(value: int = 100) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((16, 24, 3), value, np.uint8))
    assert ok
    return buf.tobytes()


def _settings(**kw):
    return load_settings(REPO_ROOT, env_file=None, camera_token="cam-token-secret", **kw)


def test_parser_splits_parts_across_arbitrary_chunk_boundaries():
    stream = b"".join(_part(p, i) for i, p in enumerate([b"AAAA", b"BBBBBB", b"C"]))
    parser = MjpegParser(b"bcsframe")
    parts = []
    for i in range(0, len(stream), 7):
        parts += parser.feed(stream[i : i + 7])
    assert [p.body for p in parts] == [b"AAAA", b"BBBBBB", b"C"] and parts[1].headers["x-frame-seq"] == "1"


def test_parser_uses_content_length_when_body_contains_the_boundary():
    tricky = b"xx--bcsframe\r\nContent-Length: 3\r\n\r\nyy"
    stream = _part(tricky, 0) + _part(b"after", 1)
    parser = MjpegParser(b"bcsframe")
    parts = []
    for i in range(0, len(stream), 5):
        parts += parser.feed(stream[i : i + 5])
    assert [p.body for p in parts] == [tricky, b"after"]


def test_offline_after_3s_without_frames_and_recovers():
    s = CameraState()
    t0 = T0
    s.on_frame(t0)
    assert s.tick(t0 + timedelta(seconds=2.9)) == []
    tr = s.tick(t0 + timedelta(seconds=3.0))
    assert tr == [Transition("offline", since=t0)]
    assert s.on_frame(t0 + timedelta(seconds=10)) == [Transition("online", since=t0 + timedelta(seconds=10))]


def test_poll_failure_counts_toward_offline_only_when_frames_are_stale():
    s = CameraState()
    s.on_frame(T0)
    assert s.on_poll_failure(T0 + timedelta(seconds=0.5)) == []
    assert s.on_poll_failure(T0 + timedelta(seconds=1.6)) == [Transition("offline", since=T0)]


def test_backoff_schedule():
    assert list(islice(backoff_delays(), 6)) == [0.5, 1, 2, 4, 5, 5]


def test_resolve_prefers_override_then_system_resolver(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("192.168.1.50", 80))]
    )
    assert resolve_camera("sentinel-cam.local", override="10.0.0.9") == "10.0.0.9"
    assert resolve_camera("sentinel-cam.local", override=None) == "192.168.1.50"


def test_never_started_link_is_offline_since_start_time():
    clock = ManualClock(T0)
    link = CameraLink(_settings(), clock, EventBus(clock=clock))
    clock.advance(60)
    st = link.status()
    assert st.online is False and st.since == "2026-10-16T03:04:05.123Z" and st.last_frame_at is None
    assert link.latest() is None and link.recent(5) == []


def test_ingest_transitions_publish_events_and_callbacks_and_keep_a_ring_of_five():
    clock = ManualClock(T0)
    bus = EventBus(clock=clock)
    sub = bus.subscribe()
    link = CameraLink(_settings(), clock, bus)
    calls = []
    link.on_online(lambda st: calls.append(("online", st.online)))
    link.on_offline(lambda st: calls.append(("offline", st.online)))
    for i in range(7):
        assert link.ingest(_jpeg(i * 30), seq=i) is not None
        clock.advance(0.1)
    assert link.ingest(b"not a jpeg") is None
    assert [f.seq for f in link.recent(10)] == [2, 3, 4, 5, 6] and link.latest().seq == 6
    assert link.latest().image_bgr.shape == (16, 24, 3)
    clock.advance(3.0)
    st = link.status()
    assert st.online is False and st.last_frame_at == "2026-10-16T03:04:05.723Z" == st.since
    assert calls == [("offline", False)]  # first-ever online is not a recovery
    assert [e.type for e in sub._queue] == ["camera.status", "camera.status"]
    assert [e.data["online"] for e in sub._queue] == [True, False]


async def test_subscribe_receives_frames_from_another_thread():
    clock = ManualClock(T0)
    link = CameraLink(_settings(), clock, EventBus(clock=clock))
    link._loop = asyncio.get_running_loop()
    it = link.subscribe()
    first = asyncio.ensure_future(it.__anext__())
    await asyncio.sleep(0.05)
    threading.Thread(target=lambda: link.ingest(_jpeg(), seq=42)).start()
    frame = await asyncio.wait_for(first, 2)
    assert frame.seq == 42
    await it.aclose()


class _Stream(httpx.SyncByteStream):
    def __init__(self, gen):
        self._gen = gen

    def __iter__(self):
        return self._gen

    def close(self):
        pass


class _Cam:
    """httpx MockTransport standing in for the camera: records requests, serves a short stream."""

    def __init__(self, fail_streams: int = 0, frames: int = 3):
        self.requests: list[httpx.Request] = []
        self.fail_streams = fail_streams
        self.frames = frames
        self.hold = threading.Event()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.port == 81:
            if self.fail_streams > 0:
                self.fail_streams -= 1
                return httpx.Response(503)

            def body():
                for i in range(self.frames):
                    yield _part(_jpeg(i * 20), i)
                self.hold.wait(10)

            return httpx.Response(
                200,
                headers={"content-type": "multipart/x-mixed-replace; boundary=bcsframe"},
                content=_Stream(body()),
            )
        if request.url.path == "/control":
            return httpx.Response(200, json={"device_id": "CAM-01", "ae_locked": True})
        return httpx.Response(200, json={"device_id": "CAM-01", "fps": 10})


def _wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_link_streams_reapplies_settings_with_bearer_token_and_stops_cleanly(tmp_path):
    from bcs_gs.store.db import Database
    from bcs_gs.store.repo import Repo

    clock = ManualClock(T0)
    db = Database(tmp_path / "bcs.sqlite3", clock)
    db.migrate()
    repo = Repo(db)
    cam = _Cam()
    link = CameraLink(
        _settings(), clock, EventBus(clock=clock), repo=repo,
        transport=httpx.MockTransport(cam), resolver=lambda host, ov: "10.1.2.3",
    )  # fmt: skip
    link.apply(CameraSettings(jpeg_quality=20))
    link.set_lock(True)
    link.start()
    try:
        assert _wait_for(lambda: link.latest() is not None and link.latest().seq == 2)
        assert link.status().online and link.status().resolved_ip == "10.1.2.3"
        controls = [json.loads(r.content) for r in cam.requests if r.url.path == "/control"]
        assert controls[0] == {"ae_lock": True, "awb_lock": True}  # the lock goes first, on its own
        assert controls[-1]["jpeg_quality"] == 20 and "ae_lock" not in controls[-1]
        assert all(r.headers["authorization"] == "Bearer cam-token-secret" for r in cam.requests)
        assert all("cam-token-secret" not in str(r.url) for r in cam.requests)
        assert _wait_for(lambda: link.status().device is not None)
    finally:
        t = time.monotonic()
        cam.hold.set()
        threads = list(link._threads)
        link.stop()
        assert time.monotonic() - t < 5
    assert threads and not any(th.is_alive() for th in threads)
    db.close()


def test_backoff_resets_after_a_successful_connection():
    clock = ManualClock(T0)
    cam = _Cam(fail_streams=3, frames=1)
    link = CameraLink(
        _settings(), clock, EventBus(clock=clock),
        transport=httpx.MockTransport(cam), resolver=lambda host, ov: "10.1.2.3",
    )  # fmt: skip
    waits: list[float] = []

    def fake_wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) >= 5:
            link._stop.set()

    link._wait = fake_wait  # type: ignore[method-assign]
    cam.hold.set()  # the stream ends right after its frame
    link._reader()
    # three refused attempts climb 0.5, 1, 2; the connection that then succeeds resets to 0.5
    assert waits[:5] == [0.5, 1, 2, 0.5, 0.5]


def test_no_frame_ever_announces_offline_once_and_first_online_is_not_a_recovery():
    s = CameraState(start=T0)
    assert s.tick(T0 + timedelta(seconds=2.9)) == []
    assert s.tick(T0 + timedelta(seconds=3.0)) == [Transition("offline", since=T0)]
    assert s.tick(T0 + timedelta(seconds=9)) == []
    assert s.on_frame(T0 + timedelta(seconds=10)) == [Transition("online", since=T0 + timedelta(seconds=10))]
    fresh = CameraState(start=T0)
    assert fresh.on_frame(T0 + timedelta(seconds=1)) == [
        Transition("online", since=T0 + timedelta(seconds=1), recovered=False)
    ]


def test_link_down_from_boot_fires_offline_callback_but_first_online_does_not_fire_online():
    clock = ManualClock(T0)
    bus = EventBus(clock=clock)
    link = CameraLink(_settings(), clock, bus)
    calls = []
    link.on_offline(lambda st: calls.append("offline"))
    link.on_online(lambda st: calls.append("online"))
    clock.advance(3.0)
    link.tick()
    link.tick()
    link.ingest(_jpeg(), seq=0)  # recovery after the announced offline
    assert calls == ["offline", "online"]
    boot = CameraLink(_settings(), clock, bus)
    boot.on_online(lambda st: calls.append("boot-online"))
    boot.ingest(_jpeg(), seq=0)
    assert "boot-online" not in calls


def test_unlock_is_resent_on_reconnect_when_set_lock_false_failed_while_disconnected():
    clock = ManualClock(T0)
    cam = _Cam(frames=1)
    link = CameraLink(
        _settings(), clock, EventBus(clock=clock),
        transport=httpx.MockTransport(cam), resolver=lambda host, ov: "10.1.2.3",
    )  # fmt: skip
    link.set_lock(True)
    link.set_lock(False)  # no address yet: the POST cannot happen
    cam.hold.set()
    link._read_stream()
    controls = [json.loads(r.content) for r in cam.requests if r.url.path == "/control"]
    assert controls[0] == {"ae_lock": False, "awb_lock": False}


def test_frame_time_window_is_pruned_without_status_calls():
    clock = ManualClock(T0)
    link = CameraLink(_settings(), clock, EventBus(clock=clock))
    for i in range(100):
        link.ingest(_jpeg(), seq=i)
        clock.advance(0.1)
    assert len(link._frame_times) <= 22


class _StrictCam(_Cam):
    """Rejects any body carrying an unknown frame size, like firmware without that size would."""

    def __init__(self, reported: dict | None = None, **kw):
        super().__init__(**kw)
        self.reported = reported if reported is not None else {"ae_locked": True, "awb_locked": True}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/control":
            self.requests.append(request)
            body = json.loads(request.content)
            if body.get("frame_size") == "HD":
                return httpx.Response(400, json={"error": "invalid frame_size"})
            return httpx.Response(200, json={"device_id": "CAM-01", **self.reported})
        return super().__call__(request)


def test_reapply_restores_the_lock_even_when_the_settings_body_is_rejected(caplog):
    clock = ManualClock(T0)
    cam = _StrictCam(frames=1)
    link = CameraLink(
        _settings(), clock, EventBus(clock=clock),
        transport=httpx.MockTransport(cam), resolver=lambda host, ov: "10.1.2.3",
    )  # fmt: skip
    link.apply(CameraSettings(frame_size="HD"))
    link.set_lock(True)
    cam.hold.set()
    with caplog.at_level("WARNING", logger="bcs_gs.camera"):
        link._read_stream()
    controls = [json.loads(r.content) for r in cam.requests if r.url.path == "/control"]
    assert controls[0] == {"ae_lock": True, "awb_lock": True}
    assert controls[1]["frame_size"] == "HD"
    assert link.exposure_locked is True  # the camera confirmed the lock despite the 400
    assert "invalid frame_size" in caplog.text and "cam-token-secret" not in caplog.text


def _link_with_device(device: dict | None, desired_lock: bool, current: bool = True) -> CameraLink:
    clock = ManualClock(T0)
    link = CameraLink(_settings(), clock, EventBus(clock=clock))
    link._mem_locked = desired_lock
    if device is not None:
        link._store_device(device)
    link._device_current = current and device is not None
    return link


def test_exposure_locked_needs_the_desired_lock_and_the_camera_report():
    both = {"ae_locked": True, "awb_locked": True}
    assert _link_with_device(both, True).exposure_locked is True
    assert _link_with_device(both, True).status().locked is True
    assert _link_with_device(None, True).exposure_locked is False  # never reported: not locked
    assert _link_with_device({"ae_locked": True, "awb_locked": False}, True).exposure_locked is False
    assert _link_with_device({"ae_locked": False, "awb_locked": True}, True).exposure_locked is False
    assert _link_with_device({"ae_locked": "true", "awb_locked": True}, True).exposure_locked is False
    assert _link_with_device({}, True).exposure_locked is False
    assert _link_with_device(both, False).exposure_locked is False  # camera still locked, GS wants auto
    assert _link_with_device(both, True, current=False).exposure_locked is False  # stale: new connection


def test_lock_post_that_fails_leaves_the_capture_lock_false():
    clock = ManualClock(T0)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    link = CameraLink(_settings(), clock, EventBus(clock=clock), transport=httpx.MockTransport(timeout))
    link._ip = "10.1.2.3"
    link._store_device({"ae_locked": False, "awb_locked": False})  # last /status poll: auto exposure
    link.set_lock(True)  # times out: GS desires a lock the camera never took
    assert link.locked is True
    assert link.exposure_locked is False and link.status().locked is False
