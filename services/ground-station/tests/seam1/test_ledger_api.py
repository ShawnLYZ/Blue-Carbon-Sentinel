"""M6 Task 6: carbon summary route, ledger verify route and event, link_ok across restart."""

from decimal import Decimal

import pytest
from gs_ledger import create_projected
from test_evidence import _W


@pytest.fixture
async def world_with_projected_record(world_applied_plan):
    w = _W(world_applied_plan, await create_projected(world_applied_plan))
    w.projected_quantity = w.record["quantity_tco2e"]
    return w


async def test_carbon_summary_totals_match_ledger(world_with_projected_record):
    s = (await world_with_projected_record.http.get("/api/v1/carbon/summary")).json()
    assert Decimal(str(s["projected_tco2e"])) == Decimal(world_with_projected_record.projected_quantity)
    assert s["verified_tco2e"] == 0 and len(s["constants"]) >= 4
    assert all(c["citation"] for c in s["constants"])
    assert s["stock_tco2e"] == pytest.approx(sum(s["per_zone"].values())) and s["per_zone"]


async def test_carbon_summary_without_forecast_or_records(gs):
    s = (await gs.http.get("/api/v1/carbon/summary")).json()
    assert s["projected_tco2e"] == 0 and s["verified_tco2e"] == 0 and len(s["constants"]) >= 4


async def test_verify_chain_route_and_event(world_with_projected_record):
    async with world_with_projected_record.events() as ev:
        v = (await world_with_projected_record.http.post("/api/v1/ledger/verify")).json()
        assert v["intact"] is True and (await ev.wait_for("ledger.verified"))["data"]["checked"] == 1


async def test_link_ok_reflects_latest_verification(world_with_projected_record):
    w = world_with_projected_record
    assert (await w.http.get("/api/v1/ledger/records")).json()[0]["link_ok"] is None
    await w.http.post("/api/v1/ledger/verify")
    assert (await w.http.get(f"/api/v1/ledger/records/{w.record_id}")).json()["link_ok"] is True


async def test_startup_verification_populates_link_ok(world_with_projected_record):
    w = world_with_projected_record
    ledger = w.ledger
    ledger.reset()  # what a restart does to the in-memory result
    assert (await w.http.get("/api/v1/ledger/records")).json()[0]["link_ok"] is None
    from gs_forecast import on_gs_loop

    await on_gs_loop(w, ledger.startup_verify)
    assert (await w.http.get("/api/v1/ledger/records")).json()[0]["link_ok"] is True
