"""Seam 2: preflight checks and the status service (Review Focus 2 and 3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from bcs_gs.core.config import load_settings
from bcs_gs.status.preflight import run_preflight
from bcs_gs.status.probes import FakeProbes

REPO_ROOT = Path(__file__).resolve().parents[4]
IDS = ["camera", "broker", "broker_port", "supabase", "cloud_usage", "gemini_keys", "nvidia_key",
       "mapbox_token", "depth_model", "ollama", "disk"]  # fmt: skip


@pytest.fixture
def fake_probes_all_ok() -> FakeProbes:
    return FakeProbes()


def settings(gemini_keys=("g1", "g2", "g3"), **over):
    keys = {f"gemini_api_key_{i}": k for i, k in enumerate(gemini_keys, 1)}
    base = {
        "gs_mqtt_password": "gs-pw", "supabase_url": "https://x.supabase.co",
        "supabase_service_role_key": "srk", "supabase_access_token": "sat",
        "nvidia_api_key": "nv", "mapbox_public_token": "pk.t",
    }  # fmt: skip
    return load_settings(REPO_ROOT, env_file=None, **{**base, **keys, **over})


def check(report, cid):
    return next(c for c in report.checks if c.id == cid)


def test_all_green_except_camera(fake_probes_all_ok):
    fake_probes_all_ok.camera = None
    r = run_preflight(settings(), fake_probes_all_ok)
    assert [c.id for c in r.checks] == IDS
    assert {c.id: c.status for c in r.checks}["camera"] == "fail"
    assert all(c.status == "pass" for c in r.checks if c.id != "camera")


def test_broker_port_held_by_foreign_process_fails_with_hint(fake_probes_all_ok):  # Review Focus 2
    fake_probes_all_ok.port_owner = lambda p: "foreign"
    c = check(run_preflight(settings(), fake_probes_all_ok), "broker_port")
    assert c.status == "fail" and "stop and disable the Mosquitto service" in c.fix_hint


def test_paused_supabase_warns_with_dashboard_link(fake_probes_all_ok):
    fake_probes_all_ok.project_status = "INACTIVE"
    c = check(run_preflight(settings(), fake_probes_all_ok), "supabase")
    assert c.status == "fail" and "https://supabase.com/dashboard/project/x" in c.fix_hint


def test_supabase_url_without_a_project_ref_warns(fake_probes_all_ok):
    c = check(run_preflight(settings(supabase_url="https://db.example.org"), fake_probes_all_ok), "supabase")
    assert c.status == "warn" and "BCS_SUPABASE_URL" in c.fix_hint


def test_missing_keys_fail_individually(fake_probes_all_ok):  # Review Focus 3
    c = check(run_preflight(settings(gemini_keys=[]), fake_probes_all_ok), "gemini_keys")
    assert c.status == "fail" and "BCS_GEMINI_API_KEY_1" in c.fix_hint
    r = run_preflight(
        settings(gemini_keys=[], nvidia_api_key=None, mapbox_public_token=None), fake_probes_all_ok
    )
    assert [check(r, i).status for i in ("gemini_keys", "nvidia_key", "mapbox_token")] == ["fail"] * 3


def test_db_size_warns_at_400mb(fake_probes_all_ok):
    fake_probes_all_ok.db_bytes = 401_000_000
    assert check(run_preflight(settings(), fake_probes_all_ok), "cloud_usage").status == "warn"


def test_depth_model_missing_fails_with_fetch_hint(fake_probes_all_ok):
    fake_probes_all_ok.depth_present = False
    c = check(run_preflight(settings(), fake_probes_all_ok), "depth_model")
    assert c.status == "fail" and "bcs-gs fetch-models" in c.fix_hint


def test_cpu_only_onnxruntime_warns(fake_probes_all_ok):
    fake_probes_all_ok.directml = False
    assert check(run_preflight(settings(), fake_probes_all_ok), "depth_model").status == "warn"


def test_rejected_gemini_slot_is_named_without_the_key(fake_probes_all_ok):
    fake_probes_all_ok.gemini_models = lambda key: key != "g2"
    c = check(run_preflight(settings(), fake_probes_all_ok), "gemini_keys")
    assert c.status == "warn" and "BCS_GEMINI_API_KEY_2 rejected" in c.fix_hint
    assert "g2" not in (c.detail + c.fix_hint).replace("KEY_2", "")


def test_a_raising_probe_becomes_a_fail_never_a_crash(fake_probes_all_ok):
    def boom(key):
        raise RuntimeError("https://x/?key=nv-secret")

    fake_probes_all_ok.nvidia_auth = boom
    r = run_preflight(settings(), fake_probes_all_ok)
    c = check(r, "nvidia_key")
    assert c.status == "fail" and "nv-secret" not in c.detail + (c.fix_hint or "")
    assert len(r.checks) == 11


def test_missing_broker_password_and_tokens_are_reported(fake_probes_all_ok):
    r = run_preflight(settings(gs_mqtt_password=None, supabase_access_token=None), fake_probes_all_ok)
    assert check(r, "broker").status == "fail" and "BCS_GS_MQTT_PASSWORD" in check(r, "broker").fix_hint
    assert check(r, "supabase").status == "warn" and "SUPABASE_ACCESS_TOKEN" in check(r, "supabase").fix_hint


# ---- status service through the API -----------------------------------------------------------
async def test_preflight_route_uses_probes_and_status_reflects_it(gs):
    r = (await gs.http.post("/api/v1/system/preflight")).json()
    assert [c["id"] for c in r["checks"]] == IDS
    st = (await gs.http.get("/api/v1/system/status")).json()
    comp = {c["id"]: c["status"] for c in st["components"]}
    assert (
        comp["broker"] == "ok"
        and comp["ollama"] == "ok"
        and st["depth"]["provider"] == "DmlExecutionProvider"
    )
    assert st["cloud"]["db_bytes"] == 12_000_000 and st["cloud"]["paused"] is False


async def test_heartbeats_written_per_component_on_status_tick(gs):
    gs.clock.advance(5)
    for _ in range(100):
        rows = gs.services.repo.query("SELECT component FROM system_heartbeats")
        if len(rows) >= 10:
            break
        await asyncio.sleep(0.05)
    assert {r["component"] for r in rows} >= {"ground_station", "broker", "cloud", "sync"} and len(rows) == 10


def test_depth_model_checks_the_flat_directory_layout(fake_probes_all_ok):
    seen = []
    fake_probes_all_ok.depth_model_present = lambda p: seen.append(p) or p.name == "model.onnx"
    c = check(run_preflight(settings(), fake_probes_all_ok), "depth_model")
    assert c.status == "pass"  # fp32 fallback is enough
    assert {p.name for p in seen} == {"model_fp16.onnx", "model.onnx"}
    assert all(p.parent.name == "depth-anything-v2-small" and p.parent.parent.name == "models" for p in seen)


def test_httpx_request_logging_is_silenced_by_setup():
    import logging

    from bcs_gs.core.logging import setup_logging

    setup_logging("INFO")
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


async def test_system_status_is_published_on_the_loop_thread(gs):
    import threading

    svc = gs.services
    threads: list[int] = []
    orig = svc.bus.publish

    def spy(type, data):
        threads.append(threading.get_ident())
        return orig(type, data)

    svc.bus.publish = spy
    async with gs.events() as ev:
        await ev.next()
        gs.clock.advance(5)
        await ev.wait_for("system.status", timeout=5)
    assert threads and set(threads) == {gs._thread.ident}  # the server loop thread, never a worker


def test_port_owner_ignores_stale_pid_files(tmp_path):
    import socket

    from bcs_gs.status.probes import RealProbes

    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        # This test process is python, so a fresh pid file naming it is "ours" ...
        (tmp_path / "x.pid").write_text(str(__import__("os").getpid()))
        assert RealProbes(tmp_path).port_owner(port) == "ours"
        # ... but a pid file from before the process started, or an empty/garbage one, is stale.
        import os

        os.utime(tmp_path / "x.pid", (1, 1))
        (tmp_path / "empty.pid").write_text("")
        assert RealProbes(tmp_path).port_owner(port) == "foreign"
        assert not list(tmp_path.glob("*.pid"))
