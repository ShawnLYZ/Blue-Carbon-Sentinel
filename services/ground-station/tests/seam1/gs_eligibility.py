"""Seam-1 eligibility helpers and fixtures (M6 Task 4), built on ``world_ready`` and the ledger worlds.

- ``world_projected``: a plan with planting applied in KSL-B3 and its Projected record. The zone's covering
  WQ / SP test nodes are online and report healthy telemetry; the camera reads as online (so camera
  confidence can reach N4's top values) and the forecast parameters come from the (fake) cloud tier, so
  overall confidence can pass 0.80. Adds:
  - ``projected_id`` and ``projected_zone_quantity(zone)`` (the Projected zone net, a tCO2e string);
  - ``clock``: the ManualClock whose ``advance(s)`` moves in steps of ``STEP_S``, the online covering
    nodes reporting healthy telemetry at each step (as live nodes do; without it the silence watchdog
    would mark them offline during a long advance);
  - ``sim``: ``fault(node_id, "offline")`` / ``clear_fault(node_id, "offline")``: the node announces
    ``offline`` (and stops reporting) / ``online`` again (and reports).
- ``world_projected_uncovered_zone``: the same for KSL-E5, which no WQ / SP covers. A temporary SP covers
  it while the Projected record is created (the checklist needs coverage), then is decommissioned.
- ``world_projected_rules_only_unlocked``: ``world_applied_plan`` (rules-tier forecast, camera offline)
  with its Projected record and a later evidence-grade capture whose exposure was not locked.
- ``await seed_recovery_capture(w, zone, new_growth_pct=4.0)``: an evidence-grade capture whose zone keeps
  the canopy it had at application (45 %) and shows ``new_growth_pct`` of new growth.
- ``await seed_three_recovery_captures(w, zone, new_growth_pct=4.0)``.
- ``await settle(w)``: one eligibility evaluation on the Ground Station loop, now (it issues what is due).
- ``await verified_records(w)``: ``settle`` then the Verified records (newest first).
- ``await eligibility(w, zone)``: that zone's ZoneEligibility from ``GET /ledger/eligibility``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from gs_assess import FLAG_CANOPY_PCT, _seed_capture
from gs_forecast import FORECAST_TIMEOUT_S, install_cloud_fpe, on_gs_loop, propose_and_wait, wait_count
from gs_ledger import LedgerWorld, create_projected

STEP_S = 10.0
UPLIFT = {"canopy_pp_2035": 0.0, "tco2e_2035": 0.0}


def planting(zone: str) -> list[dict[str, Any]]:
    return [
        {"zone_id": zone, "interventions": [{"kind": "plant_rhizophora", "sapling_count": 880},
                                            {"kind": "silt_fence"}],
         "priority": 1, "rationale": "eligibility test", "expected_uplift": UPLIFT},
    ]  # fmt: skip


class _OnlineCamera:
    """Stands in for the CameraLink in the fusion engine: online (seam-1 runs without a camera)."""

    def status(self) -> Any:
        return SimpleNamespace(online=True)


class _Nodes:
    """The covering test nodes, kept reporting healthy telemetry."""

    def __init__(self, world: Any, node_ids: list[str]) -> None:
        self.world = world
        self.live: list[str] = list(node_ids)
        self.seq: dict[str, int] = dict.fromkeys(node_ids, 0)

    def report(self, node_id: str) -> None:
        self.world.node(node_id).publish_telemetry(self.seq[node_id])
        self.seq[node_id] += 1

    def heartbeat(self) -> None:
        for n in self.live:
            self.report(n)


class LiveClock:
    """The world's ManualClock; ``advance`` steps it, the live nodes reporting at each step."""

    def __init__(self, clock: Any, nodes: _Nodes) -> None:
        self._clock, self._nodes = clock, nodes

    def __getattr__(self, name: str) -> Any:
        return getattr(self._clock, name)

    def advance(self, seconds: float) -> None:
        done = 0.0
        while done < seconds:
            dt = min(STEP_S, seconds - done)
            self._clock.advance(dt)
            self._nodes.heartbeat()
            done += dt


class NodeFaults:
    """``world.sim`` for test nodes: an ``offline`` fault makes the node announce offline and go quiet."""

    def __init__(self, world: Any, nodes: _Nodes) -> None:
        self._world, self._nodes = world, nodes

    def fault(self, node_id: str, kind: str) -> None:
        assert kind == "offline", kind
        if node_id in self._nodes.live:
            self._nodes.live.remove(node_id)
        self._world.node(node_id).publish_status("offline", "shutdown")

    def clear_fault(self, node_id: str, kind: str) -> None:
        assert kind == "offline", kind
        self._world.node(node_id).publish_status("online")
        if node_id not in self._nodes.live:
            self._nodes.live.append(node_id)
        self._nodes.report(node_id)


class EligibilityWorld(LedgerWorld):
    def __init__(self, world: Any, plan_id: str, projected: dict[str, Any], nodes: _Nodes) -> None:
        super().__init__(world, plan_id)
        self.projected = projected
        self.projected_id = projected["record_id"]
        self.nodes = nodes
        self.clock = LiveClock(world.clock, nodes)
        self.sim = NodeFaults(world, nodes)

    def projected_zone_quantity(self, zone: str) -> str:
        return self.projected["content"]["zone_quantities"][zone]["net_tco2e"]


async def covering(world: Any, zone: str) -> list[str]:
    cov = (await world.http.get("/api/v1/coverage")).json()
    z = next(c for c in cov["zones"] if c["zone_id"] == zone)
    return [*z["water"], *z["soil"]]


async def _bring_online(world: Any, node_ids: list[str]) -> _Nodes:
    nodes = _Nodes(world, node_ids)
    await asyncio.to_thread(nodes.heartbeat)  # connects (retained online status) and reports
    for n in node_ids:
        await world.wait_status(n, "online")
    # Past the fusion engine's per-zone telemetry throttle, so the zone is assessed with every node's readings.
    world.clock.advance(3)
    await asyncio.to_thread(nodes.heartbeat)
    return nodes


async def _plan(world: Any, zone: str) -> str:
    p = await propose_and_wait(world, [zone])
    r = await world.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": planting(zone)})
    assert r.status_code == 200, r.text
    return p["plan_id"]


async def _apply(world: Any, plan_id: str) -> None:
    async with world.events() as ev:
        r = await world.http.post(f"/api/v1/plans/{plan_id}/apply", json={})
        assert r.status_code == 200, r.text
        fid = r.json()["forecast_id"]
        e = await ev.wait_for("forecast.ready", lambda d: d["forecast_id"] == fid, timeout=FORECAST_TIMEOUT_S)
    assert e["data"]["status"] == "ready", e


async def _projected_world(world: Any, zone: str, monkeypatch: Any) -> EligibilityWorld:
    monkeypatch.setattr(world.gs.services.fusion, "_camera", _OnlineCamera())
    nodes = await _bring_online(world, await covering(world, zone))
    plan_id = await _plan(world, zone)
    install_cloud_fpe(world)  # after the planner ran: the forecast parameters come from the cloud tier
    await _apply(world, plan_id)
    lw = LedgerWorld(world, plan_id)
    rec = await create_projected(lw)
    w = EligibilityWorld(world, plan_id, rec, nodes)
    await settle(w)  # the sensor window starts now
    return w


@pytest.fixture
async def world_projected(world_ready: Any, monkeypatch: Any) -> AsyncIterator[EligibilityWorld]:
    yield await _projected_world(world_ready, "KSL-B3", monkeypatch)


@pytest.fixture
async def world_projected_uncovered_zone(
    world_ready: Any, monkeypatch: Any
) -> AsyncIterator[EligibilityWorld]:
    zone = "KSL-E5"
    assert await covering(world_ready, zone) == []
    r = await world_ready.http.post("/api/v1/nodes", json={"node_type": "soil_probe", "source": "simulated",
                                                            "position": {"e_m": 450.0, "s_m": 450.0}})  # fmt: skip
    assert r.status_code == 200, r.text
    temp = r.json()["node"]["id"]
    monkeypatch.setattr(world_ready.gs.services.fusion, "_camera", _OnlineCamera())
    plan_id = await _plan(world_ready, zone)
    await _apply(world_ready, plan_id)
    rec = await create_projected(LedgerWorld(world_ready, plan_id))
    r = await world_ready.http.post(f"/api/v1/nodes/{temp}/decommission", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert await covering(world_ready, zone) == []
    w = EligibilityWorld(world_ready, plan_id, rec, _Nodes(world_ready, []))
    await settle(w)
    yield w


@pytest.fixture
async def world_projected_rules_only_unlocked(world_applied_plan: Any) -> AsyncIterator[Any]:
    w = world_applied_plan
    rec = await create_projected(w)
    async with w.events() as ev:
        r = await w.http.post("/api/v1/test/seed/capture", json={
            "zone_metrics": {"KSL-B3": {"canopy_pct": FLAG_CANOPY_PCT}}, "evidence_grade": True,
            "quality": {"exposure_locked": False},
        })  # fmt: skip
        assert r.status_code == 201, r.text
        cap = r.json()
        await wait_count(
            ev, "zone.assessed", lambda d: d["zone_id"] == "KSL-B3" and d.get("capture_id") == cap["id"], 1, 15
        )
    w.projected_id = rec["record_id"]
    await settle(w)
    yield w


# ---- helpers ------------------------------------------------------------------------------------------
async def seed_recovery_capture(w: Any, zone: str, new_growth_pct: float = 4.0) -> dict[str, Any]:
    return await _seed_capture(w, {zone: {"canopy_pct": FLAG_CANOPY_PCT, "new_growth_pct": new_growth_pct}})


async def seed_three_recovery_captures(w: Any, zone: str, new_growth_pct: float = 4.0) -> list[dict[str, Any]]:
    return [await seed_recovery_capture(w, zone, new_growth_pct) for _ in range(3)]


async def settle(w: Any) -> list[dict[str, Any]]:
    """One evaluation now, on the Ground Station loop; returns the ZoneEligibility list as dicts."""
    ev = w.gs.services.eligibility
    out = await on_gs_loop(w, ev.evaluate)
    return [e.model_dump(mode="json") for e in out]


async def verified_records(w: Any) -> list[dict[str, Any]]:
    await settle(w)
    recs = (await w.http.get("/api/v1/ledger/records")).json()
    return [r for r in recs if r["type"] == "verified"]


async def eligibility(w: Any, zone: str) -> dict[str, Any]:
    await settle(w)
    r = await w.http.get("/api/v1/ledger/eligibility")
    assert r.status_code == 200, r.text
    found = [e for e in r.json() if e["zone_id"] == zone]
    assert len(found) == 1, r.json()
    return found[0]


async def pause_evaluations(w: Any) -> None:
    """Hold the evaluator's lock on the Ground Station loop: no evaluation runs until ``resume``."""
    lock = w.gs.services.eligibility._lock
    await on_gs_loop(w, lock.acquire)


async def resume_evaluations(w: Any) -> None:
    lock = w.gs.services.eligibility._lock

    async def release() -> None:
        lock.release()

    await on_gs_loop(w, release)
