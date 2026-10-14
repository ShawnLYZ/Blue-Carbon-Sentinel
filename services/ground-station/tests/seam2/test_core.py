import asyncio
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.config import load_settings
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import boot_id, ledger_record_id, node_id, uuid7
from bcs_protocol.timefmt import from_iso, to_iso

REPO_ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 10, 16, tzinfo=UTC)


def test_iso_format_has_millis_and_z():
    assert to_iso(datetime(2026, 10, 16, 3, 4, 5, 123456, tzinfo=UTC)) == "2026-10-16T03:04:05.123Z"
    with pytest.raises(ValueError):
        from_iso("2026-10-16T03:04:05")  # naive rejected


def test_iso_round_trip_and_offsets():
    assert from_iso("2026-10-16T03:04:05.123Z") == datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)
    assert from_iso("2026-10-16T11:04:05+08:00") == datetime(2026, 10, 16, 3, 4, 5, tzinfo=UTC)
    with pytest.raises(ValueError):
        to_iso(datetime(2026, 10, 16))  # noqa: DTZ001 (deliberately naive)


def test_uuid7_is_time_ordered_and_versioned():
    a, b = uuid7(), uuid7()
    assert a < b and a[14] == "7"
    ids = [uuid7() for _ in range(10000)]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert all(i[19] in "89ab" for i in ids[:100])


def test_id_formats():
    assert ledger_record_id(2026, 1) == "BC-2026-00001"
    assert node_id("WQ", 5) == "WQ-05" and node_id("WQ", 120) == "WQ-120"
    assert re.fullmatch(r"[0-9a-f]{12}", boot_id())


async def test_manual_clock_wakes_sleepers_on_advance():
    c = ManualClock(datetime(2026, 10, 16, tzinfo=UTC))
    t = asyncio.create_task(c.sleep(30))
    await asyncio.sleep(0)
    c.advance(29)
    await asyncio.sleep(0)
    assert not t.done()
    c.advance(1)
    await asyncio.sleep(0)
    assert t.done()


async def test_manual_clock_cross_thread_advance_wakes_every_sleeper():
    """sleep() pushes on the loop while a test thread advances: no lost or double wake-ups."""
    import threading

    c = ManualClock(T0)
    n = 200
    stop = threading.Event()

    def advancer() -> None:
        while not stop.is_set():
            c.advance(0.5)

    th = threading.Thread(target=advancer, daemon=True)
    th.start()
    try:
        tasks = []
        for i in range(n):
            tasks.append(asyncio.create_task(c.sleep(1 + (i % 7))))
            if i % 10 == 0:
                await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    finally:
        stop.set()
        th.join(timeout=5)
    assert all(t.done() and t.exception() is None for t in tasks)


def test_manual_clock_advance_after_loop_closed_does_not_raise():
    c = ManualClock(T0)
    loop = asyncio.new_event_loop()
    task = loop.create_task(c.sleep(5))
    loop.run_until_complete(asyncio.sleep(0))
    task.cancel()
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    loop.close()
    c.advance(10)  # owning loop is closed: must be swallowed, not raised


def test_settings_precedence_yaml_then_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BCS_THRESHOLDS__FLAGS__CANOPY_LOSS_PP", "8")
    s = load_settings(REPO_ROOT, env_file=None)
    assert s.thresholds.flags.canopy_loss_pp == 8 and s.thresholds.flags.dieback_pct == 15


def test_settings_load_with_missing_optional_secrets(monkeypatch):  # Review Focus 3
    for k in list(os.environ):
        if k.startswith(("BCS_GEMINI", "BCS_NVIDIA")):
            monkeypatch.delenv(k)
    s = load_settings(REPO_ROOT, env_file=None)
    assert s.gemini_api_key_1 is None and s.nvidia_api_key is None


def test_env_file_is_read_and_secrets_stay_masked(tmp_path, monkeypatch):
    monkeypatch.delenv("BCS_NVIDIA_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("BCS_NVIDIA_API_KEY=abc123\n# BCS_CAMERA_HOST=\nSUPABASE_DB_PASSWORD=pw\nOTHER=1\n")
    s = load_settings(REPO_ROOT, env_file=env)
    assert s.nvidia_api_key.get_secret_value() == "abc123"
    assert s.supabase_db_password.get_secret_value() == "pw"
    assert "abc123" not in repr(s) and "abc123" not in str(s.model_dump())
    assert s.camera_host == "sentinel-cam.local"


def test_yaml_values_carried_over():
    s = load_settings(REPO_ROOT, env_file=None)
    assert s.site.id == "KSL" and s.site.size_m == 500
    assert s.thresholds.motion.motion_threshold == 4.0 and s.thresholds.motion.change_threshold == 6.0
    assert sum(s.risk.weights.values()) == pytest.approx(1.0)
    assert s.carbon.buffer_pct.value == 15 and s.carbon.ecosystem_density_mg_c_ha.value == 1074
    assert s.bands.parameters["do_mg_l"].breakpoints == [(0.5, 1.0), (2.0, 0.6), (5.0, 0)]
    assert s.ai.chains["tree_locator"][0] == "robotics_er"
    assert s.forecast.bounds["g"] == (0.0, 0.15)


def test_site_nw_env_override(monkeypatch):
    monkeypatch.setenv("BCS_SITE_NW_LAT", "3.5")
    s = load_settings(REPO_ROOT, env_file=None)
    assert s.site.anchor_nw.lat == 3.5


def test_demo_values_match_addendum_n12():
    on = load_settings(REPO_ROOT, env_file=None, demo_time_scale="on").demo_values()
    off = load_settings(REPO_ROOT, env_file=None, demo_time_scale="off").demo_values()
    assert (
        on.baseline_interval_s, on.investigation_interval_s, on.task_duration_s,
        on.task_cooldown_s, on.verified_sensor_window_s,
    ) == (30, 2, 180, 30, 120)
    assert (
        off.baseline_interval_s, off.investigation_interval_s, off.task_duration_s,
        off.task_cooldown_s, off.verified_sensor_window_s,
    ) == (900, 30, 1800, 900, 86400)
    assert on.capture_interval_s == off.capture_interval_s == 10


async def test_event_bus_delivers_and_drops_slow_subscriber():
    bus = EventBus(clock=ManualClock(T0))
    sub = bus.subscribe(maxsize=2)
    for i in range(3):
        bus.publish("system.status", {"i": i})
    assert sub.closed  # overflow closes (addendum J2: close code 1013 upstream)


async def test_event_bus_delivers_in_order_with_envelope_fields():
    bus = EventBus(clock=ManualClock(T0))
    sub = bus.subscribe()
    e = bus.publish("hello", {"x": 1})
    assert e.at == "2026-10-16T00:00:00.000Z" and e.id[14] == "7"
    got = await asyncio.wait_for(sub.__anext__(), 1)
    assert got == e
    sub.close()
    with pytest.raises(StopAsyncIteration):
        await sub.__anext__()
    assert bus.subscriber_count == 0


def test_log_timestamps_are_utc_f2_format():
    import logging
    import time

    from bcs_gs.core.logging import make_formatter

    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)
    rec.created = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC).timestamp()
    rec.msecs = 123.0
    out = make_formatter().format(rec)
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", out)
    assert out.startswith("2026-10-16T03:04:05.123Z ")
    assert time.gmtime  # converter is gmtime, independent of local zone


def test_redaction_covers_exception_text_and_uvicorn_loggers():
    import io
    import logging

    from bcs_gs.core.logging import make_formatter, register_secret, setup_logging

    secret = "AIzaSyFAKEKEY-for-test-0123456789"
    register_secret(secret)
    setup_logging("INFO")
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(make_formatter())  # no filter on the handler: the logger's filter must do it
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.addHandler(h)
        try:
            raise RuntimeError(f"GET https://x/y?key={secret} failed")
        except RuntimeError:
            lg.exception("request failed")
        lg.removeHandler(h)
    out = buf.getvalue()
    assert out.count("request failed") == 3 and secret not in out and "key=***" in out


def test_redact_filter_masks_cached_exc_text():
    import logging

    from bcs_gs.core.logging import RedactFilter, register_secret

    register_secret("sb-secret-value-9")
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "m", None, None)
    rec.exc_text = "Traceback ... sb-secret-value-9"
    assert RedactFilter().filter(rec) and "sb-secret-value-9" not in rec.exc_text


# ---- ruling R30: cancelled background work leaves no write running behind it ----------------------------
async def test_to_thread_settled_waits_for_the_thread_on_cancel():
    import threading
    import time

    from bcs_gs.core.aio import cancel_and_wait, to_thread_settled

    started, done = threading.Event(), []

    def work() -> None:
        started.set()
        time.sleep(0.3)
        done.append(True)

    task = asyncio.create_task(to_thread_settled(work))
    await asyncio.to_thread(started.wait, 5)
    await cancel_and_wait([task])
    assert task.cancelled() and done == [True]  # the write finished before the cancel returned
    assert await to_thread_settled(lambda x: x + 1, 1) == 2
