"""Seam-1 hydration fixture (M7 Task 3).

- ``cloud_with_history``: the FakeCloudTarget of a Ground Station that has been through a real flow
  (``world_applied_plan``: 8 nodes, baseline and flagged captures, an applied plan, a ready forecast),
  then issued a Projected ledger record, verified the chain and drained everything to the cloud.
  ``.history`` holds what was created (record ID, forecast ID, the telemetry row's sample time).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from gs_ledger import create_projected


@pytest.fixture
async def cloud_with_history(world_applied_plan: Any) -> Any:
    w = world_applied_plan
    node_id = next(iter(w.keys))
    await asyncio.to_thread(w.node(node_id).publish_telemetry, 1)
    rec = await create_projected(w)
    r = await w.http.post("/api/v1/ledger/verify")
    assert r.status_code == 200 and r.json()["intact"], r.text
    latest = (await w.http.get("/api/v1/forecasts/latest")).json()
    for _ in range(5):  # a pass can stop short while rows are still being enqueued by background work
        res = await w.sync.drain_once()
        assert res.ok
        if w.gs.services.sync.status().queue == 0:
            break
    cloud = w.cloud
    cloud.history = SimpleNamespace(record_id=rec["record_id"], forecast_id=latest["id"])
    return cloud
