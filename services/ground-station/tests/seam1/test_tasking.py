"""Seam 1: the tasking controller end to end (§15; F5, G5, I2, J2) over a real broker, with a simulator
Runtime acking commands (``world_with_sim``) or test nodes that hold their acks (``world_no_ack``)."""

from __future__ import annotations

from bcs_gs.core.ids import uuid7
from bcs_protocol.timefmt import from_iso
from gs_tasking import seed_flag, trigger


# ---- brief tests ------------------------------------------------------------------------------------
async def test_flag_triggers_task_and_nodes_ack(world_with_sim):
    await seed_flag(world_with_sim, "KSL-B3")
    t = await world_with_sim.wait_event("task.updated", lambda d: d["status"] == "active")
    assert t["data"]["trigger"] == "zone_flag" and any(
        c["ack_status"] == "accepted" for c in t["data"]["commands"]
    )


async def test_repeat_trigger_extends_instead_of_duplicating(world_with_sim):
    a = await trigger(world_with_sim, "KSL-B3")
    world_with_sim.clock.advance(60)
    b = await trigger(world_with_sim, "KSL-B3")
    assert b["id"] == a["id"] and from_iso(b["expires_at"]) > from_iso(a["expires_at"])


async def test_cooldown_after_completion(world_with_sim):
    a = await trigger(world_with_sim, "KSL-B3")
    world_with_sim.clock.advance(181)
    assert await trigger(world_with_sim, "KSL-B3") is None
    world_with_sim.clock.advance(30)
    assert (await trigger(world_with_sim, "KSL-B3"))["id"] != a["id"]


async def test_cancel_with_pending_acks_returns_nodes_to_baseline(world_no_ack):  # Review Focus 4
    t = await trigger(world_no_ack, "KSL-B3")
    await world_no_ack.http.post(f"/api/v1/tasks/{t['id']}/cancel")
    world_no_ack.release_acks()  # late "accepted" acks arrive now
    final = (await world_no_ack.http.get("/api/v1/tasks", params={"status": "all"})).json()[0]
    assert final["status"] == "cancelled" and world_no_ack.last_cmd_mode_for_each_node() == "baseline"


async def test_unacked_command_retried_once_then_no_ack(world_no_ack):
    await trigger(world_no_ack, "KSL-B3")
    world_no_ack.clock.advance(5)
    world_no_ack.clock.advance(31)
    cmds = (await world_no_ack.http.get("/api/v1/tasks")).json()[0]["commands"]
    assert all(c["retries"] == 1 and c["ack_status"] == "no_ack" for c in cmds)


async def test_recommission_cancels_active_tasks(world_with_sim):  # Review Focus 5
    t = await trigger(world_with_sim, "KSL-B3")
    await world_with_sim.http.post("/api/v1/commissioning", json={"confirm": True})
    final = (await world_with_sim.http.get("/api/v1/tasks", params={"status": "all"})).json()[0]
    assert (
        final["id"] == t["id"]
        and final["status"] == "cancelled"
        and final["reason"].endswith("re-commissioned")
    )


async def test_uncovered_flagged_zone_creates_gap_not_task(world_with_sim):
    await seed_flag(world_with_sim, "KSL-E5")
    cov = await world_with_sim.wait_event(
        "coverage.updated", lambda d: any(g["zone_id"] == "KSL-E5" for g in d["gaps"])
    )
    assert cov and (await world_with_sim.http.get("/api/v1/tasks")).json() == []


# ---- additional ---------------------------------------------------------------------------------------
async def test_late_accepted_acks_after_cancel_are_recorded_but_task_stays_cancelled(world_no_ack):
    t = await trigger(world_no_ack, "KSL-B3")
    await world_no_ack.http.post(f"/api/v1/tasks/{t['id']}/cancel")
    world_no_ack.release_acks()
    final = (await world_no_ack.http.get("/api/v1/tasks", params={"status": "all"})).json()[0]
    inv = [c for c in final["commands"] if c["params"]["mode"] == "investigation"]
    base = [c for c in final["commands"] if c["params"]["mode"] == "baseline"]
    assert [c["ack_status"] for c in inv] == ["released"] * 4
    assert sorted(c["node_id"] for c in base) == sorted(t["node_ids"])
    assert all(c["ack_status"] == "accepted" for c in base)
    assert final["cancelled_by"] == "operator" and "late_ack" in [e["event"] for e in final["timeline"]]


async def test_manual_task_release_and_cancel_routes(world_no_ack):
    http = world_no_ack.http
    r = await http.post("/api/v1/tasks", json={"zone_id": "KSL-B3", "reason": "operator check"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["trigger"] == "manual" and t["node_ids"] == ["WQ-02", "SP-02", "SP-01", "TG-01"]
    r = await http.post(f"/api/v1/tasks/{t['id']}/release", json={"node_id": "SP-01"})
    assert r.status_code == 200 and world_no_ack.last_cmd_mode_for_each_node()["SP-01"] == "baseline"
    assert [c["ack_status"] for c in r.json()["commands"] if c["node_id"] == "SP-01"] == [
        "released",
        "pending",
    ]
    assert (await http.post(f"/api/v1/tasks/{t['id']}/release", json={"node_id": "SP-01"})).status_code == 409
    assert (await http.post(f"/api/v1/tasks/{t['id']}/release", json={"node_id": "WQ-04"})).status_code == 422
    assert (await http.post(f"/api/v1/tasks/{uuid7()}/cancel")).status_code == 404
    assert (await http.post(f"/api/v1/tasks/{t['id']}/cancel")).status_code == 200
    r = await http.post(f"/api/v1/tasks/{t['id']}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    r = await http.post("/api/v1/tasks", json={"zone_id": "KSL-E5"})
    assert r.status_code == 409
    assert (await http.post("/api/v1/tasks", json={})).status_code == 422
    detail = (await http.get("/api/v1/nodes/SP-01")).json()
    assert [x["id"] for x in detail["tasks"]] == [t["id"]] and (await http.get("/api/v1/nodes/WQ-04")).json()[
        "tasks"
    ] == []


async def test_ack_for_unknown_command_is_logged_as_gs_event(world):
    unknown = uuid7()
    world.node("WQ-01").publish_ack(unknown)
    ev = await world.wait_event(
        "node.event", lambda d: d["origin"] == "ground_station" and unknown in json_text(d["details"])
    )
    assert ev["data"]["node_id"] == "WQ-01" and ev["data"]["kind"] == "malformed"
    assert any(unknown in json_text(r["details"]) for r in await world.rows("node_events", node_id="WQ-01"))


def json_text(x: object) -> str:
    import json

    return json.dumps(x)
