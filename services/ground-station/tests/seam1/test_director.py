"""Seam 1: the Demo Director state machine (§27; F5, I2, I3, J2). It advances only on real bus events."""

from __future__ import annotations

import asyncio

from gs_tasking import manual_task, seed_flag


async def _state(d):
    return (await d.http.get("/api/v1/director")).json()


async def _publish(world, type_, data):
    """A real-shaped event on the Ground Station's bus, as the owning service would publish it."""
    bus = world.gs.services.bus
    world.gs.services.tasking.loop.call_soon_threadsafe(bus.publish, type_, data)


async def _settle(world):
    await asyncio.sleep(0.2)  # the director's listener runs on the loop


# ---- brief tests -------------------------------------------------------------------------------------
async def test_telemetry_driven_steps_advance_and_capture_steps_block(world_with_sim):  # §Testing Seam 1
    d = world_with_sim
    await d.http.post("/api/v1/director/start", json={"branch": "main"})
    s = (await d.http.get("/api/v1/director")).json()
    assert s["current"] == "detect" and s["steps"][0]["status"] == "blocked"
    assert s["steps"][0]["blocked_reason"] == "Camera offline — step requires live captures"
    await d.http.post("/api/v1/director/skip")
    await manual_task(d, "KSL-B3")
    await d.wait_event("director.state", lambda x: x["current"] == "measure")
    d.sim.apply("B3", "sediment_runoff", ramp_s=1)
    d.run_for(seconds=12)
    await d.wait_event("director.state", lambda x: x["current"] == "fuse")


async def test_detect_blocked_when_camera_offline_and_branch_available(world):  # Review Focus 1
    await world.http.post("/api/v1/director/start", json={"branch": "early_warning"})
    s = (await world.http.get("/api/v1/director")).json()
    assert s["branch"] == "early_warning" and s["current"] == "early_warning" and s["steps"][0]["status"] == "waiting"
    assert [x["key"] for x in s["steps"]][:2] == ["early_warning", "detect"]
    assert s["steps"][1]["status"] == "pending"


async def test_late_event_does_not_reopen_skipped_step(world):  # Review Focus 2
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    await world.http.post("/api/v1/director/skip")
    await seed_flag(world, "KSL-B3")
    await _settle(world)
    s = (await world.http.get("/api/v1/director")).json()
    assert s["steps"][0]["status"] == "skipped" and s["current"] == "task"


async def test_retry_resets_waiting_and_stop_deactivates(world):
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    await world.http.post("/api/v1/director/retry")
    assert (await world.http.get("/api/v1/director")).json()["steps"][0]["detected"] is None
    await world.http.post("/api/v1/director/stop")
    assert (await world.http.get("/api/v1/director")).json()["active"] is False


# ---- extra behaviour ---------------------------------------------------------------------------------
async def test_inactive_by_default_and_skip_retry_conflict(world):
    s = await _state(world)
    assert s["active"] is False and s["current"] is None and len(s["steps"]) == 7
    assert s["steps"][0]["action"] == "Brown or remove a tree"
    assert (await world.http.post("/api/v1/director/skip")).status_code == 409
    assert (await world.http.post("/api/v1/director/retry")).status_code == 409


async def test_flag_advances_detect_even_while_blocked_and_records_detected(world):
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    await seed_flag(world, "KSL-B3")
    e = await world.wait_event("director.state", lambda x: x["current"] == "task")
    step = e["data"]["steps"][0]
    assert step["status"] == "done"
    assert step["detected"]["type"] == "zone.flagged"
    assert step["detected"]["summary"] == "Zone B3 flagged: canopy loss 12.0 pp"


async def test_non_current_event_is_ignored(world):
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    await _publish(world, "ledger.appended", {
        "chain_index": 1, "record_id": "r", "type": "verified", "quantity_tco2e": "1.0",
    })  # fmt: skip
    await _settle(world)
    s = await _state(world)
    assert s["current"] == "detect" and s["steps"][-1]["status"] == "pending"


async def test_camera_status_change_reevaluates_blocked(world):
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    cam = world.gs.services.camera
    online = cam.status().model_copy(update={"online": True})
    cam.status = lambda: online  # the link reports online
    await _publish(world, "camera.status", online.model_dump(mode="json"))
    e = await world.wait_event("director.state", lambda x: x["steps"][0]["status"] == "waiting")
    assert e["data"]["steps"][0]["blocked_reason"] is None
    off = online.model_copy(update={"online": False})
    cam.status = lambda: off
    await _publish(world, "camera.status", off.model_dump(mode="json"))
    await world.wait_event("director.state", lambda x: x["steps"][0]["status"] == "blocked")


async def test_restore_needs_applied_plan_then_new_growth_in_planted_zone(world):
    d = world
    await d.http.post("/api/v1/director/start", json={"branch": "main"})
    for _ in range(5):
        await d.http.post("/api/v1/director/skip")
    assert (await _state(d))["current"] == "restore"
    growth = {"capture_id": "c", "zone_id": "KSL-B3", "flags": [{"kind": "new_growth", "value": 4.0, "threshold": 2.0}]}
    await _publish(d, "zone.flagged", growth)  # no plan yet: ignored
    await _settle(d)
    assert (await _state(d))["current"] == "restore"
    plan = {"plan_id": "p1", "version": 1, "status": "applied", "source": "ai",
            "created_at": "2026-10-13T00:00:00Z", "applied_at": "2026-10-13T00:00:00Z", "zones": ["KSL-C2"]}  # fmt: skip
    await _publish(d, "plan.updated", plan)
    await _publish(d, "zone.flagged", growth)  # B3 is not planted: ignored
    await _settle(d)
    assert (await _state(d))["current"] == "restore"
    await _publish(d, "zone.flagged", {**growth, "zone_id": "KSL-C2"})
    e = await d.wait_event("director.state", lambda x: x["current"] == "verify")
    assert e["data"]["steps"][5]["status"] == "done"


# ---- fix round 1: advance conditions ----------------------------------------------------------------
async def _wait_state(world, pred, timeout=5):
    """Poll GET /director until ``pred(state)`` (the listener runs on the loop)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while True:
        s = await _state(world)
        if pred(s):
            return s
        assert loop.time() < end, f"director state never matched: {s['current']}"
        await asyncio.sleep(0.02)


async def _skip_to(world, key, branch="main"):
    await world.http.post("/api/v1/director/start", json={"branch": branch})
    while (await _state(world))["current"] != key:
        await world.http.post("/api/v1/director/skip")


def _assessment(zone="KSL-B3", narrative="Stress from runoff.", early=False):
    return {
        "id": "a", "zone_id": zone, "at": "2026-10-13T00:00:00Z", "early_warning": early,
        "narrative": narrative, "risk_class": "high",
    }  # fmt: skip


def _task(created_at, accepted=True, nodes=("n1", "n2")):
    return {
        "id": "t1", "created_at": created_at, "zone_id": "KSL-B3", "node_ids": list(nodes),
        "commands": [{"ack_status": "accepted" if accepted else "pending"}],
    }  # fmt: skip


def _telemetry(node, mode="investigation"):
    return {"node_id": node, "mode": mode}


def _plan():
    return {
        "plan_id": "p1", "version": 1, "status": "applied", "source": "ai",
        "created_at": "2026-10-13T00:00:00Z", "applied_at": "2026-10-13T00:00:00Z", "zones": ["KSL-C2"],
    }  # fmt: skip


def _growth(zone="KSL-C2", kind="new_growth"):
    return {"capture_id": "c", "zone_id": zone, "flags": [{"kind": kind, "value": 4.0, "threshold": 2.0}]}


async def test_early_warning_advances_only_on_early_warning_assessment(world):
    await _skip_to(world, "early_warning", branch="early_warning")
    await _publish(world, "zone.assessed", _assessment(early=False))
    await _settle(world)
    assert (await _state(world))["current"] == "early_warning"
    await _publish(world, "zone.assessed", _assessment(early=True))
    s = await _wait_state(world, lambda s: s["current"] == "detect")
    assert s["steps"][0]["status"] == "done" and s["steps"][0]["detected"]["type"] == "zone.assessed"


async def test_task_advances_on_accepted_ack_even_if_task_predates_step(world):
    """The automatic task is created before detect completes: its created_at predates the task step."""
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    await seed_flag(world, "KSL-B3")
    await _wait_state(world, lambda s: s["current"] == "task")
    await _publish(world, "task.updated", _task("2000-01-01T00:00:00Z", accepted=False))
    await _settle(world)
    assert (await _state(world))["current"] == "task"  # no ack yet
    await _publish(world, "task.updated", _task("2000-01-01T00:00:00Z"))
    await _wait_state(world, lambda s: s["current"] == "measure")
    ctx = world.gs.services.director._ctx
    assert ctx.tasked_node_ids == ["n1", "n2"] and ctx.task_id == "t1"


async def test_real_automatic_flow_flag_to_auto_task_ack(world_with_sim):
    d = world_with_sim
    await d.http.post("/api/v1/director/start", json={"branch": "main"})
    await seed_flag(d, "KSL-B3")
    s = await _wait_state(d, lambda s: s["current"] == "measure", timeout=10)
    assert [x["status"] for x in s["steps"][:2]] == ["done", "done"]
    assert s["steps"][1]["detected"]["type"] == "task.updated"


async def test_measure_needs_five_samples_from_tasked_nodes_only(world):
    await _skip_to(world, "task")
    await _publish(world, "task.updated", _task("2000-01-01T00:00:00Z"))
    await _wait_state(world, lambda s: s["current"] == "measure")
    for _ in range(4):
        await _publish(world, "node.telemetry", _telemetry("n1"))
    for _ in range(3):
        await _publish(world, "node.telemetry", _telemetry("other"))  # not tasked
        await _publish(world, "node.telemetry", _telemetry("n2", mode="baseline"))  # wrong mode
    await _settle(world)
    assert (await _state(world))["current"] == "measure"
    await _publish(world, "node.telemetry", _telemetry("n2"))
    await _wait_state(world, lambda s: s["current"] == "fuse")


async def test_measure_without_task_context_accepts_any_node(world):
    await _skip_to(world, "measure")
    for _ in range(5):
        await _publish(world, "node.telemetry", _telemetry("anything"))
    await _wait_state(world, lambda s: s["current"] == "fuse")


async def test_fuse_only_for_flagged_zone_with_narrative(world):
    await world.http.post("/api/v1/director/start", json={"branch": "main"})
    await seed_flag(world, "KSL-B3")
    await _wait_state(world, lambda s: s["current"] == "task")
    await world.http.post("/api/v1/director/skip")
    await world.http.post("/api/v1/director/skip")
    assert (await _state(world))["current"] == "fuse"
    await _publish(world, "zone.assessed", _assessment(zone="KSL-C2"))  # other zone
    await _publish(world, "zone.assessed", _assessment(narrative="  "))  # empty narrative
    await _settle(world)
    assert (await _state(world))["current"] == "fuse"
    await _publish(world, "zone.assessed", _assessment())
    await _wait_state(world, lambda s: s["current"] == "predict")


async def test_fuse_with_unknown_flagged_zone_accepts_any_zone(world):
    await _skip_to(world, "fuse")
    await _publish(world, "zone.assessed", _assessment(zone="KSL-C2"))
    await _wait_state(world, lambda s: s["current"] == "predict")


async def test_predict_only_on_ready_forecast(world):
    await _skip_to(world, "predict")
    await _publish(world, "forecast.ready", {"forecast_id": "f1", "plan_id": None, "status": "failed"})
    await _settle(world)
    assert (await _state(world))["current"] == "predict"
    await _publish(world, "forecast.ready", {"forecast_id": "f1", "plan_id": None, "status": "ready"})
    await _wait_state(world, lambda s: s["current"] == "restore")
    assert world.gs.services.director._ctx.forecast_id == "f1"


async def test_verify_only_on_verified_record(world):
    await _skip_to(world, "verify")
    rec = {"chain_index": 3, "record_id": "r", "type": "projected", "quantity_tco2e": "1.0"}
    await _publish(world, "ledger.appended", rec)
    await _settle(world)
    assert (await _state(world))["current"] == "verify"
    await _publish(world, "ledger.appended", {**rec, "type": "verified"})
    s = await _wait_state(world, lambda s: s["current"] is None)
    assert s["active"] is True and s["steps"][-1]["status"] == "done"
    assert s["steps"][-1]["detected"]["type"] == "ledger.appended"


async def test_retry_mid_progress_resets_current_step_only(world):
    await _skip_to(world, "measure")
    for _ in range(4):
        await _publish(world, "node.telemetry", _telemetry("a"))
    await _settle(world)
    await world.http.post("/api/v1/director/retry")
    await _publish(world, "node.telemetry", _telemetry("a"))  # would be the 5th without the reset
    await _settle(world)
    s = await _state(world)
    assert s["current"] == "measure" and s["steps"][2]["status"] == "waiting"
    assert s["steps"][0]["status"] == "skipped"  # earlier steps untouched
    assert world.gs.services.director._ctx.measure_samples == 1


async def test_plan_applied_during_predict_satisfies_restore_phase_one(world):
    await _skip_to(world, "predict")
    await _publish(world, "plan.updated", _plan())
    await _settle(world)
    assert (await _state(world))["current"] == "predict"  # the plan alone advances nothing
    await _publish(world, "forecast.ready", {"forecast_id": "f1", "plan_id": "p1", "status": "ready"})
    await _wait_state(world, lambda s: s["current"] == "restore")
    await _publish(world, "zone.flagged", _growth(kind="canopy_loss"))
    await _settle(world)
    assert (await _state(world))["current"] == "restore"  # a real new_growth flag is still required
    await _publish(world, "zone.flagged", _growth())
    s = await _wait_state(world, lambda s: s["current"] == "verify")
    assert s["steps"][5]["status"] == "done"


async def test_plan_applied_never_reopens_finished_steps(world):
    await _skip_to(world, "predict")
    await _publish(world, "plan.updated", _plan())
    await _settle(world)
    s = await _state(world)
    assert [x["status"] for x in s["steps"]][:4] == ["skipped"] * 4 and s["current"] == "predict"
