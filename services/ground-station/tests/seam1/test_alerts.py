"""AlertService (M4 Task 6): severities, dedupe windows, acknowledgement, event mapping."""

from __future__ import annotations

import asyncio
from typing import Any

from gs_assess import seed_flag


async def _alerts(world: Any, type_: str | None = None, **params: Any) -> list[dict[str, Any]]:
    r = await world.http.get("/api/v1/alerts", params=params)
    assert r.status_code == 200, r.text
    return [a for a in r.json() if type_ is None or a["type"] == type_]


async def test_dedupe_window_counts_occurrences(world):  # Review Focus 5
    for _ in range(5):
        await world.publish_node_event("WQ-01", kind="anomaly", parameter="turbidity_ntu")
    a = await _alerts(world, "node_anomaly")
    assert len(a) == 1 and a[0]["occurrences"] == 5
    world.clock.advance(301)
    await world.publish_node_event("WQ-01", kind="anomaly", parameter="turbidity_ntu")
    assert len(await _alerts(world, "node_anomaly")) == 2


async def test_ai_degraded_alert_deduplicated_per_role(world_offline_ai):  # Review Focus 3
    for z in ["KSL-B3", "KSL-C3", "KSL-D3"]:
        await seed_flag(world_offline_ai, z)
    # The three flags give three RiskInterpreter calls served by rules (background tasks): one alert.
    # (VisionAnalyst never runs for seeded captures: they have no JPEG, so it is covered below.)
    await world_offline_ai.wait_event(
        "alert.created",
        lambda d: d["type"] == "ai_degraded" and d["details"]["role"] == "risk_interpreter",
        timeout=20,
    )
    deg = await _alerts(world_offline_ai, "ai_degraded")
    # The first baseline also starts the HistorySynthesizer (M4 Task 7), which is degraded too: one alert
    # per role, whatever the number of calls.
    roles = [a["details"]["role"] for a in deg]
    assert len(roles) == len(set(roles))
    # Seeded captures carry synthetic media (ruling R22a), so the vision analyst and tree locator run too.
    assert set(roles) <= {"risk_interpreter", "history_synthesizer", "vision_analyst", "tree_locator"}
    risk = [a for a in deg if a["details"]["role"] == "risk_interpreter"]
    assert len(risk) == 1 and risk[0]["severity"] == "warning" and risk[0]["details"]["tier"] == "rules"


async def _publish(world: Any, type_: str, data: dict[str, Any]) -> None:
    svc = world.gs.services

    async def go() -> None:
        svc.bus.publish(type_, data)

    await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(go(), svc.tasking.loop))


def _ai_call(role: str, tier: str, status: str = "success") -> dict[str, Any]:
    return {"call_id": f"c-{role}-{tier}-{status}", "role": role, "tier": tier, "status": status,
            "cached": False, "fallback_from": None}  # fmt: skip


async def test_ai_degraded_counts_only_serving_rows_once_per_role(world):
    for _ in range(3):
        await _publish(world, "ai.call", _ai_call("vision_analyst", "rules"))
    await _publish(
        world, "ai.call", _ai_call("vision_analyst", "gemini_primary", "unavailable")
    )  # failed attempt
    await _publish(world, "ai.call", _ai_call("risk_interpreter", "gemini_primary"))  # not degraded
    await _publish(world, "ai.call", _ai_call("tree_locator", "gemma_local", "cache_hit"))
    await world.wait_event("alert.created", lambda d: d["details"].get("role") == "tree_locator")
    deg = {a["details"]["role"]: a for a in await _alerts(world, "ai_degraded")}
    assert set(deg) == {"vision_analyst", "tree_locator"}
    assert deg["vision_analyst"]["occurrences"] == 3 and deg["vision_analyst"]["severity"] == "warning"
    assert deg["tree_locator"]["severity"] == "info"


async def test_node_anomaly_message_has_units_and_zscore(world):
    await world.publish_node_event("WQ-02", kind="anomaly", parameter="turbidity_ntu", value=162.8, score=4.1)
    (a,) = await _alerts(world, "node_anomaly")
    assert a["message"] == "WQ-02 turbidity spike: 162.8 NTU (z 4.1)" and a["node_id"] == "WQ-02"


async def test_low_battery_and_ack_filter(world):
    world.node("WQ-03").publish_telemetry(1, health={"battery_pct": 9.0, "rssi_dbm": -60.0, "uptime_s": 1.0,
                                                     "fw_version": "t"})  # fmt: skip
    a = (await world.wait_event("alert.created", lambda d: d["type"] == "node_low_battery"))["data"]
    assert a["node_id"] == "WQ-03" and a["severity"] == "warning" and "9.0 %" in a["message"]
    assert [x["id"] for x in await _alerts(world, unacknowledged="true")] == [a["id"]]
    r = await world.http.post(f"/api/v1/alerts/{a['id']}/ack")
    assert r.status_code == 200 and r.json()["acknowledged_at"]
    assert await _alerts(world, unacknowledged="true") == []
    assert (await world.http.post("/api/v1/alerts/nope/ack")).status_code == 404


async def test_duplicate_while_unacknowledged_and_new_after_ack(world):
    first = await world.raise_alert("camera_offline")
    again = await world.raise_alert("camera_offline")  # no window: dedupe while unacknowledged
    assert again["id"] == first["id"] and again["occurrences"] == 2
    await world.http.post(f"/api/v1/alerts/{first['id']}/ack")
    third = await world.raise_alert("camera_offline")
    assert third["id"] != first["id"] and third["occurrences"] == 1


async def test_acknowledge_emits_event(world):
    a = await world.raise_alert("camera_offline")
    async with world.events() as ev:
        await world.http.post(f"/api/v1/alerts/{a['id']}/ack")
        assert (await ev.wait_for("alert.acknowledged"))["data"]["id"] == a["id"]


async def test_node_offline_is_critical(world_with_sim):
    world_with_sim.sim.fault("WQ-02", "offline")
    world_with_sim.run_for(60)
    a = await world_with_sim.wait_event("alert.created", lambda d: d["type"] == "node_offline", timeout=15)
    assert a["data"]["severity"] == "critical" and a["data"]["node_id"] == "WQ-02"


def _assessed(cls: str, zone: str = "KSL-B3") -> dict[str, Any]:
    return {"id": f"a-{cls}", "zone_id": zone, "risk_class": cls, "risk_score": 85.0, "early_warning": False}


async def test_risk_critical_fires_on_entering_critical_only(world):
    async def critical_alerts() -> list[dict[str, Any]]:
        await asyncio.sleep(0.5)  # let the alert listener drain
        return await _alerts(world, "risk_critical")

    await _publish(world, "zone.assessed", _assessed("critical"))  # code-only
    await _publish(world, "zone.assessed", _assessed("critical"))  # AI follow-up: not a second entry
    (a,) = await critical_alerts()
    assert a["occurrences"] == 1
    await world.http.post(f"/api/v1/alerts/{a['id']}/ack")
    await _publish(world, "zone.assessed", _assessed("critical"))  # still critical after the ack
    assert len(await critical_alerts()) == 1
    await _publish(world, "zone.assessed", _assessed("high"))
    await _publish(world, "zone.assessed", _assessed("critical"))  # re-entered
    assert len(await critical_alerts()) == 2


async def test_early_warning_alert_carries_the_spec_wording(world):  # spec §16 / addendum N5
    await _publish(world, "zone.assessed", {**_assessed("low", "KSL-E3"), "early_warning": True})
    await asyncio.sleep(0.5)  # let the alert listener drain
    (a,) = await _alerts(world, "early_warning")
    assert a["zone_id"] == "KSL-E3"
    assert "Sub-canopy stress — not yet visible from orbit" in a["message"]
