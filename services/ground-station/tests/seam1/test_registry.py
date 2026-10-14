"""Seam 1: NodeRegistry, device keys, broker identities and the internal simulator routes."""

from __future__ import annotations

import json

import pytest
from bcs_gs.nodes.keys import hash_key, new_key, verify_key
from gs_seam1_helpers import can_connect

HDR = {"X-BCS-Sim-Token": "sim-shared-secret"}
API = "/api/v1/internal/sim"


def test_key_helpers():
    k = new_key()
    assert len(k) >= 43 and new_key() != k
    h = hash_key(k)
    assert h.startswith("pbkdf2_sha256$200000$") and k not in h
    assert verify_key(k, h) and not verify_key(k + "x", h) and not verify_key(k, "garbage")
    assert hash_key(k) != h  # random salt


async def test_install_creates_identity_key_hash_and_history(gs_broker):
    node, key = gs_broker.registry.install("water_quality", "hardware", 120, 340)
    assert node.id == "WQ-01" and len(key) >= 43
    row = gs_broker.repo.get("device_keys", {"device_id": "WQ-01"})
    assert row["key_hash"].startswith("pbkdf2_sha256$200000$") and key not in json.dumps(row)
    assert can_connect(gs_broker.mqtt, "WQ-01", key)
    dev = gs_broker.repo.get("devices", {"id": "WQ-01"})
    assert dev["kind"] == "sentinel_node" and dev["source"] == "hardware" and dev["zone_id"] == "KSL-B4"
    assert dev["lat"] and dev["lng"] and dev["u_px"] and dev["status"] == "unknown"
    hist = gs_broker.repo.query("SELECT change FROM device_history WHERE device_id = 'WQ-01'")
    assert [h["change"] for h in hist] == ["installed"]


async def test_ids_continue_and_are_never_reused(gs_broker):
    for _ in range(4):
        gs_broker.registry.install("water_quality", "simulated", 10, 10)
    gs_broker.registry.decommission("WQ-04")
    n, _ = gs_broker.registry.install("water_quality", "simulated", 10, 10)
    assert n.id == "WQ-05"
    assert gs_broker.registry.next_id("soil_probe") == "SP-01"
    assert gs_broker.registry.next_id("tide_gauge") == "TG-01"


async def test_move_decommission_and_regenerate(gs_broker):
    reg = gs_broker.registry
    _, key = reg.install("soil_probe", "hardware", 10, 10)
    moved = reg.move("SP-01", 250, 250)
    assert (moved.e_m, moved.s_m, moved.zone_id) == (250, 250, "KSL-C3")
    new = reg.regenerate_key("SP-01")
    assert new != key
    assert not can_connect(gs_broker.mqtt, "SP-01", key)
    assert can_connect(gs_broker.mqtt, "SP-01", new)
    assert gs_broker.repo.get("device_keys", {"device_id": "SP-01"})["rotations"] == 1
    reg.decommission("SP-01")
    assert not can_connect(gs_broker.mqtt, "SP-01", new)
    assert reg.get("SP-01").status == "decommissioned"
    assert [n.id for n in reg.nodes()] == []
    assert [n.id for n in reg.nodes(include_decommissioned=True)] == ["SP-01"]
    rows = gs_broker.repo.query("SELECT change FROM device_history WHERE device_id = 'SP-01' ORDER BY at, rowid")
    assert [r["change"] for r in rows] == ["installed", "moved", "key_regenerated", "decommissioned"]
    with pytest.raises(ValueError):
        reg.move("SP-01", 1, 1)


async def test_camera_is_registered_without_a_key(gs_broker):
    cam = gs_broker.repo.get("devices", {"id": "CAM-01"})
    assert cam["kind"] == "camera" and cam["source"] == "hardware"
    assert gs_broker.repo.get("device_keys", {"device_id": "CAM-01"}) is None
    assert gs_broker.registry.nodes() == []


async def test_provision_simulated_never_touches_hardware(gs_broker):
    reg = gs_broker.registry
    _, hw_key = reg.install("water_quality", "hardware", 10, 10)
    _, sim_key = reg.install("water_quality", "simulated", 200, 10)
    out = reg.provision_simulated(None)
    assert set(out) == {"WQ-02"} and out["WQ-02"] != sim_key
    assert can_connect(gs_broker.mqtt, "WQ-01", hw_key)
    assert not can_connect(gs_broker.mqtt, "WQ-02", sim_key)
    assert can_connect(gs_broker.mqtt, "WQ-02", out["WQ-02"])
    assert reg.provision_simulated(["WQ-01"]) == {}


async def test_registry_changes_emit_node_registry_events(gs_broker):
    async with gs_broker.events() as ev:
        await ev.wait_for("hello")
        gs_broker.registry.install("tide_gauge", "simulated", 250, 250)
        msg = await ev.wait_for("node.registry", lambda m: m["data"]["change"] == "installed")
        assert msg["data"]["node_ids"] == ["TG-01"]
        gs_broker.registry.provision_simulated(None)
        msg = await ev.wait_for("node.registry", lambda m: m["data"]["change"] == "key_regenerated")
        assert msg["data"]["node_ids"] == ["TG-01"]


async def test_internal_routes_require_token(gs_broker):
    assert (await gs_broker.http.post(f"{API}/credentials", json={})).status_code == 403
    assert (await gs_broker.http.get(f"{API}/registry")).status_code == 403
    bad = {"X-BCS-Sim-Token": "wrong"}
    assert (await gs_broker.http.get(f"{API}/registry", headers=bad)).status_code == 403
    assert (await gs_broker.http.post(f"{API}/sessions", headers=bad)).status_code == 403


async def test_registry_and_credentials_routes(gs_broker):
    gs_broker.registry.install("water_quality", "simulated", 160, 250)
    gs_broker.registry.install("water_quality", "hardware", 10, 10)
    body = (await gs_broker.http.get(f"{API}/registry", headers=HDR)).json()
    assert body == {
        "site_id": "KSL",
        "nodes": [
            {
                "node_id": "WQ-01",
                "node_type": "water_quality",
                "position": {"e_m": 160, "s_m": 250},
                "zone_label": "B3",
            }
        ],
    }
    r = await gs_broker.http.post(f"{API}/credentials", headers=HDR, json={"node_ids": ["WQ-01"]})
    (cred,) = r.json()["credentials"]
    assert cred["node_id"] == cred["username"] == "WQ-01"
    assert can_connect(gs_broker.mqtt, "WQ-01", cred["password"])
    assert cred["password"] not in json.dumps(gs_broker.repo.get("device_keys", {"device_id": "WQ-01"}))


async def test_sessions_route_stores_file_and_row(gs_broker):
    meta = {
        "id": "sess-1", "created_at": "2026-10-16T03:04:05.123Z", "name": "demo", "kind": "recording",
        "seed": 42, "duration_s": 12.5, "message_count": 2,
    }  # fmt: skip
    r = await gs_broker.http.post(
        f"{API}/sessions", headers=HDR, data={"meta": json.dumps(meta)},
        files={"file": ("sess-1.jsonl", b'{"a":1}\n{"a":2}\n', "application/x-ndjson")},
    )  # fmt: skip
    assert r.status_code == 200 and r.json()["id"] == "sess-1"
    row = gs_broker.repo.get("sim_sessions", {"id": "sess-1"})
    assert row["media_key"] == "sess-1.jsonl" and row["message_count"] == 2 and row["seed"] == 42
    path = gs_broker.data_dir / "var" / "media" / "sim-sessions" / "sess-1.jsonl"
    assert path.read_bytes() == b'{"a":1}\n{"a":2}\n'
    mo = gs_broker.repo.query("SELECT state FROM media_objects WHERE bucket='sim-sessions'")
    assert mo[0]["state"] == "pending"
    bad = await gs_broker.http.post(f"{API}/sessions", headers=HDR, data={"meta": "{}"})
    assert bad.status_code == 422


async def test_simulator_runtime_gets_registry_and_credentials(gs_broker, sim_runtime_factory):
    rt = sim_runtime_factory()
    rt.start()
    try:
        assert set(rt.credentials) == {"WQ-01", "WQ-02", "WQ-03", "WQ-04", "SP-01", "SP-02", "SP-03", "TG-01"}
    finally:
        rt.stop()


async def test_simulator_restart_rotates_credentials(gs_broker, sim_runtime_factory):
    rt1 = sim_runtime_factory()
    rt1.start()
    k1 = rt1.credentials["SP-01"]
    rt1.stop()
    rt2 = sim_runtime_factory()
    rt2.start()
    k2 = rt2.credentials["SP-01"]
    assert k1 != k2
    assert can_connect(gs_broker.mqtt, "SP-01", k2)
    assert not can_connect(gs_broker.mqtt, "SP-01", k1)


# ---- commissioning (Task 8) ----------------------------------------------------------------------
EIGHT_IDS = ["SP-01", "SP-02", "SP-03", "TG-01", "WQ-01", "WQ-02", "WQ-03", "WQ-04"]


def estuary_mask():
    import numpy as np

    c = np.full((512, 512), 1, np.uint8)  # canopy east
    c[:, :170] = 2  # west third water
    c[:, 170:230] = 3  # mud band
    return c


async def test_first_start_auto_commissions_eight_nodes_low_confidence(gs_broker_fresh):
    run = (await gs_broker_fresh.http.get("/api/v1/commissioning")).json()
    assert len(run["positions"]) == 8 and run["confidence"] == "low"
    assert run["method"] == "fallback_spread" and run["reasons"] == ["no capture available"]
    assert run["capture_id"] is None
    nodes = (await gs_broker_fresh.http.get("/api/v1/nodes")).json()
    assert sorted(n["id"] for n in nodes) == EIGHT_IDS
    assert all(n["source"] == "simulated" and n["latest"] is None for n in nodes)
    assert all(set(n["position"]) == {"e_m", "s_m", "lat", "lng", "u_px", "v_px"} for n in nodes)
    wq = next(n for n in nodes if n["id"] == "WQ-01")
    assert wq["covers"]["water"] and wq["covers"]["soil"] == []
    tg = next(n for n in nodes if n["id"] == "TG-01")
    assert tg["covers"] == {"water": [], "soil": []} and tg["zone_id"] == "KSL-A3"
    dev = gs_broker_fresh.repo.get("devices", {"id": "WQ-01"})
    assert dev["commissioning_run_id"] == run["id"]


async def test_no_commissioning_run_yet_is_not_found(gs_broker):
    r = await gs_broker.http.get("/api/v1/commissioning")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert (await gs_broker.http.get("/api/v1/nodes")).json() == []


async def test_recommission_keeps_ids_and_logs_history(gs_broker_fresh):  # Review Focus 5
    gs = gs_broker_fresh
    before = {n["id"]: n["position"] for n in (await gs.http.get("/api/v1/nodes")).json()}
    cap_id = await gs.set_latest_class_map(estuary_mask())
    async with gs.events() as ev:
        await ev.wait_for("hello")
        r = await gs.http.post("/api/v1/commissioning", json={"confirm": True})
        assert r.status_code == 200
        reg = await ev.wait_for("node.registry", lambda m: m["data"]["change"] == "re_commissioned")
        cov = await ev.wait_for("coverage.updated")
    run = r.json()
    assert run["capture_id"] == cap_id and run["method"] == "class_map" and run["confidence"] == "high"
    assert reg["data"]["commissioning_run_id"] == run["id"] and sorted(reg["data"]["node_ids"]) == EIGHT_IDS
    assert len(cov["data"]["zones"]) == 25
    after = {n["id"]: n["position"] for n in (await gs.http.get("/api/v1/nodes")).json()}
    assert sorted(after) == EIGHT_IDS == sorted(before) and after != before
    assert {r["change"] for r in await gs.rows("device_history")} >= {"installed", "re_commissioned"}
    latest = (await gs.http.get("/api/v1/commissioning")).json()
    assert latest["id"] == run["id"]
    # H7: the run protects its capture from thinning
    assert cap_id in gs.services.retention._protected_ids()


async def test_recommission_requires_confirmation(gs_broker_fresh):
    r = await gs_broker_fresh.http.post("/api/v1/commissioning", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirmation_required"
    r = await gs_broker_fresh.http.post("/api/v1/commissioning")
    assert r.status_code == 409


async def test_recommission_awaits_the_hook(gs_broker_fresh):
    called = []

    async def hook():
        called.append(True)

    gs_broker_fresh.services.commissioning.on_recommission = hook
    r = await gs_broker_fresh.http.post("/api/v1/commissioning", json={"confirm": True})
    assert r.status_code == 200 and called == [True]


# ---- key-rotation feedback loop (M3 final review A1) ------------------------------------------------
def _rotations(gs_broker, node_id: str) -> int:
    row = gs_broker.repo.get("device_keys", {"device_id": node_id})
    return row["rotations"]


async def _watching_runtime(gs_broker, sim_runtime_factory):
    """A started runtime whose registry watcher is subscribed to /ws/events."""
    import asyncio

    base = gs_broker.services.bus.subscriber_count
    rt = sim_runtime_factory(watch_registry=True)
    await asyncio.to_thread(rt.start)
    for _ in range(200):
        if gs_broker.services.bus.subscriber_count > base:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("the registry watcher never subscribed")
    return rt


async def test_regenerate_key_with_watcher_rotates_at_most_once_more(gs_broker, sim_runtime_factory):
    import asyncio

    rt = await _watching_runtime(gs_broker, sim_runtime_factory)
    try:
        before = _rotations(gs_broker, "WQ-02")
        await asyncio.to_thread(gs_broker.registry.regenerate_key, "WQ-02")  # the operator's rotation
        await asyncio.sleep(10)
        # the operator's rotation plus the simulator fetching the new key: at most one more
        assert _rotations(gs_broker, "WQ-02") - before <= 2
        assert can_connect(gs_broker.mqtt, "WQ-02", rt.credentials["WQ-02"])
    finally:
        await asyncio.to_thread(rt.stop)


async def test_install_with_watcher_rotates_at_most_once(gs_broker, sim_runtime_factory):
    import asyncio

    rt = await _watching_runtime(gs_broker, sim_runtime_factory)
    try:
        node, _ = await asyncio.to_thread(
            gs_broker.registry.install, "water_quality", "simulated", 450.0, 450.0
        )
        await asyncio.sleep(10)
        assert _rotations(gs_broker, node.id) <= 1  # install sets 0; the simulator's fetch rotates once
        assert node.id in rt.nodes
        assert can_connect(gs_broker.mqtt, node.id, rt.credentials[node.id])
    finally:
        await asyncio.to_thread(rt.stop)
