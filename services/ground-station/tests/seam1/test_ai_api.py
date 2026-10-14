"""M4 Task 7: history, trees, AI status and call-log routes (seam 1, test-mode world: rules tier)."""

from __future__ import annotations

import json

from gs_assess import seed_flag, set_seeded_baseline


async def test_history_generated_once_after_first_baseline_with_label(world):
    await set_seeded_baseline(world)
    await world.wait_event("history.updated")
    body = (await world.http.get("/api/v1/history")).json()
    assert body["label"] == "AI-generated baseline — stand-in for the Sentinel-2 archive"
    assert [p["year"] for p in body["series"]["KSL-B3"]] == list(range(2016, 2026))


async def test_trees_locate_returns_202_then_points_event(world):
    await set_seeded_baseline(world, with_classes=True)
    assert (await world.http.post("/api/v1/trees/locate")).status_code == 202
    t = await world.wait_event("trees.updated")
    assert t["data"]["source"]["tier"] in ("robotics_er", "rules")


async def test_ai_calls_list_and_jsonl_export(world):
    await seed_flag(world, "KSL-B3")
    await world.wait_event("zone.assessed", lambda d: d["narrative"], timeout=15)
    calls = (await world.http.get("/api/v1/ai/calls")).json()
    assert calls and "inputs" not in calls[0]
    r = await world.http.get("/api/v1/ai/calls/export")
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert all("inputs" in json.loads(line) for line in r.text.strip().splitlines())


async def test_ai_status_shows_keys_by_slot_only(world):
    s = (await world.http.get("/api/v1/ai/status")).json()
    assert {k["slot"] for k in s["keys"]} <= {1, 2, 3} and "AQ." not in json.dumps(s)


async def test_history_real_points_regenerate_and_no_baseline_cases(world):
    empty = (await world.http.get("/api/v1/history")).json()
    assert empty["series"] == {} and empty["real"] == [] and empty["generation_id"] is None
    assert (await world.http.post("/api/v1/history/regenerate")).status_code == 409
    await set_seeded_baseline(world)
    first = (await world.wait_event("history.updated"))["data"]["generation_id"]
    assert (await world.http.post("/api/v1/history/regenerate")).status_code == 202
    second = (await world.wait_event("history.updated", lambda d: d["generation_id"] != first))["data"]
    body = (await world.http.get("/api/v1/history")).json()
    assert body["generation_id"] == second["generation_id"] and body["source"]["tier"] == "rules"
    assert {r["zone_id"] for r in body["real"]} == set(body["series"])
    assert body["real"][0]["canopy_pct"] == 60.0
    assert len(body["series"]["KSL-B3"]) == 10
    assert len(await world.rows("history_series", generation_id=first)) == 250


async def test_trees_are_stored_in_site_metres_with_zone(world):
    assert (await world.http.get("/api/v1/trees")).status_code == 404
    assert (await world.http.post("/api/v1/trees/locate")).status_code == 409
    await set_seeded_baseline(world, with_classes=True)
    # The seeded baseline's synthetic map is located automatically (ruling R22a): let that settle first.
    await world.wait_event("trees.updated", timeout=15)
    assert (await world.http.post("/api/v1/trees/locate")).status_code == 202
    # (the seeded baseline's synthetic class map is located too, ruling R22a: wait for this map's 6 trees)
    t = (await world.wait_event("trees.updated", lambda d: len(d["points"]) == 6))["data"]
    got = (await world.http.get("/api/v1/trees")).json()
    assert got["points"] and len(got["points"]) == len(t["points"]) == 6
    p = min(got["points"], key=lambda q: q["u_px"])  # canopy blob centred on x=80, y=60 of 512 px
    assert abs(p["u_px"] - 79.5) < 1 and abs(p["v_px"] - 59.5) < 1
    size = world.gs.services.site.site().size_m
    assert abs(p["e_m"] - 79.5 * size / 512) < 1 and p["zone_id"] == "KSL-A1"
    assert got["capture_id"] == t["capture_id"] and len(await world.rows("tree_points")) >= 1


async def test_history_regenerate_uses_a_fresh_seed_at_operator_priority(world):
    from bcs_gs.ai.roles.base import Priority

    gw = world.gs.services.ai
    seen: list[tuple[int, Priority]] = []
    orig = gw.call

    async def spy(role, inp, priority):
        if role.name == "history_synthesizer":
            seen.append((inp.seed, priority))
        return await orig(role, inp, priority)

    gw.call = spy
    try:
        await set_seeded_baseline(world)
        gens = {(await world.wait_event("history.updated"))["data"]["generation_id"]}
        for _ in range(2):
            assert (await world.http.post("/api/v1/history/regenerate")).status_code == 202
            ev = await world.wait_event("history.updated", lambda d, g=frozenset(gens): d["generation_id"] not in g)
            gens.add(ev["data"]["generation_id"])
    finally:
        del gw.call
    assert [p for _, p in seen] == [Priority.BACKGROUND, Priority.OPERATOR, Priority.OPERATOR]
    assert len({s for s, _ in seen}) == 3  # a regenerate never repeats the inputs, so never a cache hit
