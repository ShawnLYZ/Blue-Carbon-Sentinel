"""M6 Task 3: the append-only, hash-chained carbon ledger, Projected records and tamper detection."""

import asyncio
import re
import sqlite3

import pytest
from bcs_gs.ledger.canonical import record_hash
from gs_assess import _seed_capture
from gs_ledger import PLAN_ZONE, append_dummy, create_projected

LABEL = "Demo record — not a certified carbon credit"
METHOD = "aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified"


async def test_projected_requires_checklist(world_plan_not_applied):
    PLAN = world_plan_not_applied.plan_id
    r = await world_plan_not_applied.http.post("/api/v1/ledger/projected", json={"plan_id": PLAN})
    assert r.status_code == 422 and r.json()["error"]["details"]["checklist"]["restoration"] is False
    assert (await world_plan_not_applied.http.get("/api/v1/ledger/records")).json() == []


async def test_checklist_route(world_plan_not_applied):
    PLAN = world_plan_not_applied.plan_id
    c = (await world_plan_not_applied.http.get("/api/v1/ledger/checklist", params={"plan_id": PLAN})).json()
    assert c == {"plan_id": PLAN, "satellite": True, "sensor": True, "ai": False, "restoration": False,
                 "missing": ["ai", "restoration"]}  # fmt: skip
    assert (await world_plan_not_applied.http.get("/api/v1/ledger/checklist")).status_code == 422
    r = await world_plan_not_applied.http.get("/api/v1/ledger/checklist", params={"plan_id": "nope"})
    assert r.status_code == 404


async def test_projected_record_fields_and_hash(world_applied_plan):
    PLAN = world_applied_plan.plan_id
    rec = (await world_applied_plan.http.post("/api/v1/ledger/projected", json={"plan_id": PLAN})).json()
    assert re.fullmatch(r"BC-2026-\d{5}", rec["record_id"]) and rec["type"] == "projected"
    c = rec["content"]
    assert c["label"] == "Demo record — not a certified carbon credit" and c["evidence"]["telemetry_window"]["simulated"] is True
    assert c["method_note"] == "aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified"
    assert record_hash(rec["canonical"]) == rec["hash"] and rec["previous_hash"] == "0" * 64
    # the rest of the §23 content
    assert rec["record_id"] == "BC-2026-00001" and rec["chain_index"] == 0 and c["chain_index"] == 0
    assert c["zone_ids"] == [PLAN_ZONE] and c["period"] == {"start_year": 2026, "end_year": 2035}
    zq = c["zone_quantities"][PLAN_ZONE]
    assert c["quantity_tco2e"] == rec["quantity_tco2e"] == zq["net_tco2e"]
    assert re.fullmatch(r"\d+\.\d{3}", c["quantity_tco2e"]) and re.fullmatch(r"\d+\.\d{3}", c["gross_tco2e"])
    assert re.fullmatch(r"[01]\.\d{4}", c["confidence"]["overall"])
    assert c["confidence"]["overall"] == zq["confidence"]
    ev = c["evidence"]
    plan = (await world_applied_plan.http.get(f"/api/v1/plans/{PLAN}")).json()
    assert ev["plan_id"] == PLAN and ev["plan_version"] == plan["version"] == 2
    assert ev["forecast_id"] == plan["forecast_id"]
    roles = {x["role"] for x in ev["captures"]}
    assert {"baseline", "application", "latest"} <= roles
    assert plan["capture_at_application_id"] in {x["id"] for x in ev["captures"] if x["role"] == "application"}
    tw = ev["telemetry_window"]
    assert tw["node_ids"] and set(tw) >= {"node_ids", "from", "to", "stats", "simulated"}
    assert all({"tier", "model", "role"} <= set(a) for a in ev["ai_calls"]) and ev["ai_calls"]
    fpe = [a for a in ev["ai_calls"] if a["role"] == "forecast_parameter_estimator"]
    assert [a["zone_id"] for a in fpe] == [PLAN_ZONE]  # the plan's zones only
    assert isinstance(c["demo_time_scale"], bool)
    # display columns, alert and event
    got = (await world_applied_plan.http.get(f"/api/v1/ledger/records/{rec['record_id']}")).json()
    assert got["hash"] == rec["hash"] and got["content"] == c
    assert (await world_applied_plan.http.get("/api/v1/ledger/records/BC-2026-99999")).status_code == 404
    alerts = (await world_applied_plan.http.get("/api/v1/alerts")).json()
    issued = [a for a in alerts if a["type"] == "ledger_issued"]
    assert len(issued) == 1 and issued[0]["severity"] == "info" and rec["record_id"] in issued[0]["message"]
    e = await world_applied_plan.wait_event("ledger.appended")
    assert e["data"] == {"chain_index": 0, "record_id": rec["record_id"], "type": "projected",
                         "quantity_tco2e": rec["quantity_tco2e"]}  # fmt: skip


async def test_projected_protects_its_evidence_captures(world_applied_plan):  # H7, A2
    later = await _seed_capture(world_applied_plan, {})  # an evidence-grade capture after application
    rec = await create_projected(world_applied_plan)
    ids = {x["id"] for x in rec["content"]["evidence"]["captures"]}
    assert later["id"] in ids
    rows = {r["id"]: r for r in await world_applied_plan.rows("captures")}
    # a capture with no stronger reason becomes ledger evidence; baseline / plan_application are kept
    assert rows[later["id"]]["retention_reason"] == "ledger_evidence"
    assert all(rows[i]["retention_reason"] in ("baseline", "plan_application", "ledger_evidence") for i in ids)
    protected = world_applied_plan.gs.services.retention._protected_ids()
    assert ids <= protected


async def test_projected_is_idempotent_per_plan_version(world_applied_plan):  # Review Focus 5
    PLAN = world_applied_plan.plan_id
    a, b = await asyncio.gather(*(world_applied_plan.http.post("/api/v1/ledger/projected", json={"plan_id": PLAN}) for _ in range(2)))
    assert a.json()["record_id"] == b.json()["record_id"] and len((await world_applied_plan.http.get("/api/v1/ledger/records")).json()) == 1


async def test_update_and_delete_rejected_locally(world_applied_plan):
    await create_projected(world_applied_plan)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"): world_applied_plan.raw_sql("update ledger_records set label='x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        world_applied_plan.raw_sql("delete from ledger_records")
    with pytest.raises(ValueError, match="insert-only"):
        world_applied_plan.gs.services.repo.upsert("ledger_records", {"chain_index": 0})


async def test_tamper_detected_at_index_and_blocks_issuance(world_applied_plan):  # Review Focus 2
    for _ in range(3): await append_dummy(world_applied_plan)
    ok = (await world_applied_plan.http.post("/api/v1/ledger/verify")).json()
    assert ok["intact"] is True and ok["checked"] == 3 and ok["first_broken_index"] is None
    world_applied_plan.tamper(chain_index=1)           # drops the trigger, edits canonical, re-creates the trigger
    v = (await world_applied_plan.http.post("/api/v1/ledger/verify")).json()
    assert v["intact"] is False and v["first_broken_index"] == 1
    assert any(a["type"] == "chain_broken" for a in (await world_applied_plan.http.get("/api/v1/alerts")).json())
    assert world_applied_plan.ledger.issuance_blocked is True
    recs = (await world_applied_plan.http.get("/api/v1/ledger/records")).json()  # newest first (I1)
    assert [(r["chain_index"], r["link_ok"]) for r in recs] == [(2, False), (1, False), (0, True)]
    e = await world_applied_plan.wait_event("ledger.verified", lambda d: d["intact"] is False)
    assert e["data"]["first_broken_index"] == 1 and e["data"]["at"]


async def test_ledger_offline_then_sync_once_in_order(world_applied_plan):  # Review Focus 1
    world_applied_plan.cloud.failing = True
    for _ in range(3): await append_dummy(world_applied_plan)
    world_applied_plan.cloud.failing = False; await world_applied_plan.sync.drain_once()
    assert [r["chain_index"] for r in world_applied_plan.cloud.tables_in_order("ledger_records")] == [0, 1, 2]
    sent = [r["chain_index"] for c in world_applied_plan.cloud.calls if c.table == "ledger_records" for r in c.rows]
    assert sent == [0, 1, 2]  # exactly once each


async def test_append_always_writes_the_label_and_methodology(gs):  # callers cannot override them
    from gs_ledger import DUMMY

    ledger = gs.services.ledger
    content = {**DUMMY, "label": "Certified carbon credit", "method_note": "Verra certified"}
    loop = gs.services.tasking.loop
    rec = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(ledger.append(content), loop))
    assert rec.content["label"] == LABEL and rec.content["method_note"] == METHOD
    assert '"label":"Certified' not in rec.canonical and "Verra certified" not in rec.canonical


# ---- final review: display columns are verified; crafted rows never 500 ------------------------------
async def _verify_reports_broken(w, index: int) -> None:
    r = await w.http.post("/api/v1/ledger/verify")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["intact"] is False and v["first_broken_index"] == index, v
    assert any(a["type"] == "chain_broken" for a in (await w.http.get("/api/v1/alerts")).json())
    assert w.ledger.issuance_blocked is True


async def test_tampered_display_column_is_detected_and_not_trusted(world_applied_plan):  # Review Focus 2
    w = world_applied_plan
    rec = await create_projected(w)
    for _ in range(2): await append_dummy(w)
    before = (await w.http.get("/api/v1/carbon/summary")).json()["projected_tco2e"]
    w.tamper_sql(0, "quantity_tco2e = ?", ("999999.000",))
    await _verify_reports_broken(w, 0)
    # totals and the record are derived from the hashed canonical content, not the edited column
    assert (await w.http.get("/api/v1/carbon/summary")).json()["projected_tco2e"] == before
    got = (await w.http.get(f"/api/v1/ledger/records/{rec['record_id']}")).json()
    assert got["quantity_tco2e"] == rec["quantity_tco2e"]


async def test_tampered_json_display_column_is_detected(world_applied_plan):
    w = world_applied_plan
    for _ in range(3): await append_dummy(w)
    w.tamper_sql(2, "zone_ids = ?", ('["KSL-A1"]',))
    await _verify_reports_broken(w, 2)


async def test_tampered_evidence_column_cannot_unlock_a_second_projected(world_applied_plan):
    w = world_applied_plan
    rec = await create_projected(w)
    w.tamper_sql(0, "evidence = json_set(evidence, '$.plan_version', 99)")
    again = await create_projected(w)  # idempotency reads the canonical content, not the column
    assert again["record_id"] == rec["record_id"]
    assert len((await w.http.get("/api/v1/ledger/records")).json()) == 1


async def test_retention_protects_by_canonical_evidence_not_the_display_column(world_applied_plan):
    w = world_applied_plan
    later = await _seed_capture(w, {})
    rec = await create_projected(w)
    ids = {x["id"] for x in rec["content"]["evidence"]["captures"]}
    assert later["id"] in ids
    w.raw_sql("UPDATE captures SET retention_reason = NULL WHERE retention_reason = 'ledger_evidence'")
    # the display column is edited to cite nothing, and to cite a capture the canonical content never did
    w.tamper_sql(0, "evidence = ?", ('{"captures": [{"id": "CAP-NOT-EVIDENCE"}]}',))
    protected = w.gs.services.retention._protected_ids()
    assert later["id"] in protected and "CAP-NOT-EVIDENCE" not in protected


@pytest.mark.parametrize(
    ("assignments", "params"),
    [
        ("canonical = CAST(? AS TEXT)", (b"\xff\xfe not utf-8",)),  # invalid UTF-8 stored as TEXT
        ("canonical = ?", ("[" * 100_000 + "]" * 100_000,)),  # deep nesting
        ("canonical = ?", ("not json",)),  # unparseable
    ],
    ids=["invalid-utf8", "deep-nesting", "unparseable"],
)
async def test_crafted_canonical_reports_broken_without_500(world_applied_plan, assignments, params):
    w = world_applied_plan
    for _ in range(3): await append_dummy(w)
    w.tamper_sql(1, assignments, params)
    await _verify_reports_broken(w, 1)
    r = await w.http.get("/api/v1/ledger/records")
    assert r.status_code == 200 and [x["link_ok"] for x in r.json()] == [False, False, True]
    assert (await w.http.get("/api/v1/carbon/summary")).status_code == 200


@pytest.mark.parametrize("column", ["record_id", "type", "created_at", "quantity_tco2e", "previous_hash", "hash"])
async def test_invalid_utf8_in_any_listed_column_does_not_500(world_applied_plan, column):
    w = world_applied_plan
    for _ in range(3): await append_dummy(w)
    w.tamper_sql(1, f"{column} = CAST(? AS TEXT)", (bytes([0xFF, 0xFE]) + b" bad",))
    await _verify_reports_broken(w, 1)
    r = await w.http.get("/api/v1/ledger/records")
    assert r.status_code == 200 and len(r.json()) == 3, r.text
    assert (await w.http.get("/api/v1/ledger/records/" + r.json()[1]["record_id"])).status_code in (200, 404)


async def test_content_index_disagreeing_with_the_row_is_broken(world_applied_plan):
    import json

    from bcs_gs.ledger.canonical import canonical_json

    w = world_applied_plan
    for _ in range(3): await append_dummy(w)
    canonical = w.raw_sql("SELECT canonical FROM ledger_records WHERE chain_index = 1")[0][0]
    edited = canonical_json({**json.loads(canonical), "chain_index": 2})
    w.tamper_sql(1, "canonical = ?, hash = ?", (edited, record_hash(edited)))
    await _verify_reports_broken(w, 1)


async def test_method_note_is_the_constant_never_the_optional_config(gs, monkeypatch):
    from gs_ledger import DUMMY

    ledger = gs.services.ledger
    monkeypatch.setattr(ledger, "_carbon", type("C", (), {"CFG": ledger._carbon.CFG.model_copy(
        update={"methodology_label": None})}))  # fmt: skip
    loop = gs.services.tasking.loop
    rec = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(ledger.append(dict(DUMMY)), loop))
    assert rec.content["method_note"] == METHOD


async def test_startup_verifies_the_chain_once(gs, monkeypatch):
    from bcs_gs.core.clock import ManualClock
    from bcs_gs.ledger.service import LedgerService
    from bcs_gs.store.cloud import FakeCloudTarget
    from gs_ledger import DUMMY

    loop = gs.services.tasking.loop
    await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(gs.services.ledger.append(dict(DUMMY)), loop))
    await asyncio.to_thread(gs.stop)
    calls: list[int] = []
    real = LedgerService.verify_chain

    async def counting(self):
        calls.append(1)
        return await real(self)

    monkeypatch.setattr(LedgerService, "verify_chain", counting)
    again = type(gs)(gs.settings, FakeCloudTarget(failing=False), ManualClock(gs.clock.now()), gs.data_dir)
    await asyncio.to_thread(again.start)
    try:
        await asyncio.sleep(1.5)  # the evaluator's first pass and the startup tasks run
        assert len(calls) == 1
        assert again.services.ledger._last is not None and again.services.ledger._last.intact
    finally:
        await asyncio.to_thread(again.stop)
