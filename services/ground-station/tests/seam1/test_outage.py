"""M7 Task 3: an internet outage mid-pitch buffers and later drains in order (Review Focus 4)."""

from __future__ import annotations


async def test_ten_minute_outage_drains_in_order(world_with_sim):  # Review Focus 4
    w = world_with_sim; w.cloud.failing = True; w.run_for(seconds=600)
    q = (await w.http.get("/api/v1/system/status")).json()["sync"]; assert q["state"] in ("buffering", "offline") and q["queue"] > 0
    w.cloud.failing = False; await w.sync.drain_once()
    rows = w.cloud.tables_in_order("telemetry"); assert len(rows) == len({r["id"] for r in rows})
    by_node: dict[str, list[tuple[str, int]]] = {}
    for r in rows:  # cloud arrival order: each node's samples arrive oldest first
        by_node.setdefault(r["node_id"], []).append((r["sampled_at"], r["seq"]))
    assert by_node and all(len(v) > 1 for v in by_node.values())
    for node, seen in by_node.items():
        assert seen == sorted(seen), f"{node} drained out of order"
    assert (await w.http.get("/api/v1/system/status")).json()["sync"]["queue"] == 0
