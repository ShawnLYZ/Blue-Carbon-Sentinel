"""The simulator control API (K1) over an in-memory Runtime (no broker, stub Ground Station)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from bcs_sim.app import WsClientQueue, create_sim_app
from bcs_sim.config import load_sim_settings
from bcs_sim.gs_client import GsError
from bcs_sim.runtime import Runtime


class LifecycleGs:
    """Stub Ground Station public node routes: records calls; ``fail`` makes them answer an I1 error."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail: tuple[int, dict[str, Any]] | None = None

    def _answer(self, what: str, body: Any, ok: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((what, body))
        if self.fail is not None:
            status, err = self.fail
            raise GsError(f"HTTP {status}", status=status, body=err)
        return ok

    def create_node(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._answer("create", body, {"node": {"id": "WQ-05"}, "key": None})

    def move_node(self, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._answer(f"move {node_id}", body, {"id": node_id})

    def decommission_node(self, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._answer(f"decommission {node_id}", body, {"id": node_id, "status": "decommissioned"})

    def coverage(self) -> dict[str, Any]:
        return {"gaps": [{"id": "gap-KSL-E5", "node_type": "soil_probe"}]}


@pytest.fixture
async def api(fake_runtime_factory: Callable[..., Runtime]) -> AsyncIterator[Any]:
    rt = fake_runtime_factory(seed=7)
    life = LifecycleGs()
    for name in ("create_node", "move_node", "decommission_node", "coverage"):
        setattr(rt.fake_gs, name, getattr(life, name))  # type: ignore[attr-defined]
    rt.step(rt.clock.now())
    app = create_sim_app(load_sim_settings(None), runtime=rt)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.rt, c.life, c.app = rt, life, app  # type: ignore[attr-defined]
        yield c


def node(state: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(n for n in state["nodes"] if n["node_id"] == node_id)


async def test_state_shape(api):
    s = (await api.get("/api/v1/state")).json()
    assert set(s) == {
        "broker_connected", "demo_time_scale", "fast_forward", "nature", "nodes", "zone_scenarios",
        "recording", "replay",
    }  # fmt: skip
    assert [n["node_id"] for n in s["nodes"]] == [
        "WQ-01",
        "WQ-02",
        "WQ-03",
        "WQ-04",
        "SP-01",
        "SP-02",
        "SP-03",
        "TG-01",
    ]
    n = node(s, "WQ-02")
    assert set(n) == {
        "node_id", "node_type", "position", "zone_label", "connected", "mode", "interval_s", "readings",
        "natural", "overrides", "battery_pct", "rssi_dbm", "faults", "last_command", "last_ack", "source",
    }  # fmt: skip
    assert n["source"] == "simulated" and n["position"] == {"e_m": 160.0, "s_m": 250.0}
    assert set(n["readings"]) == {"salinity_psu", "turbidity_ntu", "do_mg_l", "temp_c", "ph"}
    assert s["broker_connected"] is True and s["fast_forward"] == 1 and s["demo_time_scale"] is True
    assert s["nature"] == {
        "tide": {"enabled": True, "mean_cm": 0.0, "amplitude_cm": 150.0, "spring_neap": False},
        "diurnal": True,
        "noise": True,
    }


async def test_live_readings_follow_a_scenario_between_samples(api):
    before = node((await api.get("/api/v1/state")).json(), "WQ-02")["readings"]["turbidity_ntu"]
    await api.post("/api/v1/zones/B3/scenario", json={"scenario": "sediment_runoff", "ramp_s": 1})
    api.rt.clock.advance(1.0)  # well inside the 30 s baseline interval: no new sample
    after = node((await api.get("/api/v1/state")).json(), "WQ-02")["readings"]["turbidity_ntu"]
    assert after > before + 50


async def test_live_readings_do_not_disturb_published_determinism(fake_runtime_factory):
    def run(view: bool) -> list[bytes]:
        rt = fake_runtime_factory(seed=3)
        for _ in range(100):
            rt.clock.advance(1.0)
            if view:
                rt.state()
            rt.step(rt.clock.now())
        return [
            m.payload for m in rt.hub.published if m.channel == "telemetry" and m.node_id.startswith("WQ")
        ]

    def strip(payloads: list[bytes]) -> list[dict[str, Any]]:
        docs = [json.loads(p) for p in payloads]
        for d in docs:
            d.pop("boot_id")
        return docs

    assert strip(run(False)) == strip(run(True))


async def test_scenario_catalogue(api):
    cat = (await api.get("/api/v1/scenarios")).json()
    by = {c["id"]: c for c in cat}
    assert set(by) == {
        "sediment_runoff",
        "salt_intrusion",
        "low_oxygen",
        "heat_stress",
        "heavy_rain",
        "healthy",
        "recovery",
    }
    assert by["sediment_runoff"]["offsets"]["turbidity_ntu"] == 150
    assert by["sediment_runoff"]["default_ramp_s"] == 60
    assert by["heavy_rain"]["node_types"] == ["soil_probe", "tide_gauge", "water_quality"]
    assert by["low_oxygen"]["fraction_night"] == 0.3


async def test_scenario_validation_and_clear(api):
    r = await api.post("/api/v1/zones/F9/scenario", json={"scenario": "sediment_runoff"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await api.post("/api/v1/zones/B3/scenario", json={"scenario": "volcano"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = await api.post("/api/v1/zones/KSL-B3/scenario", json={"scenario": "salt_intrusion", "ramp_s": 30})
    body = r.json()
    assert r.status_code == 200 and body["zone_label"] == "B3" and body["warning"] is None
    assert {n["node_id"] for n in body["nodes"]} >= {"WQ-02", "SP-02"}
    zs = (await api.get("/api/v1/state")).json()["zone_scenarios"]
    assert zs["B3"]["scenario"] == "salt_intrusion" and zs["B3"]["ramp_s"] == 30
    r = await api.delete("/api/v1/zones/B3/scenario")
    assert r.status_code == 200 and (await api.get("/api/v1/state")).json()["zone_scenarios"] == {}


async def test_uncovered_zone_warns_but_applies(api):
    r = await api.post("/api/v1/zones/E5/scenario", json={"scenario": "sediment_runoff"})
    assert (
        r.status_code == 200 and r.json()["warning"] == "no node in range of E5" and r.json()["nodes"] == []
    )
    assert "E5" in (await api.get("/api/v1/state")).json()["zone_scenarios"]


async def test_overrides_hold_and_clear(api):
    r = await api.post(
        "/api/v1/nodes/SP-01/overrides",
        json={"parameter": "porewater_salinity_psu", "value": 58, "behaviour": "hold"},
    )
    assert r.status_code == 200
    assert r.json()["overrides"] == {"porewater_salinity_psu": {"value": 58.0, "behaviour": "hold"}}
    assert r.json()["readings"]["porewater_salinity_psu"] == 58.0
    r = await api.delete("/api/v1/nodes/SP-01/overrides/porewater_salinity_psu")
    assert r.status_code == 200 and r.json()["overrides"] == {}


async def test_override_validation(api):
    cases = [
        ("WQ-99", {"parameter": "ph", "value": 7, "behaviour": "hold"}, 404),
        ("WQ-01", {"parameter": "water_level_cm", "value": 7, "behaviour": "hold"}, 422),
        ("WQ-01", {"parameter": "ph", "value": 15, "behaviour": "hold"}, 422),
        ("WQ-01", {"parameter": "ph", "value": 7, "behaviour": "wobble"}, 422),
    ]
    for nid, body, status in cases:
        r = await api.post(f"/api/v1/nodes/{nid}/overrides", json=body)
        assert r.status_code == status, (nid, body, r.text)
        assert "error" in r.json()


async def test_health_sliders(api):
    r = await api.post("/api/v1/nodes/WQ-01/health", json={"battery_pct": 12, "rssi_dbm": -95})
    assert r.status_code == 200 and r.json()["battery_pct"] == 12 and r.json()["rssi_dbm"] == -95
    assert (await api.post("/api/v1/nodes/WQ-01/health", json={"battery_pct": 120})).status_code == 422
    assert (await api.post("/api/v1/nodes/WQ-01/health", json={"rssi_dbm": 5})).status_code == 422


async def test_faults(api):
    r = await api.post("/api/v1/nodes/WQ-01/faults", json={"kind": "low_battery", "params": {"pct": 9}})
    assert r.status_code == 200 and r.json()["battery_pct"] == 9 and "low_battery" in r.json()["faults"]
    assert (await api.post("/api/v1/nodes/WQ-01/faults", json={"kind": "gremlins"})).status_code == 422
    r = await api.post(
        "/api/v1/nodes/WQ-01/faults", json={"kind": "stuck", "params": {"parameter": "water_level_cm"}}
    )
    assert r.status_code == 422
    assert (await api.delete("/api/v1/nodes/WQ-01/faults/gremlins")).status_code == 422
    r = await api.delete("/api/v1/nodes/WQ-01/faults/low_battery")
    assert r.status_code == 200 and r.json()["faults"] == {}


async def test_stuck_fault_shows_in_live_readings(api):
    await api.post(
        "/api/v1/nodes/WQ-02/faults", json={"kind": "stuck", "params": {"parameter": "turbidity_ntu"}}
    )
    api.rt.clock.advance(30)
    api.rt.step(api.rt.clock.now())  # the stuck value is taken at this sample
    stuck = node((await api.get("/api/v1/state")).json(), "WQ-02")["readings"]["turbidity_ntu"]
    await api.post("/api/v1/zones/B3/scenario", json={"scenario": "sediment_runoff", "ramp_s": 0})
    api.rt.clock.advance(1)
    assert node((await api.get("/api/v1/state")).json(), "WQ-02")["readings"]["turbidity_ntu"] == stuck


async def test_nature_patch(api):
    r = await api.patch(
        "/api/v1/nature",
        json={
            "tide": {"mean_cm": 20, "amplitude_cm": 80, "spring_neap": True},
            "diurnal": False,
            "noise": False,
            "fast_forward": 60,
        },
    )
    assert r.status_code == 200
    s = (await api.get("/api/v1/state")).json()
    assert s["fast_forward"] == 60
    assert s["nature"] == {
        "tide": {"enabled": True, "mean_cm": 20.0, "amplitude_cm": 80.0, "spring_neap": True},
        "diurnal": False,
        "noise": False,
    }
    r = await api.patch("/api/v1/nature", json={"tide": {"enabled": False}})
    assert r.json()["nature"]["tide"]["enabled"] is False
    tg = node((await api.get("/api/v1/state")).json(), "TG-01")["readings"]["water_level_cm"]
    assert tg == 20  # tide off: the mean level, noise off
    assert (await api.patch("/api/v1/nature", json={"fast_forward": 0})).status_code == 422


async def test_lifecycle_routes_delegate(api):
    r = await api.post(
        "/api/v1/lifecycle/install", json={"node_type": "water_quality", "position": {"e_m": 1, "s_m": 2}}
    )
    assert r.status_code == 200 and r.json() == {"node": {"id": "WQ-05"}, "key": None}
    r = await api.post("/api/v1/lifecycle/install", json={"suggestion_id": "gap-KSL-E5"})
    assert r.status_code == 200
    await api.post("/api/v1/lifecycle/WQ-01/move", json={"position": {"e_m": 3, "s_m": 4}, "confirm": True})
    await api.post("/api/v1/lifecycle/WQ-01/remove", json={"confirm": True})
    assert api.life.calls == [
        ("create", {"node_type": "water_quality", "source": "simulated", "position": {"e_m": 1, "s_m": 2}}),
        ("create", {"node_type": "soil_probe", "source": "simulated", "suggestion_id": "gap-KSL-E5"}),
        ("move WQ-01", {"position": {"e_m": 3, "s_m": 4}, "confirm": True}),
        ("decommission WQ-01", {"confirm": True}),
    ]


async def test_lifecycle_passes_errors_through(api):
    err = {"error": {"code": "confirmation_required", "message": "confirm", "details": None}}
    api.life.fail = (409, err)
    r = await api.post("/api/v1/lifecycle/WQ-01/remove", json={})
    assert r.status_code == 409 and r.json() == err


async def test_lifecycle_ground_station_unreachable_is_503(api):
    def down(*_a: Any) -> Any:
        raise GsError("POST /nodes: Ground Station unreachable (ConnectError)")

    api.rt.fake_gs.create_node = down
    r = await api.post(
        "/api/v1/lifecycle/install", json={"node_type": "water_quality", "position": {"e_m": 1, "s_m": 2}}
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"


async def test_recording_sessions_and_replay(api):
    r = await api.post("/api/v1/recording/start", json={"name": "rehearsal"})
    assert r.status_code == 200 and r.json()["name"] == "rehearsal"
    assert (await api.post("/api/v1/recording/start", json={"name": "again"})).status_code == 409
    assert (await api.get("/api/v1/state")).json()["recording"]["name"] == "rehearsal"
    for _ in range(4):
        api.rt.clock.advance(30)
        api.rt.step(api.rt.clock.now())
    meta = (await api.post("/api/v1/recording/stop")).json()
    assert meta["uploaded"] is True and meta["message_count"] >= 8 and meta["name"] == "rehearsal"
    assert (await api.post("/api/v1/recording/stop")).status_code == 409
    sessions = (await api.get("/api/v1/sessions")).json()
    assert [s["id"] for s in sessions] == [meta["id"]]
    assert sessions[0]["uploaded"] is True and sessions[0]["local"] is True
    assert (await api.post("/api/v1/sessions/nope/replay")).status_code == 404
    r = await api.post(f"/api/v1/sessions/{meta['id']}/replay")
    assert r.status_code == 200 and r.json()["replay"]["session_id"] == meta["id"]
    assert (await api.post("/api/v1/replay/stop")).json() == {"replay": None}


async def test_sessions_survive_a_new_app(api, fake_runtime_factory):
    await api.post("/api/v1/recording/start", json={"name": "keep"})
    api.rt.clock.advance(30)
    api.rt.step(api.rt.clock.now())
    meta = (await api.post("/api/v1/recording/stop")).json()
    app2 = create_sim_app(load_sim_settings(None), runtime=api.rt)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as c:
        assert [s["id"] for s in (await c.get("/api/v1/sessions")).json()] == [meta["id"]]


async def test_scenario_run_from_text_and_by_name(api):
    script = (
        "name: quick\nseed: 7\nduration_s: 0.4\nsteps:\n"
        "  - {at_s: 0, action: apply_scenario, zone: B3, scenario: heat_stress}\n"
        "  - {at_s: 0.2, action: inject_fault, node: WQ-77, fault: stuck}\n"
    )
    r = await api.post("/api/v1/scenario-runs", json={"script": script})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    deadline = time.monotonic() + 10
    while (body := (await api.get(f"/api/v1/scenario-runs/{run_id}")).json())["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    assert body["status"] == "finished" and body["name"] == "quick"
    assert len(body["log"]["steps"]) == 2 and len(body["log"]["errors"]) == 1
    assert (await api.get("/api/v1/state")).json()["zone_scenarios"]["B3"]["scenario"] == "heat_stress"
    assert (await api.get("/api/v1/scenario-runs/nope")).status_code == 404


async def test_scenario_run_validation(api):
    r = await api.post(
        "/api/v1/scenario-runs",
        json={"script": "name: x\nseed: 1\nduration_s: 5\nsteps:\n  - {at_s: 0, action: fly}\n"},
    )
    assert r.status_code == 422 and r.json()["error"]["details"]["line"] == 5
    assert (await api.post("/api/v1/scenario-runs", json={})).status_code == 422
    assert (await api.post("/api/v1/scenario-runs", json={"name": "../etc/passwd"})).status_code == 422
    assert (await api.post("/api/v1/scenario-runs", json={"name": "no-such-script"})).status_code == 404


async def test_routes_without_a_runtime_answer_503():
    app = create_sim_app(load_sim_settings(None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/zones/B3/scenario", json={"scenario": "healthy"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"
        assert (await c.get("/api/v1/scenarios")).status_code == 200


async def test_ws_queue_drops_oldest_and_reports_count():
    q = WsClientQueue(maxlen=3)
    for i in range(5):
        q.push({"type": "inspector.packet", "data": {"i": i}})
    first = await q.get()
    assert first == {"type": "inspector.packet", "data": {"i": 2}, "dropped": 2}
    assert await q.get() == {"type": "inspector.packet", "data": {"i": 3}}
