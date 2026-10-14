"""M6 Task 4: the four-rule eligibility tracker and automatic per-zone Verified records."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bcs_gs.api.errors import ApiError
from bcs_gs.ledger.eligibility import SensorWindow, camera_rule
from bcs_gs.vegetation.metrics import ZoneMetricsRow
from gs_eligibility import (
    eligibility,
    pause_evaluations,
    resume_evaluations,
    seed_recovery_capture,
    seed_three_recovery_captures,
    settle,
    verified_records,
)

LABEL = "Demo record — not a certified carbon credit"
METHOD = "aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified"


async def test_verified_issued_only_when_all_four_rules_pass(world_projected):
    w = world_projected                                     # plan applied in KSL-B3, Projected record exists, covering SP healthy
    for i in range(2): await seed_recovery_capture(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(120); assert not await verified_records(w)                      # 2/3 captures
    await seed_recovery_capture(w, "KSL-B3", new_growth_pct=4.0); w.clock.advance(1)
    rec = (await verified_records(w))[0]
    assert rec["content"]["projected_record_id"] == w.projected_id and Decimal(rec["content"]["verification_ratio"]) <= 1


async def test_sensor_window_resets_on_offline(world_projected):                                  # Review Focus 3
    w = world_projected; await seed_three_recovery_captures(w, "KSL-B3")
    w.clock.advance(110); w.sim.fault("SP-01", "offline"); await settle(w); w.sim.clear_fault("SP-01", "offline"); w.clock.advance(60)
    e = await eligibility(w, "KSL-B3")
    assert e["sensors"]["ok"] is False and e["sensors"]["healthy_s"] < 120 and not await verified_records(w)
    assert "SP-01" in e["sensors"]["reason"]  # the eligibility card says why the window restarted


async def test_no_coverage_fails_sensor_rule_with_gap(world_projected_uncovered_zone):            # Review Focus 4
    e = await eligibility(world_projected_uncovered_zone, "KSL-E5")
    assert e["sensors"]["reason"] == "no coverage" and e["eligible"] is False
    assert any(g["zone_id"] == "KSL-E5" for g in (await world_projected_uncovered_zone.http.get("/api/v1/coverage")).json()["gaps"])


async def test_low_confidence_blocks_verified(world_projected_rules_only_unlocked):
    e = await eligibility(world_projected_rules_only_unlocked, "KSL-B3"); assert e["confidence"]["ok"] is False


async def test_ratio_capped_at_one_and_quantity_scaled(world_projected):
    w = world_projected; await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=50.0); w.clock.advance(121)
    rec = (await verified_records(w))[0]["content"]
    assert rec["verification_ratio"] == "1.0000" and rec["quantity_tco2e"] == w.projected_zone_quantity("KSL-B3")


# ---- beyond the brief: record content, at most one per (Projected, zone), the chain rule -------------
async def test_verified_record_content_and_at_most_one_per_zone(world_projected):
    w = world_projected
    e = await eligibility(w, "KSL-B3")
    assert e["plan_id"] == w.plan_id and e["camera"] == {"have": 0, "need": 3, "ok": False}
    assert e["sensors"]["need_s"] == 120 and e["confidence"]["need"] == 0.8 and e["chain"] == {"ok": True}
    caps = await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    (rec,) = await verified_records(w)
    c = rec["content"]
    assert rec["type"] == "verified" and c["zone_ids"] == ["KSL-B3"] and c["type"] == "verified"
    assert c["label"] == LABEL and c["method_note"] == METHOD
    assert c["demo_time_scale"] is True and c["period"] == w.projected["content"]["period"]
    assert re.fullmatch(r"[01]\.\d{4}", c["verification_ratio"]) and re.fullmatch(r"\d+\.\d{3}", c["quantity_tco2e"])
    net = Decimal(w.projected_zone_quantity("KSL-B3"))
    assert Decimal(c["quantity_tco2e"]) == (net * Decimal(c["verification_ratio"])).quantize(Decimal("0.001"))
    v = c["verification"]
    assert Decimal(v["observed_pp"]) == Decimal("4.00") and Decimal(v["expected_pp"]) >= 1
    ev = c["evidence"]
    assert ev["telemetry_window"]["simulated"] is True and ev["telemetry_window"]["node_ids"]
    assert [x["id"] for x in ev["captures"] if x["role"] == "qualifying"] == [x["id"] for x in caps]
    assert any(x["role"] == "application" for x in ev["captures"])
    assert Decimal(c["confidence"]["overall"]) >= Decimal("0.8")
    # more recovery and time, then a restart of the evaluator's memory: still one record for the zone
    await seed_recovery_capture(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(30)
    w.gs.services.eligibility.reset()
    w.clock.advance(130)
    assert len(await verified_records(w)) == 1


async def test_tampered_chain_blocks_verified_after_restart(world_projected):  # rule 4 is a real verification
    w = world_projected
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.tamper(chain_index=0)  # the Projected record's row edited in SQLite
    w.ledger.reset()  # as after a restart: the in-memory issuance_blocked flag is gone, the edited row stays
    w.clock.advance(121)
    assert not await verified_records(w)
    alerts = (await w.http.get("/api/v1/alerts")).json()
    assert any(a["type"] == "chain_broken" for a in alerts)
    assert (await eligibility(w, "KSL-B3"))["chain"]["ok"] is False


# ---- pure rules --------------------------------------------------------------------------------------
def _zm(canopy: float, new_growth: float = 0.0) -> ZoneMetricsRow:
    return ZoneMetricsRow(zone_id="KSL-B3", canopy_pct=canopy, water_pct=20.0, mud_pct=15.0, other_pct=5.0,
                          dieback_pct=0.0, new_growth_pct=new_growth)  # fmt: skip


def test_camera_rule_counts_the_trailing_run_of_recovery():
    app = _zm(45.0)
    assert camera_rule([], app) == (0, False)
    assert camera_rule([_zm(45.0, 3.0), _zm(50.0), _zm(45.0, 3.5)], app) == (3, True)  # 3 % new growth or +5 pp
    assert camera_rule([_zm(45.0, 4.0), _zm(45.0, 4.0), _zm(45.0, 2.9)], app) == (0, False)  # the run broke
    assert camera_rule([_zm(45.0), _zm(49.9, 2.9), _zm(46.0, 3.0), _zm(45.0, 9.0)], app) == (2, False)
    assert camera_rule([_zm(60.0)] * 5, app) == (3, True)


def test_sensor_window_rule():
    t = datetime(2026, 10, 16, tzinfo=UTC)
    w = SensorWindow(120)
    ok = {"SP-01": {"porewater_salinity": 0.0}}
    assert w.observe(t, {}, [], {}).reason == "no coverage"
    s = w.observe(t, ok, ["SP-01"], {"SP-01": True})
    assert (s.healthy_s, s.ok) == (0, False)
    s = w.observe(t + timedelta(seconds=110), ok, ["SP-01"], {"SP-01": True})
    assert (s.healthy_s, s.ok) == (110, False)
    s = w.observe(t + timedelta(seconds=111), {"SP-01": {"porewater_salinity": 0.3}}, ["SP-01"], {"SP-01": True})
    assert (s.healthy_s, s.ok) == (0, False) and "porewater_salinity" in s.reason  # >= 0.3 resets
    s = w.observe(t + timedelta(seconds=112), ok, ["SP-01"], {"SP-01": True})
    s = w.observe(t + timedelta(seconds=232), ok, ["SP-01"], {"SP-01": True})
    assert (s.healthy_s, s.ok, s.reason) == (120, True, None)
    s = w.observe(t + timedelta(seconds=233), ok, ["SP-01"], {"SP-01": False})
    assert (s.healthy_s, s.ok) == (0, False) and "SP-01" in s.reason and "offline" in s.reason
    s = w.observe(t + timedelta(seconds=234), ok, ["SP-01"], {"SP-01": True})
    s = w.observe(t + timedelta(seconds=300), ok, ["SP-01"], {"SP-01": True})
    assert s.healthy_s == 66
    s = w.observe(t + timedelta(seconds=301), ok, ["SP-01"], {"SP-01": True}, went_offline=["SP-01"])
    assert (s.healthy_s, s.ok) == (0, False) and s.reason == "SP-01 went offline"  # offline and back between


# ---- review fixes ----------------------------------------------------------------------------------
async def test_sensor_window_resets_on_a_quick_offline_online_flip(world_projected):  # N8, Review Focus 3
    w = world_projected; await seed_three_recovery_captures(w, "KSL-B3")
    w.clock.advance(110)
    await pause_evaluations(w)  # the flip falls between two evaluations
    w.sim.fault("SP-01", "offline"); w.sim.clear_fault("SP-01", "offline")
    await resume_evaluations(w)
    w.clock.advance(60)
    e = await eligibility(w, "KSL-B3")
    assert e["sensors"]["ok"] is False and e["sensors"]["healthy_s"] < 120 and not await verified_records(w)
    assert "SP-01" in e["sensors"]["reason"]


async def test_missing_expected_recovery_blocks_issuance(world_projected, monkeypatch):  # A6: no floor stand-in
    w = world_projected
    svc = w.gs.services

    def unreadable(forecast_id):
        raise ApiError("not_found", 404, f"No forecast {forecast_id}.")

    monkeypatch.setattr(svc.forecasts, "get", unreadable)
    svc.eligibility.reset()  # forget the expected recovery read while the forecast was readable
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    e = await eligibility(w, "KSL-B3")
    assert e["camera"]["ok"] and e["sensors"]["ok"] and e["confidence"]["ok"] and e["chain"]["ok"], e
    assert e["eligible"] is False and not await verified_records(w)
    assert "expected recovery" in svc.eligibility.blocked[(w.projected_id, "KSL-B3")]


async def test_reset_stops_the_evaluator_until_the_store_is_cleared(world_projected_uncovered_zone, monkeypatch):
    from bcs_gs.api import routes_test

    w = world_projected_uncovered_zone
    svc = w.gs.services
    assert "KSL-E5" in svc.tasking.zones_needing()  # the evaluator noted the gap (a write it makes)
    seen: dict[str, bool] = {}
    real = routes_test.reset_store

    def reset_store(s):
        seen["evaluator_live_during_reset"] = any(not t.done() for t in s.eligibility._tasks)
        real(s)

    monkeypatch.setattr(routes_test, "reset_store", reset_store)
    assert (await w.http.post("/api/v1/test/reset")).status_code == 200
    assert seen == {"evaluator_live_during_reset": False}  # nothing evaluates (or writes) mid-reset
    assert any(not t.done() for t in svc.eligibility._tasks)  # running again afterwards
    w.gs.clock.advance(3)
    assert await settle(w) == []
    assert "KSL-E5" not in svc.tasking.zones_needing()
    assert not await w.rows("settings", key="tasking.zones_needing") or \
        "KSL-E5" not in (await w.rows("settings", key="tasking.zones_needing"))[0]["value"]
    assert (await w.http.get("/api/v1/ledger/records")).json() == []


# ---- final review ------------------------------------------------------------------------------------
async def test_reapplied_plan_does_not_verify_a_zone_twice(world_projected):  # ruling: one per (plan, zone)
    from gs_eligibility import _apply, planting
    from gs_ledger import create_projected

    w = world_projected
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    (first,) = await verified_records(w)
    total = (await w.http.get("/api/v1/carbon/summary")).json()["verified_tco2e"]
    assert total > 0
    r = await w.http.put(f"/api/v1/plans/{w.plan_id}", json={"items": planting("KSL-B3")})
    assert r.status_code == 200, r.text
    await _apply(w, w.plan_id)
    v2 = await create_projected(w)
    assert v2["record_id"] != w.projected_id
    assert v2["content"]["evidence"]["plan_version"] > w.projected["content"]["evidence"]["plan_version"]
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    e = await eligibility(w, "KSL-B3")
    assert e["camera"]["ok"] and e["sensors"]["ok"] and e["confidence"]["ok"] and e["chain"]["ok"], e
    assert [x["record_id"] for x in await verified_records(w)] == [first["record_id"]]
    assert first["record_id"] in (e["reason"] or "")
    assert (await w.http.get("/api/v1/carbon/summary")).json()["verified_tco2e"] == total


async def test_verified_record_carries_the_projected_ai_provenance(world_projected):
    w = world_projected
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    (rec,) = await verified_records(w)
    ev, pev = rec["content"]["evidence"], w.projected["content"]["evidence"]
    assert ev["ai_calls"] == pev["ai_calls"] and ev["ai_calls"]
    assert (ev["forecast_id"], ev["plan_id"], ev["plan_version"]) == \
        (pev["forecast_id"], pev["plan_id"], pev["plan_version"])  # fmt: skip


async def test_eligibility_reason_carries_other_blocking_reasons(world_projected, monkeypatch):
    w = world_projected
    assert (await eligibility(w, "KSL-B3"))["reason"] is None
    svc = w.gs.services

    def unreadable(forecast_id):
        raise ApiError("not_found", 404, f"No forecast {forecast_id}.")

    monkeypatch.setattr(svc.forecasts, "get", unreadable)
    svc.eligibility.reset()
    assert "expected recovery unavailable" in (await eligibility(w, "KSL-B3"))["reason"]


async def test_issuance_failure_backs_off(world_projected, monkeypatch):
    import asyncio

    w = world_projected
    ev = w.gs.services.eligibility
    calls: list[str] = []

    def boom(z):
        calls.append(z.zone)
        raise RuntimeError("cannot build the Verified content")

    monkeypatch.setattr(ev, "_verified_content", boom)
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    await settle(w)  # the failure stays inside the evaluator
    await asyncio.sleep(1.0)  # the ledger.verified events of the failed attempt wake the evaluator
    await settle(w)
    assert calls == ["KSL-B3"] and not await verified_records(w)
    w.clock.advance(31)
    await settle(w)
    assert len(calls) == 2


def test_verified_quantities_round_half_even():
    from types import SimpleNamespace

    from bcs_gs.ledger.eligibility import EligibilityEvaluator, _ZoneEval

    ledger = SimpleNamespace(telemetry_window=lambda zones, start=None: {"simulated": True})
    ev = EligibilityEvaluator(repo=None, bus=None, clock=None, settings=SimpleNamespace(demo_time_scale="on"),
                              ledger=ledger, forecasts=None, ingest=None, registry=None, tasking=None, grid=None,
                              site_id="KSL")  # fmt: skip
    zq = {"gross_tco2e": "0.005", "buffer_tco2e": "0.007", "uncertainty_tco2e": "0.001", "net_tco2e": "0.005",
          "uncertainty_fraction": "0.0000"}  # fmt: skip
    projected = {"zone_quantities": {"KSL-B3": zq}, "period": {}, "deductions": {"buffer_pct": "15.00"},
                 "evidence": {"forecast_id": "f", "ai_calls": []}}  # fmt: skip
    z = _ZoneEval(
        projected_id="BC-2026-00001", projected=projected, plan={"plan_id": "p", "version": 2}, zone="KSL-B3",
        application={"id": "c0", "taken_at": "t0"}, app_metrics=_zm(45.0),
        qualifying=[({"id": "c1", "taken_at": "t1"}, _zm(45.0, 1.0))], window_since=None,
        confidence={"camera": 0.9, "sensor": 0.9, "prediction": 0.9, "overall": 0.9},
        expected_pp=Decimal("2.0"), verified=False, eligibility=None,
    )  # fmt: skip
    c = ev._verified_content(z)
    assert c["verification_ratio"] == "0.5000"
    # 0.005 x 0.5 = 0.0025 -> 0.002 (half-even, as Projected quantities), never 0.003 (half-up)
    assert (c["quantity_tco2e"], c["gross_tco2e"]) == ("0.002", "0.002")
    assert (c["deductions"]["buffer_tco2e"], c["deductions"]["uncertainty_tco2e"]) == ("0.004", "0.000")
