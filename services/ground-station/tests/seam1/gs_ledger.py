"""Seam-1 ledger helpers and fixtures (M6 Task 3), built on ``world_ready`` (gs_forecast).

- ``world_plan_not_applied``: ``world_ready`` with a plan for KSL-B3 (version 2: the operator's planting
  items) that is not applied. ``.plan_id`` is its ID.
- ``world_applied_plan``: the same plan applied, its forecast ready. Both worlds forward everything to the
  ``world`` and add:
  - ``ledger`` (the LedgerService), ``cloud`` (the FakeCloudTarget), ``sync.drain_once()`` (one sync pass
    on the Ground Station's loop);
  - ``raw_sql(sql)``: run SQL straight on the SQLite file, as someone with the file would (blocking);
  - ``tamper(chain_index)``: drop the append-only triggers, edit that row's ``canonical``, re-create them;
  - ``tamper_sql(chain_index, assignments, params)``: the same with any ``SET`` clause (display columns,
    raw bytes).
- ``await create_projected(world)``: ``POST /ledger/projected`` for the world's plan (asserted 200).
- ``await append_dummy(world)``: ``LedgerService.append`` of a minimal Projected content on the GS loop.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from typing import Any

import pytest
from gs_forecast import FORECAST_TIMEOUT_S, on_gs_loop, propose_and_wait

PLAN_ZONE = "KSL-B3"
UPLIFT = {"canopy_pp_2035": 0.0, "tco2e_2035": 0.0}
PLANTING = [
    {"zone_id": PLAN_ZONE, "interventions": [{"kind": "plant_rhizophora", "sapling_count": 880},
                                             {"kind": "silt_fence"}],
     "priority": 1, "rationale": "ledger test", "expected_uplift": UPLIFT},
]  # fmt: skip


class _Sync:
    def __init__(self, world: Any) -> None:
        self._world = world

    async def drain_once(self) -> Any:
        sync = self._world.gs.services.sync
        return await on_gs_loop(self._world, sync.drain_once)


class LedgerWorld:
    def __init__(self, world: Any, plan_id: str) -> None:
        self._world, self.plan_id = world, plan_id
        self.sync = _Sync(world)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._world, name)

    @property
    def ledger(self) -> Any:
        return self._world.gs.services.ledger

    @property
    def cloud(self) -> Any:
        return self._world.gs.cloud

    def raw_sql(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        conn = sqlite3.connect(str(self._world.gs.services.db.path), isolation_level=None)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def tamper(self, chain_index: int) -> None:
        canonical = self.raw_sql("SELECT canonical FROM ledger_records WHERE chain_index = ?", (chain_index,))[0][0]
        edited = canonical.replace('"label":"Demo record', '"label":"Real record', 1)
        assert edited != canonical
        self.tamper_sql(chain_index, "canonical = ?", (edited,))

    def tamper_sql(self, chain_index: int, assignments: str, params: tuple[Any, ...] = ()) -> None:
        """Drop the append-only triggers, ``UPDATE ledger_records SET {assignments}`` on that row,
        re-create the triggers (someone with the SQLite file)."""
        from bcs_gs.store.schema import LEDGER_TRIGGERS_DDL, LEDGER_TRIGGERS_DROP

        conn = sqlite3.connect(str(self._world.gs.services.db.path), isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in LEDGER_TRIGGERS_DROP:
                conn.execute(stmt)
            n = conn.execute(
                f"UPDATE ledger_records SET {assignments} WHERE chain_index = ?", (*params, chain_index)
            ).rowcount
            assert n == 1
            for stmt in LEDGER_TRIGGERS_DDL:
                conn.execute(stmt)
            conn.execute("COMMIT")
        finally:
            conn.close()


async def _plan(world: Any) -> str:
    p = await propose_and_wait(world, [PLAN_ZONE])
    r = await world.http.put(f"/api/v1/plans/{p['plan_id']}", json={"items": PLANTING})
    assert r.status_code == 200, r.text
    return p["plan_id"]


@pytest.fixture
async def world_plan_not_applied(world_ready: Any) -> AsyncIterator[LedgerWorld]:
    yield LedgerWorld(world_ready, await _plan(world_ready))


@pytest.fixture
async def world_applied_plan(world_ready: Any) -> AsyncIterator[LedgerWorld]:
    plan_id = await _plan(world_ready)
    async with world_ready.events() as ev:
        r = await world_ready.http.post(f"/api/v1/plans/{plan_id}/apply", json={})
        assert r.status_code == 200, r.text
        fid = r.json()["forecast_id"]
        e = await ev.wait_for("forecast.ready", lambda d: d["forecast_id"] == fid, timeout=FORECAST_TIMEOUT_S)
    assert e["data"]["status"] == "ready", e
    yield LedgerWorld(world_ready, plan_id)


async def create_projected(world: LedgerWorld) -> dict[str, Any]:
    r = await world.http.post("/api/v1/ledger/projected", json={"plan_id": world.plan_id})
    assert r.status_code == 200, r.text
    return r.json()


DUMMY = {
    "type": "projected", "site_id": "KSL", "zone_ids": [PLAN_ZONE],
    "period": {"start_year": 2026, "end_year": 2035},
    "quantity_tco2e": "1.000", "gross_tco2e": "1.250",
    "deductions": {"buffer_tco2e": "0.188", "uncertainty_fraction": "0.0000", "uncertainty_tco2e": "0.000"},
    "evidence": {"captures": [], "simulated": True}, "confidence": {"overall": "0.9000"},
}  # fmt: skip


async def append_dummy(world: LedgerWorld) -> Any:
    ledger = world.ledger
    return await on_gs_loop(world, lambda: ledger.append(dict(DUMMY)))
