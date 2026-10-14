"""Seam 1: the M3 node, commissioning, coverage and task routes (addendum I2, I3) over a real broker."""

from __future__ import annotations

import asyncio

from gs_tasking import seed_flag

API = "/api/v1"


async def _uncovered(world) -> list[str]:
    cov = (await world.http.get(f"{API}/coverage")).json()
    return [z["zone_id"] for z in cov["zones"] if not z["covered"]]


# ---- brief tests ------------------------------------------------------------------------------------
async def test_nodes_list_shows_simulated_source_coverage_and_latest(world_with_sim):
    nodes = (await world_with_sim.http.get(f"{API}/nodes")).json()
    assert len(nodes) == 8 and all(n["source"] == "simulated" for n in nodes)
    assert all(n["latest"] is not None for n in nodes) and "covers" in nodes[0]


async def test_telemetry_window_downsamples(world_with_sim):
    world_with_sim.run_for(seconds=600)
    for _ in range(100):  # the ingest handles the published samples asynchronously
        r = await world_with_sim.http.get(f"{API}/nodes/WQ-01/telemetry", params={"max_points": 5})
        s = r.json()
        if s["downsampled"]:
            break
        await asyncio.sleep(0.1)
    assert s["downsampled"] is True and len(s["points"]) == 5


async def test_move_requires_confirm_and_logs_history(world_with_sim):
    body = {"position": {"e_m": 10, "s_m": 10}}
    assert (await world_with_sim.http.post(f"{API}/nodes/WQ-01/move", json=body)).status_code == 409
    r = await world_with_sim.http.post(f"{API}/nodes/WQ-01/move", json={**body, "confirm": True})
    assert r.status_code == 200 and r.json()["position"]["e_m"] == 10
    assert (await world_with_sim.rows("device_history", device_id="WQ-01"))[-1]["change"] == "moved"


async def test_install_at_gap_suggestion(world_with_sim):
    zone = (await _uncovered(world_with_sim))[0]  # R11: gaps exist only for flagged (or High/Critical) zones
    await seed_flag(world_with_sim, zone)
    await world_with_sim.wait_event("coverage.updated", lambda d: bool(d["gaps"]))
    gap = (await world_with_sim.http.get(f"{API}/coverage")).json()["gaps"][0]
    assert gap["zone_id"] == zone
    body = {"node_type": gap["node_type"], "source": "simulated", "suggestion_id": gap["id"]}
    r = (await world_with_sim.http.post(f"{API}/nodes", json=body)).json()
    assert r["node"]["id"] in ("WQ-05", "SP-04") and r["key"] is None
    assert r["node"]["position"]["e_m"] == gap["e_m"]
    assert zone not in await _uncovered(world_with_sim)


async def test_manual_task_cancel_release_via_api(world_with_sim):
    t = (await world_with_sim.http.post(f"{API}/tasks", json={"zone_id": "KSL-B3"})).json()
    body = {"node_id": t["node_ids"][0]}
    r = (await world_with_sim.http.post(f"{API}/tasks/{t['id']}/release", json=body)).json()
    assert any(c["ack_status"] == "released" for c in r["commands"])


# ---- coverage ---------------------------------------------------------------------------------------
async def test_coverage_has_no_gaps_until_a_zone_is_flagged(world_with_sim):
    cov = (await world_with_sim.http.get(f"{API}/coverage")).json()
    assert len(cov["zones"]) == 25 and cov["gaps"] == []
    assert "KSL-E5" in await _uncovered(world_with_sim)


# ---- lifecycle --------------------------------------------------------------------------------------
async def test_install_by_position_and_validation(world_with_sim):
    http = world_with_sim.http
    body = {"node_type": "soil_probe", "source": "simulated", "position": {"e_m": 100, "s_m": 100}}
    r = await http.post(f"{API}/nodes", json=body)
    assert r.status_code == 200 and r.json()["node"]["id"] == "SP-04" and r.json()["key"] is None
    # neither or both of position and suggestion_id
    bare = {"node_type": "soil_probe", "source": "simulated"}
    assert (await http.post(f"{API}/nodes", json=bare)).status_code == 422
    both = {**body, "suggestion_id": "gap-KSL-E5"}
    assert (await http.post(f"{API}/nodes", json=both)).status_code == 422
    out = {**body, "position": {"e_m": 9999, "s_m": 1}}  # outside the site
    assert (await http.post(f"{API}/nodes", json=out)).status_code == 422
    unk = {"node_type": "soil_probe", "source": "simulated", "suggestion_id": "gap-nope"}
    assert (await http.post(f"{API}/nodes", json=unk)).status_code == 404


async def test_hardware_install_returns_key_once(world_with_sim):
    body = {"node_type": "water_quality", "source": "hardware", "position": {"e_m": 60, "s_m": 400}}
    r = (await world_with_sim.http.post(f"{API}/nodes", json=body)).json()
    assert r["node"]["source"] == "hardware" and isinstance(r["key"], str) and len(r["key"]) >= 16
    again = (await world_with_sim.http.get(f"{API}/nodes/{r['node']['id']}")).text
    assert r["key"] not in again


async def test_decommission_requires_confirm_and_hides_node(world_with_sim):
    http = world_with_sim.http
    assert (await http.post(f"{API}/nodes/SP-03/decommission", json={})).status_code == 409
    err = (await http.post(f"{API}/nodes/SP-03/decommission")).json()
    assert err["error"]["code"] == "confirmation_required"
    r = await http.post(f"{API}/nodes/SP-03/decommission", json={"confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "decommissioned"
    assert "SP-03" not in [n["id"] for n in (await http.get(f"{API}/nodes")).json()]
    listed = (await http.get(f"{API}/nodes", params={"include_decommissioned": True})).json()
    assert "SP-03" in [n["id"] for n in listed]
    assert (await http.post(f"{API}/nodes/SP-03/decommission", json={"confirm": True})).status_code == 409
    assert (await http.post(f"{API}/nodes/NOPE-01/decommission", json={"confirm": True})).status_code == 404


async def test_regenerate_key_simulated_and_hardware(world_with_sim):
    http = world_with_sim.http
    r = (await http.post(f"{API}/nodes/WQ-02/regenerate-key")).json()
    assert r == {"key": None, "reprovision": "simulator"}
    got = await world_with_sim.wait_event(
        "node.registry", lambda d: d["change"] == "key_regenerated" and d["node_ids"] == ["WQ-02"]
    )
    assert got["data"]["change"] == "key_regenerated"
    hw = {"node_type": "tide_gauge", "source": "hardware", "position": {"e_m": 60, "s_m": 400}}
    node = (await http.post(f"{API}/nodes", json=hw)).json()["node"]
    k = (await http.post(f"{API}/nodes/{node['id']}/regenerate-key")).json()
    assert isinstance(k["key"], str) and k.get("reprovision") is None
    assert (await http.post(f"{API}/nodes/NOPE-01/regenerate-key")).status_code == 404


async def test_registry_changes_emit_coverage_updated(world_with_sim):
    await world_with_sim.http.post(
        f"{API}/nodes/WQ-01/move", json={"position": {"e_m": 10, "s_m": 10}, "confirm": True}
    )
    await world_with_sim.wait_event("node.registry", lambda d: d["change"] == "moved")
    await world_with_sim.wait_event("coverage.updated", lambda d: "zones" in d)
