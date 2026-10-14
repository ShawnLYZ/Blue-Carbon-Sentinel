"""FusionRiskEngine at the Ground Station boundary (M4 Task 5): rules tier, seeded metrics, simulated telemetry."""

from __future__ import annotations

from gs_assess import seed_flag, seed_healthy_baseline


async def test_flagged_zone_gets_assessment_with_narrative_and_source_chip(world):
    await seed_flag(world, "KSL-B3")
    a = await world.wait_event(
        "zone.assessed", lambda d: d["zone_id"] == "KSL-B3" and d["narrative"], timeout=15
    )
    assert a["data"]["source"]["tier"] == "rules"
    assert a["data"]["risk_class"] in ("low", "medium", "high", "critical")
    assert set(a["data"]["confidence"]) == {"camera", "sensor", "prediction", "overall"}
    # Seeded captures carry a synthetic JPEG (ruling R22a), so VisionAnalyst may run: the field is a list.
    assert isinstance(a["data"]["observations"], list)
    # M4 ruling: VisionAnalyst observations are stored with their own source chip. The test world runs the
    # rules tier only, so that chip is rules/no model/uncached, with the vision call's own ai_call_id.
    obs_src = a["data"]["observations_source"]
    assert obs_src is not None
    assert (obs_src["tier"], obs_src["model"], obs_src["cached"]) == ("rules", None, False)
    assert obs_src["ai_call_id"] and obs_src["ai_call_id"] != a["data"]["source"]["ai_call_id"]
    stored = (await world.http.get("/api/v1/zones/KSL-B3/assessments?limit=1")).json()[0]
    assert isinstance(stored["observations"], list)
    assert stored["observations_source"] == obs_src


async def test_assessment_with_rules_when_offline(world_offline_ai):  # Review Focus 3
    await seed_flag(world_offline_ai, "KSL-B3")
    a = await world_offline_ai.wait_event(
        "zone.assessed", lambda d: d["zone_id"] == "KSL-B3" and d["narrative"], timeout=15
    )
    assert a["data"]["source"]["tier"] == "rules"


async def test_early_warning_from_salt_scenario_with_healthy_canopy(world_with_sim):
    await seed_healthy_baseline(world_with_sim)
    # Ruling (Task 5, N5 per-sample reading): salt intrusion alone never reaches a 0.5 composite, so as in
    # early-warning-salt.yaml SP-02's porewater salinity is also forced up, here to 58 PSU (stress 0.54):
    # sub-canopy stress still below the node's 60 PSU critical band, so no node threshold anomaly opens a
    # node_anomaly task first. Run long enough at the 30 s baseline interval for SP-02's robust value to
    # rise and for 2 baseline evaluations.
    world_with_sim.sim.apply("B3", "salt_intrusion", ramp_s=1)
    world_with_sim.sim.set_value("SP-02", "porewater_salinity_psu", 58.0)
    world_with_sim.run_for(seconds=150)
    ew = await world_with_sim.wait_event("zone.assessed", lambda d: d["early_warning"] is True, timeout=30)
    assert ew["data"]["stressors"]["vegetation"] < 0.2
    tasks = (await world_with_sim.http.get("/api/v1/tasks", params={"status": "all"})).json()
    assert any(t["trigger"] == "early_warning" for t in tasks)


async def test_operator_analysis_rate_limited_per_zone(world):
    assert (await world.http.post("/api/v1/zones/KSL-B3/analyze")).status_code == 202
    assert (await world.http.post("/api/v1/zones/KSL-B3/analyze")).status_code == 429


async def test_zone_without_coverage_or_baseline_has_no_assessment(world):
    assert (await world.http.get("/api/v1/zones/KSL-E5/assessments")).json() == []


async def test_code_only_assessment_comes_first_and_ai_follows_and_is_stored(world):
    cap = await seed_flag(world, "KSL-B3")
    ai = await world.wait_event(
        "zone.assessed", lambda d: d["zone_id"] == "KSL-B3" and d["narrative"], timeout=15
    )
    b3 = [
        e["data"]
        for e in world.recorder.items
        if e["type"] == "zone.assessed"
        and e["data"]["zone_id"] == "KSL-B3"
        and e["data"]["capture_id"] == cap["id"]
    ]
    assert b3[0]["narrative"] == "" and b3[0]["stressors"]["vegetation"] == 0.5  # 15 pp loss / 30
    assert b3[0]["stressors"]["salinity"] is None  # no telemetry yet: unmeasured, weight renormalised
    assert ai["data"]["weights"] == {"vegetation": 1.0} and ai["data"]["multipliers"] == {"vegetation": 1.0}
    stored = (await world.http.get("/api/v1/zones/KSL-B3/assessments")).json()
    assert stored[0]["id"] == ai["data"]["id"] and stored[0]["source"]["ai_call_id"]
    assert (await world.http.get("/api/v1/zones/KSL-Z9/assessments")).status_code == 404


def test_observations_of_keeps_only_the_zones_own_and_round_trips_through_the_row():
    from types import SimpleNamespace as NS

    from bcs_gs.api import models as m
    from bcs_gs.fusion.engine import _from_row, _to_row, observations_of

    obs = [
        NS(zone_id="KSL-B3", kind="dieback", confidence=0.8, text="Canopy thinning"),
        NS(zone_id="KSL-C3", kind="clearing", confidence=0.6, text="Cleared strip"),
    ]
    chip = m.SourceChip(tier="gemma_local", model="gemma4", cached=False)
    mine, src = observations_of("KSL-B3", obs, chip)
    assert [(o.kind, o.confidence, o.text) for o in mine] == [("dieback", 0.8, "Canopy thinning")]
    assert src == chip

    a = m.Assessment(
        id="a1", zone_id="KSL-B3", at="2026-10-12T02:00:00Z", stressors={"vegetation": 0.5}, multipliers={},
        weights={}, risk_score=40.0, risk_class="medium",
        confidence=m.Confidence(camera=0.5, sensor=0.5, prediction=0.5, overall=0.5), early_warning=False,
        narrative="n", root_causes=[], actions=[], source=m.SourceChip(tier="rules", cached=False),
        observations=mine, observations_source=src,
    )
    back = _from_row(_to_row(a))
    assert back.observations == mine and back.observations_source == chip
    legacy = _to_row(a) | {"observations": None}  # rows written before migration 3
    assert _from_row(legacy).observations == []


async def _interpretations(world) -> int:
    """RiskInterpreter calls answered so far (one rules success per interpretation in test mode)."""
    rows = await world.rows("ai_calls", role="risk_interpreter", status="success")
    return len(rows)


async def test_zone_that_stays_flagged_is_interpreted_once_per_flag_set(world):  # no AI per capture
    import asyncio

    from gs_assess import _seed_capture

    await seed_flag(world, "KSL-B3")
    await world.wait_event("zone.assessed", lambda d: d["zone_id"] == "KSL-B3" and d["narrative"], timeout=15)
    world.clock.advance(5)
    await seed_flag(world, "KSL-B3")  # the next capture: same zone, same flag kinds
    await asyncio.sleep(1.0)
    assert await _interpretations(world) == 1
    # a changed flag set (canopy loss + dieback) starts a new interpretation, once the minimum interval passed
    world.clock.advance(31)
    cap = await _seed_capture(world, {"KSL-B3": {"canopy_pct": 45.0, "dieback_pct": 20.0}})
    assert {f["kind"] for z in cap["zone_metrics"] if z["zone_id"] == "KSL-B3" for f in z["flags"]} == {
        "canopy_loss", "dieback",
    }  # fmt: skip
    for _ in range(50):
        if await _interpretations(world) == 2:
            break
        await asyncio.sleep(0.1)
    assert await _interpretations(world) == 2
    # the operator's analysis still runs (its own 30 s rule)
    assert (await world.http.post("/api/v1/zones/KSL-B3/analyze")).status_code == 202
    for _ in range(50):
        if await _interpretations(world) == 3:
            break
        await asyncio.sleep(0.1)
    assert await _interpretations(world) == 3
