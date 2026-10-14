"""M5: forecasts (Task 3) and restoration plans (Task 4) over HTTP (seam 1, test-mode world: rules tier)."""

from __future__ import annotations

import asyncio

from gs_assess import _seed_capture
from gs_forecast import install_cloud_fpe, on_gs_loop, propose_and_wait, run_and_wait, seed_varied


async def test_forecast_requires_evidence_grade_capture(world):  # Review Focus 3
    r = await world.http.post("/api/v1/forecasts", json={})
    assert r.status_code == 409 and "needs an evidence-grade capture" in r.json()["error"]["message"]


async def test_forecast_requires_baseline(world):  # Review Focus 3
    r = await world.http.post("/api/v1/test/seed/capture", json={"zone_metrics": {}, "evidence_grade": True})
    assert r.status_code == 201, r.text
    repo = world.gs.repo
    row = await asyncio.to_thread(repo.get, "captures", {"id": r.json()["id"]})
    await asyncio.to_thread(repo.upsert, "captures", {**row, "is_baseline": False, "retention_reason": None})
    r = await world.http.post("/api/v1/forecasts", json={})
    assert r.status_code == 409 and "needs a baseline" in r.json()["error"]["message"]


async def test_forecast_runs_and_is_deterministic_with_cached_params(world_ready):
    a = await run_and_wait(world_ready)
    b = await run_and_wait(world_ready)
    assert a["scenarios"] == b["scenarios"] and all(s["cached"] for s in b["parameter_sources"].values())
    assert b["summary"]["elapsed_ms"] <= 1000  # ruling R7


async def test_forecast_starts_from_latest_real_capture(world_ready):
    f = await run_and_wait(world_ready)
    latest = (await world_ready.http.get("/api/v1/captures/latest")).json()
    assert f["base_capture_id"] == latest["id"] and f["years"] == list(range(2026, 2036))


async def test_forecast_stored_with_keyframes_event_and_referenced_capture(world_ready):
    f = await run_and_wait(world_ready)
    assert f["plan_id"] is None and 0 < f["confidence_prediction"] <= 1
    assert set(f["parameter_sources"]) == set(f["scenarios"]["without"]["zones"])
    assert len(f["scenarios"]["with"]["site"]) == 10
    latest = (await world_ready.http.get("/api/v1/forecasts/latest")).json()
    assert latest["id"] == f["id"]
    row = (await world_ready.rows("forecasts", id=f["id"]))[0]
    zone_kf = next(iter(row["keyframes"]["without"]["zones"].values()))[0]
    assert "sigma" in zone_kf and "cohort_fraction" in zone_kf  # ruling R6
    assert row["input_hash"] and row["parameters"] and row["bands"]
    cap = (await world_ready.rows("captures", id=f["base_capture_id"]))[0]
    assert cap["retention_reason"] in ("referenced", "baseline")
    media = await world_ready.rows("media_objects")
    assert all(o["protected"] for o in media if f["base_capture_id"] in o["key"])


async def test_forecast_unknown_id_404_and_no_latest_404(world):
    assert (await world.http.get("/api/v1/forecasts/nope")).status_code == 404
    assert (await world.http.get("/api/v1/forecasts/latest")).status_code == 404


async def test_forecast_failure_marks_row_failed_and_emits_ready(world_ready, monkeypatch):
    import bcs_gs.forecast.service as fs

    def boom(*_a, **_k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(fs, "run_forecast", boom)
    f = await run_and_wait(world_ready, status="failed")
    assert "engine down" in f["summary"]["error"]
    assert (await world_ready.http.get("/api/v1/forecasts/latest")).status_code == 404  # ruling R18


async def test_forecast_latest_is_newest_ready_one(world_ready, monkeypatch):  # ruling R18
    import bcs_gs.forecast.service as fs

    ok = await run_and_wait(world_ready)
    monkeypatch.setattr(fs, "run_forecast", lambda *_a, **_k: 1 / 0)
    await run_and_wait(world_ready, status="failed")
    assert (await world_ready.http.get("/api/v1/forecasts/latest")).json()["id"] == ok["id"]


def _by_tier(f):
    out = {}
    for z, s in f["parameter_sources"].items():
        out.setdefault(s["tier"], set()).add(z)
    return out


async def test_forecast_caps_fresh_cloud_calls_per_run(world_ready):  # ruling R16
    await seed_varied(world_ready)
    cloud = install_cloud_fpe(world_ready)
    f = await run_and_wait(world_ready)
    tiers = _by_tier(f)
    assert cloud.calls == 4 and set(tiers) == {"gemini_primary", "rules"}
    assert len({f["parameter_sources"][z]["ai_call_id"] for z in tiers["gemini_primary"]}) == 4
    assert all(f["parameter_sources"][z]["ai_call_id"] is None for z in tiers["rules"])


async def test_forecast_parameter_deadline_falls_back_to_rules(world_ready, monkeypatch):  # rulings R16, R26
    import bcs_gs.forecast.service as fs

    assert fs.PARAM_DEADLINE_S == 18.0  # ruling R26: the spec's <= 20 s with fresh AI parameters
    monkeypatch.setattr(fs, "PARAM_DEADLINE_S", 0.3)
    install_cloud_fpe(world_ready, delay_s=10)
    f = await run_and_wait(world_ready)
    assert set(_by_tier(f)) == {"rules"} and f["summary"]["elapsed_ms"] < 5000


async def test_degraded_params_expire_after_10_min_and_cloud_params_persist(world_ready):  # ruling R17
    await seed_varied(world_ready)
    install_cloud_fpe(world_ready)
    first = await run_and_wait(world_ready)
    cloud_zones = _by_tier(first)["gemini_primary"]
    world_ready.clock.advance(5 * 60)
    second = await run_and_wait(world_ready)
    assert all(s["cached"] for s in second["parameter_sources"].values())
    world_ready.clock.advance(6 * 60)  # 11 min after the first run
    third = await run_and_wait(world_ready)
    fresh = {z for z, s in third["parameter_sources"].items() if not s["cached"]}
    assert fresh == set(third["parameter_sources"]) - cloud_zones and fresh


async def test_only_the_zone_whose_inputs_changed_is_refetched(world_ready):
    from gs_assess import FLAG_CANOPY_PCT, _seed_capture

    await run_and_wait(world_ready)
    await _seed_capture(
        world_ready, {"KSL-B3": {"canopy_pct": FLAG_CANOPY_PCT}, "KSL-C3": {"canopy_pct": 57.0}}
    )
    f = await run_and_wait(world_ready)
    assert {z for z, s in f["parameter_sources"].items() if not s["cached"]} == {"KSL-C3"}


def _new_service(svc):
    from bcs_gs.forecast.service import ForecastService

    return ForecastService(
        repo=svc.repo, bus=svc.bus, clock=svc.clock, settings=svc.settings, site=svc.site,
        captures=svc.capture, fusion=svc.fusion, gateway=svc.ai,
    )  # fmt: skip


async def test_persisted_params_reused_by_a_new_service_instance(world_ready):
    await run_and_wait(world_ready)
    svc = world_ready.gs.services
    other = await asyncio.to_thread(_new_service, svc)  # as after a restart: an empty in-memory cache
    async with world_ready.events() as ev:
        fid = await on_gs_loop(world_ready, lambda: other.start(None))
        await ev.wait_for("forecast.ready", lambda d: d["forecast_id"] == fid, timeout=30)
    f = (await world_ready.http.get(f"/api/v1/forecasts/{fid}")).json()
    assert f["status"] == "ready" and all(s["cached"] for s in f["parameter_sources"].values())
    await on_gs_loop(world_ready, other.stop)


async def test_stale_pending_forecast_marked_failed_on_startup(world_ready):
    svc = world_ready.gs.services
    latest = (await world_ready.http.get("/api/v1/captures/latest")).json()
    row = {
        "id": "stale-1", "created_at": "2026-10-01T00:00:00.000Z", "status": "pending", "plan_version_id": None,
        "base_capture_id": latest["id"], "input_hash": "", "parameters": {}, "parameter_sources": {},
        "keyframes": {}, "summary": {}, "bands": {},
    }  # fmt: skip
    await asyncio.to_thread(svc.repo.insert, "forecasts", row)
    await asyncio.to_thread(_new_service, svc)
    f = (await world_ready.http.get("/api/v1/forecasts/stale-1")).json()
    assert f["status"] == "failed" and "interrupted" in f["summary"]["error"]


# ---- restoration plans (Task 4) -------------------------------------------------------------------
UPLIFT = {"canopy_pp_2035": 0.0, "tco2e_2035": 0.0}
EDITED = [
    {"zone_id": "KSL-B3", "interventions": [{"kind": "plant_rhizophora", "sapling_count": 880}, {"kind": "silt_fence"}],
     "priority": 1, "rationale": "operator edit", "expected_uplift": UPLIFT},
]  # fmt: skip
NO_MUD = {"canopy_pct": 95.0, "water_pct": 0.0, "mud_pct": 0.0, "other_pct": 5.0}


async def test_edit_after_apply_creates_new_version(world_ready):  # Review Focus 4
    p = await propose_and_wait(world_ready)
    await world_ready.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={})
    v2 = (await world_ready.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": EDITED})).json()
    assert v2["version"] == 2 and v2["status"] == "draft" and v2["source"] == "mixed"
    v1 = (await world_ready.http.get(f"/api/v1/plans/{p['plan_id']}", params={"version": 1})).json()
    assert v1["status"] == "applied"  # superseded only once the new version is applied
    await world_ready.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={"version": 2})
    v1 = (await world_ready.http.get(f"/api/v1/plans/{p['plan_id']}", params={"version": 1})).json()
    assert v1["status"] == "superseded"
    v2 = (await world_ready.http.get(f"/api/v1/plans/{p['plan_id']}")).json()
    assert v2["version"] == 2 and v2["status"] == "applied"
    assert v2["items"][0]["interventions"][0]["planted_area_ha"] == 0.2  # 880 / 4,400
    v3 = (await world_ready.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": EDITED})).json()
    assert v3["version"] == 3 and v3["source"] == "mixed"


async def test_apply_triggers_forecast_and_records_capture(world_ready):
    p = await propose_and_wait(world_ready)
    r = (await world_ready.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={})).json()
    assert r["plan"]["capture_at_application_id"] and r["forecast_id"]
    f = await world_ready.wait_event(
        "forecast.ready", lambda d: d["forecast_id"] == r["forecast_id"], timeout=30
    )
    assert f["data"]["status"] == "ready" and f["data"]["plan_id"] == p["plan_id"]
    plan = r["plan"]
    assert plan["status"] == "applied" and plan["applied_at"] and plan["forecast_id"] == r["forecast_id"]
    cap = (await world_ready.rows("captures", id=plan["capture_at_application_id"]))[0]
    latest = (await world_ready.http.get("/api/v1/captures/latest")).json()
    assert cap["id"] == latest["id"] and cap["retention_reason"] == "plan_application"  # H7
    fc = (await world_ready.http.get(f"/api/v1/forecasts/{r['forecast_id']}")).json()
    assert fc["plan_id"] == p["plan_id"] and fc["plan_version"] == 1


async def test_apply_again_is_safe_and_starts_a_new_forecast(world_ready):  # Review Focus 4
    p = await propose_and_wait(world_ready)
    a = (await world_ready.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={})).json()
    b = (await world_ready.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={"version": 1})).json()
    assert b["plan"]["status"] == "applied" and b["forecast_id"] != a["forecast_id"]
    assert b["plan"]["applied_at"] == a["plan"]["applied_at"]
    rows = await world_ready.rows("restoration_plans", plan_id=p["plan_id"])
    assert [(x["version"], x["status"]) for x in rows] == [(1, "applied")]


async def test_plan_updated_events_carry_the_summary(world_ready):
    async with world_ready.events() as ev:
        p = await propose_and_wait(world_ready)
        await world_ready.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": EDITED})
        await world_ready.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={})
        await ev.wait_for("plan.updated", lambda d: d["plan_id"] == p["plan_id"] and d["status"] == "applied")
        events = ev.all("plan.updated")
    assert [(e["data"]["version"], e["data"]["status"]) for e in events] == [
        (1, "draft"),
        (2, "draft"),
        (2, "applied"),
    ]
    assert events[1]["data"]["zones"] == ["KSL-B3"] and events[1]["data"]["source"] == "mixed"


async def test_update_rejects_planting_without_mud_and_plan_stays_editable(world_ready):  # Review Focus 2
    await _seed_capture(world_ready, {"KSL-A1": NO_MUD})
    p = await propose_and_wait(world_ready)
    bad = [{**EDITED[0], "zone_id": "KSL-A1"}]
    r = await world_ready.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": bad})
    assert (
        r.status_code == 422
        and "planting needs mud or an eroded edge in KSL-A1" in r.json()["error"]["message"]
    )
    rows = await world_ready.rows("restoration_plans", plan_id=p["plan_id"])
    assert [(x["version"], x["status"]) for x in rows] == [(1, "draft")]
    ok = await world_ready.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": EDITED})
    assert ok.status_code == 200 and ok.json()["version"] == 2


async def test_update_switches_species_above_40_psu_with_a_warning(
    world_ready, monkeypatch
):  # Review Focus 2
    from bcs_gs.restoration.catalogue import ZonePlanState

    svc = world_ready.gs.services.plans
    real = svc.zone_states

    def salty():
        s = real()
        b3 = s["KSL-B3"]
        return {**s, "KSL-B3": ZonePlanState(mud=b3.mud, porewater_psu=46.0, eroded=b3.eroded)}

    monkeypatch.setattr(svc, "zone_states", salty)
    p = await propose_and_wait(world_ready)
    v2 = (await world_ready.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": EDITED})).json()
    assert v2["items"][0]["interventions"][0]["kind"] == "plant_avicennia"
    assert v2["warnings"] == ["switched to Avicennia marina: porewater > 40 PSU"]
    got = (await world_ready.http.get(f"/api/v1/plans/{p['plan_id']}", params={"version": 2})).json()
    assert got["warnings"] == v2["warnings"]


async def test_ai_draft_drops_invalid_planting_with_a_warning(world_ready, monkeypatch):
    from bcs_gs.ai.roles.restoration_planner import PlannerOutput, RestorationPlanner
    from bcs_gs.api.models import PlanItem

    await _seed_capture(world_ready, {"KSL-A1": NO_MUD})
    items = [PlanItem.model_validate({**EDITED[0], "zone_id": "KSL-A1"}), PlanItem.model_validate(EDITED[0])]
    monkeypatch.setattr(RestorationPlanner, "rules", lambda self, inp: PlannerOutput(items=items))
    p = await propose_and_wait(world_ready)
    assert [(i["zone_id"], [iv["kind"] for iv in i["interventions"]]) for i in p["items"]] == [
        ("KSL-A1", ["silt_fence"]), ("KSL-B3", ["plant_rhizophora", "silt_fence"])
    ]  # fmt: skip
    assert p["warnings"] == [
        "dropped plant_rhizophora in KSL-A1: planting needs mud or an eroded edge in KSL-A1"
    ]
    assert p["ai"]["tier"] == "rules"


async def test_apply_without_capture_is_409_and_changes_nothing(world):  # Review Focus 3
    p = await propose_and_wait(world)
    r = await world.http.post(f"/api/v1/plans/{p['plan_id']}/apply", json={})
    assert r.status_code == 409 and "needs an evidence-grade capture" in r.json()["error"]["message"]
    rows = await world.rows("restoration_plans", plan_id=p["plan_id"])
    assert [(x["status"], x["applied_at"], x["forecast_id"]) for x in rows] == [("draft", None, None)]


async def test_plan_list_get_and_unknowns(world_ready):
    a = await propose_and_wait(world_ready)
    b = await propose_and_wait(world_ready, ["KSL-B3"])
    await world_ready.http.put(f"/api/v1/plans/{a['plan_id']}", json={"items": EDITED})
    listed = (await world_ready.http.get("/api/v1/plans")).json()
    assert [(x["plan_id"], x["version"]) for x in listed] == [(a["plan_id"], 2), (b["plan_id"], 1)]
    assert (await world_ready.http.get("/api/v1/plans/nope")).status_code == 404
    assert (
        await world_ready.http.get(f"/api/v1/plans/{a['plan_id']}", params={"version": 9})
    ).status_code == 404
    assert (await world_ready.http.put("/api/v1/plans/nope", json={"items": EDITED})).status_code == 404
    assert (await world_ready.http.post("/api/v1/plans/nope/apply", json={})).status_code == 404
    r = await world_ready.http.post("/api/v1/plans/propose", json={"zone_ids": ["KSL-Z9"]})
    assert r.status_code == 422 and "KSL-Z9" in r.json()["error"]["message"]


async def test_plan_routes_round_trip(world_ready):
    async with world_ready.events() as ev:
        r = await world_ready.http.post("/api/v1/plans/propose", json={})
        assert r.status_code == 202
        plan_id = r.json()["request_id"]
        p = await ev.wait_for("plan.updated", lambda d: d["plan_id"] == plan_id, timeout=30)
    plans = (await world_ready.http.get("/api/v1/plans")).json()
    assert plans[0]["plan_id"] == p["data"]["plan_id"] and plans[0]["status"] == "draft"


async def test_forecast_latest_and_illustrations_listing(world_ready):
    from gs_forecast import wait_all_illustrations

    f = await run_and_wait(world_ready)
    assert (await world_ready.http.get("/api/v1/forecasts/latest")).json()["id"] == f["id"]
    await wait_all_illustrations(world_ready, f["id"])
    rows = (await world_ready.http.get(f"/api/v1/forecasts/{f['id']}/illustrations")).json()
    assert len(rows) == 4 and all((r["url"] is not None) == (r["status"] == "ready") for r in rows)
    assert (await world_ready.http.get("/api/v1/forecasts/nope/illustrations")).status_code == 404


async def test_illustration_media_404_unless_ready(world_ready):
    assert (await world_ready.http.get("/api/v1/media/illustrations/nope.jpg")).status_code == 404


async def test_reset_cancels_an_in_flight_forecast(world_ready):  # ruling R30 (#5, #6)
    from gs_forecast import start_forecast

    install_cloud_fpe(world_ready, delay_s=1.0)  # the run waits on its parameter fetches for 1 s
    svc = world_ready.gs.services
    async with world_ready.events() as ev:
        fid = await start_forecast(world_ready)

        async def fetching() -> bool:
            return any(t.get_name().startswith("forecast-fpe-") for t in asyncio.all_tasks())

        for _ in range(100):
            if await on_gs_loop(world_ready, fetching):
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("the forecast never started its parameter fetches")
        assert (await world_ready.http.post("/api/v1/test/reset")).status_code == 200
        await asyncio.sleep(2.5)  # uncancelled, the run would have stored its row and published by now
        assert not [e for e in ev.all("forecast.ready") if e["data"]["forecast_id"] == fid]
    rows = await asyncio.to_thread(svc.repo.query, "SELECT id FROM forecasts", table="forecasts")
    assert rows == []
    assert (await world_ready.http.get(f"/api/v1/forecasts/{fid}")).status_code == 404
    assert not await on_gs_loop(world_ready, fetching)  # no orphaned fetch outlives the run
    assert not svc.forecasts._bg


async def test_reset_cancels_fusion_trees_and_tasking_work(world_ready):  # M5 follow-up (R30 extended)
    svc = world_ready.gs.services

    async def plant() -> list[asyncio.Task]:
        tasks = []
        for owner, name in ((svc.fusion, "fusion-ai-test"), (svc.trees, "trees-locate-test")):
            t = asyncio.create_task(asyncio.sleep(60), name=name)
            owner._bg.add(t)
            tasks.append(t)
        tasks.append(svc.tasking._bg[1])  # the ticker: in-flight tasking work
        return tasks

    planted = await on_gs_loop(world_ready, plant)
    assert (await world_ready.http.post("/api/v1/test/reset")).status_code == 200

    async def state() -> tuple[list[bool], int, int, list[bool]]:
        alive = [not t.done() for t in svc.tasking._bg]
        return [t.cancelled() for t in planted], len(svc.fusion._bg), len(svc.trees._bg), alive

    cancelled, fusion_bg, trees_bg, alive = await on_gs_loop(world_ready, state)
    assert cancelled == [True, True, True]  # the old fusion, trees and tasking tasks were cancelled
    assert fusion_bg == 0 and trees_bg == 0
    assert alive == [True, True]  # tasking keeps listening and ticking after the reset
