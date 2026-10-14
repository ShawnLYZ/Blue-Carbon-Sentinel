"""Seam 1: the simulator control API (addendum K1), ``/ws`` (K2) and lifecycle delegation, against a real
Ground Station and Mosquitto (``sim_world``: WQ-02 lies in B3; no WQ or SP node reaches E5)."""

from __future__ import annotations

import asyncio

from helpers import NODES_8, eventually


async def reading(sim_world, node_id: str, key: str) -> float:
    nodes = (await sim_world.http.get("/api/v1/state")).json()["nodes"]
    return next(n for n in nodes if n["node_id"] == node_id)["readings"][key]


async def state_ids(sim_world) -> set[str]:
    return {n["node_id"] for n in (await sim_world.http.get("/api/v1/state")).json()["nodes"]}


# ---- the brief's tests ---------------------------------------------------------------------------
async def test_scenario_changes_covering_node_within_one_second(sim_world):
    before = await reading(sim_world, "WQ-02", "turbidity_ntu")
    r = await sim_world.http.post(
        "/api/v1/zones/B3/scenario", json={"scenario": "sediment_runoff", "ramp_s": 1}
    )
    assert r.status_code == 200 and r.json()["warning"] is None
    sim_world.clock.advance(1.0)
    assert await reading(sim_world, "WQ-02", "turbidity_ntu") > before + 50


async def test_uncovered_zone_warns(sim_world):
    r = (await sim_world.http.post("/api/v1/zones/E5/scenario", json={"scenario": "sediment_runoff"})).json()
    assert r["warning"] == "no node in range of E5"


async def test_fault_inject_and_clear(sim_world):
    await sim_world.http.post(
        "/api/v1/nodes/WQ-01/faults", json={"kind": "stuck", "params": {"parameter": "ph"}}
    )
    assert "stuck" in (await sim_world.http.get("/api/v1/state")).json()["nodes"][0]["faults"]
    r = await sim_world.http.delete("/api/v1/nodes/WQ-01/faults/stuck")
    assert r.status_code == 200
    assert "stuck" not in (await sim_world.http.get("/api/v1/state")).json()["nodes"][0]["faults"]


async def test_inspector_stream_carries_up_and_down_packets(sim_world):
    async with sim_world.ws() as ws:
        await sim_world.gs_task("KSL-B3")
        dirs = {p["data"]["direction"] for p in await ws.collect("inspector.packet", n=20)}
        assert dirs == {"up", "down"}


async def test_recording_upload_creates_session_on_ground_station(sim_world):
    await sim_world.http.post("/api/v1/recording/start", json={"name": "rehearsal"})
    sim_world.run_for(30)
    meta = (await sim_world.http.post("/api/v1/recording/stop")).json()
    assert meta["uploaded"] is True and meta["message_count"] > 0
    assert any(s["id"] == meta["id"] for s in (await sim_world.http.get("/api/v1/sessions")).json())
    rows = await asyncio.to_thread(
        sim_world.gs.services.repo.query, 'SELECT * FROM "sim_sessions"', (), table="sim_sessions"
    )
    assert [r["id"] for r in rows] == [meta["id"]]


# ---- more of K1 / K2 ------------------------------------------------------------------------------
async def test_heavy_rain_counts_the_tide_gauge_reach(sim_world):
    # E5 has no WQ/SP reach, but heavy rain also raises the water level, and the TG reaches 500 m.
    r = (await sim_world.http.post("/api/v1/zones/E5/scenario", json={"scenario": "heavy_rain"})).json()
    assert r["warning"] is None
    assert [n["node_id"] for n in r["nodes"]] == ["TG-01"]


async def test_ws_streams_node_state_at_four_hz_and_status(sim_world):
    async with sim_world.ws() as ws:
        status = ws.of("sim.status")[0]["data"]
        assert status["broker_connected"] is True and status["recording"] is None
        first = await ws.next_of("nodes.state")
        assert {n["node_id"] for n in first["data"]} == {n[0] for n in NODES_8}
        assert all(n["source"] == "simulated" for n in first["data"])
        await asyncio.sleep(1.0)
        assert 2 <= len(ws.of("nodes.state")) <= 8  # 4 Hz, with scheduling slack
        await sim_world.http.post("/api/v1/recording/start", json={"name": "ws"})
        st = await ws.next_of("sim.status")
        assert st["data"]["recording"]["name"] == "ws"
        await sim_world.http.post("/api/v1/recording/stop")


async def test_inspector_packets_are_validated(sim_world):
    async with sim_world.ws() as ws:
        await sim_world.http.post("/api/v1/nodes/WQ-03/faults", json={"kind": "malformed"})
        sim_world.run_for(30, step_s=10)
        pkts = await ws.collect("inspector.packet", n=200, timeout=2)
        bad = [p["data"] for p in pkts if p["data"]["node_id"] == "WQ-03" and not p["data"]["valid"]]
        assert bad and all(p["errors"] for p in bad)
        good = [
            p["data"] for p in pkts if p["data"]["channel"] == "telemetry" and p["data"]["node_id"] == "WQ-01"
        ]
        assert good and good[0]["valid"] and good[0]["topic"] == "bcs/v1/KSL/nodes/WQ-01/telemetry"


async def test_lifecycle_install_move_remove_delegate_to_ground_station(sim_world):
    r = await sim_world.http.post(
        "/api/v1/lifecycle/install", json={"node_type": "water_quality", "position": {"e_m": 450, "s_m": 450}}
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert (
        created["node"]["id"] == "WQ-05"
        and created["node"]["source"] == "simulated"
        and created["key"] is None
    )
    await eventually(lambda: "WQ-05" in sim_world.runtime.nodes, timeout=10)
    assert "WQ-05" in await state_ids(sim_world)

    r = await sim_world.http.post(
        "/api/v1/lifecycle/WQ-05/move", json={"position": {"e_m": 440, "s_m": 440}, "confirm": True}
    )
    assert r.status_code == 200 and r.json()["position"]["e_m"] == 440
    await eventually(lambda: sim_world.runtime.nodes["WQ-05"].node.e_m == 440, timeout=10)

    r = await sim_world.http.post("/api/v1/lifecycle/WQ-05/remove", json={"confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "decommissioned"
    await eventually(lambda: "WQ-05" not in sim_world.runtime.nodes, timeout=10)


async def test_lifecycle_passes_ground_station_errors_through(sim_world):
    body = {"position": {"e_m": 10, "s_m": 10}}
    direct = await sim_world.gs_http.post("/api/v1/nodes/WQ-01/move", json=body)
    via = await sim_world.http.post("/api/v1/lifecycle/WQ-01/move", json=body)
    assert via.status_code == direct.status_code == 409
    assert via.json() == direct.json() and via.json()["error"]["code"] == "confirmation_required"
    r = await sim_world.http.post("/api/v1/lifecycle/WQ-99/remove", json={"confirm": True})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await sim_world.http.post(
        "/api/v1/lifecycle/install", json={"node_type": "water_quality", "position": {"e_m": 900, "s_m": 10}}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_replay_of_an_uploaded_session_is_marked_replay(sim_world):
    await sim_world.http.post("/api/v1/recording/start", json={"name": "for-replay"})
    sim_world.run_for(31)
    meta = (await sim_world.http.post("/api/v1/recording/stop")).json()
    async with sim_world.ws() as ws:
        r = await sim_world.http.post(f"/api/v1/sessions/{meta['id']}/replay")
        assert r.status_code == 200, r.text
        assert (await sim_world.http.get("/api/v1/state")).json()["replay"]["session_id"] == meta["id"]
        sim_world.run_for(31)
        pkts = await ws.collect("inspector.packet", n=500, timeout=2)
        replayed = [
            p["data"]
            for p in pkts
            if isinstance(p["data"]["payload"], dict) and p["data"]["payload"].get("replay")
        ]
        assert replayed and all(p["payload"]["source"] == "simulated" for p in replayed)
    assert (await sim_world.http.post("/api/v1/replay/stop")).json()["replay"] is None
