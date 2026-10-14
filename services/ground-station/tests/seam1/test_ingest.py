"""Telemetry ingest (addendum G5) and the retained node configuration (G3, N1, N12)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import Any

from bcs_protocol.timefmt import from_iso


async def settle() -> None:
    """Test publishers return once the ingest handled their message; this only yields the loop."""
    await asyncio.sleep(0.05)


async def wait_telemetry(
    gsb: Any, node_id: str, *, other_than: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The first stored telemetry row of ``node_id`` (with a boot other than ``other_than``'s)."""
    deadline = time.monotonic() + 15
    while True:
        for r in await gsb.rows("telemetry"):
            if r["node_id"] == node_id and (other_than is None or r["boot_id"] != other_than["boot_id"]):
                return r
        if time.monotonic() > deadline:
            raise AssertionError(f"no telemetry from {node_id}")
        await asyncio.sleep(0.05)


# ---- the brief's tests ------------------------------------------------------------------------
async def test_valid_telemetry_stored_and_event_emitted(world):
    async with world.events() as ev:
        world.node("WQ-01").publish_telemetry(seq=1)
        e = await ev.wait_for("node.telemetry", lambda d: d["node_id"] == "WQ-01")
        assert e["data"]["source"] == "simulated"
    assert set(e["data"]) == {
        "node_id",
        "sampled_at",
        "mode",
        "readings",
        "health",
        "flags",
        "late",
        "source",
        "replay",
    }
    assert len(await world.rows("telemetry", node_id="WQ-01")) == 1
    await world.wait_status("WQ-01", "online")


async def test_duplicate_dropped_and_late_marked(world):
    n = world.node("WQ-01")
    n.publish_telemetry(seq=5)
    n.publish_telemetry(seq=5)
    n.publish_telemetry(seq=6, sampled_at=world.clock.now() - timedelta(seconds=61))  # > 2 x 30 s
    rows = await world.rows("telemetry", node_id="WQ-01")
    assert [r["seq"] for r in rows] == [5, 6] and rows[1]["late"] is True
    assert rows[0]["late"] is False
    assert await world.rows("node_events", node_id="WQ-01", kind="malformed") == []


async def test_out_of_order_burst_latest_view_uses_newest_sampled_at(world):  # Review Focus 2
    n = world.node("WQ-01")
    t = world.clock.now()
    for seq, dt in [(1, 0), (3, 4), (2, 2)]:
        n.publish_telemetry(seq=seq, sampled_at=t + timedelta(seconds=dt))
    await settle()
    assert world.ingest.latest("WQ-01").seq == 3
    series = (await world.http.get("/api/v1/nodes/WQ-01/telemetry")).json()["points"]
    assert [p["t"] for p in series] == sorted(p["t"] for p in series)
    assert len(series) == 3
    nodes = {x["id"]: x for x in (await world.http.get("/api/v1/nodes")).json()}
    assert from_iso(nodes["WQ-01"]["latest"]["sampled_at"]) == t + timedelta(seconds=4)
    assert nodes["WQ-02"]["latest"] is None


async def test_malformed_creates_ground_station_event_not_reading(world):
    world.node("SP-01").publish_raw("telemetry", b"{not json")
    ev = await world.wait_event("node.event", lambda d: d["kind"] == "malformed")
    assert ev["data"]["origin"] == "ground_station" and await world.rows("telemetry", node_id="SP-01") == []
    row = (await world.rows("node_events", node_id="SP-01", kind="malformed"))[0]
    assert row["details"]["errors"] and row["details"]["excerpt"] == "{not json"


async def test_offline_by_last_will_and_by_silence(world):
    world.node("WQ-02").drop()
    await world.wait_status("WQ-02", "offline")
    world.node("WQ-03").publish_telemetry(seq=1)
    world.clock.advance(91)  # 3 x 30 s
    await world.wait_status("WQ-03", "offline")
    gs_events = [
        (r["kind"], r["details"].get("reason")) for r in await world.rows("node_events", node_id="WQ-03")
    ]
    assert gs_events[-1] == ("offline", "silence")
    will = [(r["kind"], r["details"].get("reason")) for r in await world.rows("node_events", node_id="WQ-02")]
    assert will[-1] == ("offline", "last_will")


async def test_simulator_restart_reprovisions_and_resumes(gs_broker, sim_runtime_factory):  # Review Focus 1
    rt1 = sim_runtime_factory()
    await asyncio.to_thread(rt1.start)
    rt1.run_background()
    first = await wait_telemetry(gs_broker, "SP-01")
    await asyncio.to_thread(rt1.stop)
    rt2 = sim_runtime_factory()
    await asyncio.to_thread(rt2.start)
    rt2.run_background()
    second = await wait_telemetry(gs_broker, "SP-01", other_than=first)
    assert first["boot_id"] != second["boot_id"]
    assert (await gs_broker.http.get("/api/v1/nodes/SP-01")).json()["status"] == "online"
    rows = [r for r in await gs_broker.rows("telemetry") if r["node_id"] == "SP-01"]
    assert len({(r["boot_id"], r["seq"]) for r in rows}) == len(rows)


async def test_retained_config_published_with_demo_intervals(world):
    cfg = await world.retained("bcs/v1/KSL/nodes/WQ-01/config")
    assert (cfg["baseline_interval_s"], cfg["investigation_interval_s"]) == (30, 2) and cfg[
        "demo_time_scale"
    ] is True
    assert cfg["schema"] == "bcs.config.v1" and cfg["node_id"] == "WQ-01" and cfg["config_version"] >= 1
    # Bands are thresholds (G3): critical below min or above max; values from N1's 0.6 points.
    assert cfg["critical_bands"] == {
        "do_mg_l": {"min": 2.0},
        "ph": {"min": 6.5, "max": 9.0},
        "turbidity_ntu": {"max": 100.0},
        "salinity_psu": {"max": 45.0},
        "temp_c": {"max": 36.0},
    }
    sp = await world.retained("bcs/v1/KSL/nodes/SP-01/config")
    assert sp["critical_bands"] == {"porewater_salinity_psu": {"max": 60.0}}
    tg = await world.retained("bcs/v1/KSL/nodes/TG-01/config")
    assert tg["critical_bands"] == {}
    assert sp["battery_low_pct"] == 15 and sp["anomaly"]["window"] == 30


# ---- further coverage --------------------------------------------------------------------------
async def test_config_version_increases_on_online_and_demo_time_change(world):
    before = (await world.retained("bcs/v1/KSL/nodes/WQ-04/config"))["config_version"]
    world.node("WQ-04")  # connects and publishes a retained online status
    await world.wait_status("WQ-04", "online")
    deadline = time.monotonic() + 5
    while (cfg := await world.retained("bcs/v1/KSL/nodes/WQ-04/config"))["config_version"] != before + 1:
        assert time.monotonic() < deadline, cfg
        await asyncio.sleep(0.05)
    await asyncio.to_thread(world.ingest.set_demo_time_scale, False)
    deadline = time.monotonic() + 5
    while (cfg := await world.retained("bcs/v1/KSL/nodes/WQ-04/config"))["config_version"] != before + 2:
        assert time.monotonic() < deadline, cfg
        await asyncio.sleep(0.05)
    assert (cfg["baseline_interval_s"], cfg["investigation_interval_s"], cfg["demo_time_scale"]) == (
        900,
        30,
        False,
    )


async def test_node_events_deduplicated_and_emitted(world):
    n = world.node("TG-01")
    async with world.events() as ev:
        seq = n.publish_event("battery_low", parameter="battery_pct", value=12.0)
        n.publish_event("battery_low", seq=seq, parameter="battery_pct", value=12.0)
        e = await ev.wait_for("node.event", lambda d: d["kind"] == "battery_low")
    assert e["data"]["origin"] == "node" and e["data"]["node_id"] == "TG-01"
    assert set(e["data"]) == {
        "id",
        "node_id",
        "at",
        "origin",
        "kind",
        "parameter",
        "value",
        "score",
        "details",
    }
    rows = await world.rows("node_events", node_id="TG-01", kind="battery_low")
    assert len(rows) == 1 and rows[0]["seq"] == seq and rows[0]["boot_id"] == n.boot_id


async def test_ack_is_handed_to_the_hook(world):
    got: list[Any] = []
    world.ingest.on_ack = got.append
    world.node("WQ-01").publish_ack("01890a5d-ac96-774b-bcce-b302099a8057", "accepted")
    await settle()
    assert [(a.node_id, a.command_id, a.status) for a in got] == [
        ("WQ-01", "01890a5d-ac96-774b-bcce-b302099a8057", "accepted")
    ]


async def test_inconsistent_future_and_wrong_type_are_malformed(world):
    n = world.node("WQ-01")
    n.publish_telemetry(seq=1, sampled_at=world.clock.now() + timedelta(seconds=61))  # step 5
    n.publish_telemetry(seq=2, node_id="WQ-02")  # step 3: topic and payload disagree
    n.publish_telemetry(
        seq=3, readings={"salinity_psu": 70.0, "turbidity_ntu": 1, "do_mg_l": 1, "temp_c": 1, "ph": 7}
    )
    assert await world.rows("telemetry") == []
    rows = await world.rows("node_events", node_id="WQ-01", kind="malformed")
    assert len(rows) == 3 and all(r["origin"] == "ground_station" for r in rows)
    assert all(len(r["details"]["errors"]) >= 1 for r in rows)


async def test_decommissioned_node_telemetry_is_malformed(world):
    # A decommissioned node is disabled on the broker, so its message is fed to the ingest directly.
    payload = json.dumps({**world.node("SP-03").telemetry(1)}).encode()
    await asyncio.to_thread(world.registry.decommission, "SP-03")
    out = await asyncio.to_thread(
        world.ingest._process_message, "bcs/v1/KSL/nodes/SP-03/telemetry", payload, world.clock.now()
    )
    assert [t for t, _ in out.events] == ["node.event"]
    assert await world.rows("telemetry", node_id="SP-03") == []
    rows = await world.rows("node_events", node_id="SP-03", kind="malformed")
    assert len(rows) == 1 and "decommissioned" in rows[0]["details"]["errors"][0]


async def test_online_offline_transitions_write_ground_station_events(world):
    n = world.node("WQ-03")
    n.publish_telemetry(seq=1)
    world.clock.advance(91)
    await world.wait_status("WQ-03", "offline")
    n.publish_telemetry(seq=2)
    await world.wait_status("WQ-03", "online")
    kinds = [(r["kind"], r["origin"]) for r in await world.rows("node_events", node_id="WQ-03")]
    assert kinds == [
        ("online", "ground_station"),
        ("offline", "ground_station"),
        ("online", "ground_station"),
    ]
    st = await world.wait_event("node.status", lambda d: d["node_id"] == "WQ-03" and d["state"] == "offline")
    assert st["data"]["reason"] == "silence" and set(st["data"]) == {
        "node_id",
        "state",
        "mode",
        "interval_s",
        "at",
        "reason",
    }


async def test_robust_and_window(world):
    n = world.node("WQ-01")
    t = world.clock.now()
    for i, sal in enumerate([10.0, 11.0, 30.0, 12.0, 13.0, 14.0]):
        r = {**n.telemetry(0)["readings"], "salinity_psu": sal}
        n.publish_telemetry(seq=i, sampled_at=t - timedelta(seconds=10 * (5 - i)), readings=r)
    assert world.ingest.robust("WQ-01", "salinity_psu", "baseline") == 13.0  # median of 11, 30, 12, 13, 14
    assert world.ingest.robust("WQ-01", "salinity_psu", "investigation") == 12.5  # last 60 s: all 6
    assert [r.seq for r in world.ingest.window("WQ-01", t - timedelta(seconds=20))] == [3, 4, 5]
    assert world.ingest.robust("WQ-02", "salinity_psu", "baseline") is None


async def test_node_detail_and_series_downsampling(world):
    n = world.node("WQ-01")
    t = world.clock.now()
    for i in range(20):
        r = {**n.telemetry(0)["readings"], "temp_c": float(i)}
        n.publish_telemetry(seq=i, sampled_at=t - timedelta(seconds=40 - 2 * i), readings=r)
    n.publish_event("boot")
    detail = (await world.http.get("/api/v1/nodes/WQ-01")).json()
    assert detail["status"] == "online" and detail["source"] == "simulated" and detail["tasks"] == []
    assert len(detail["recent_telemetry"]) == 20 and detail["latest"]["readings"]["temp_c"] == 19.0
    assert [e["kind"] for e in detail["recent_events"]][:1] == ["boot"]
    full = (await world.http.get("/api/v1/nodes/WQ-01/telemetry")).json()
    assert full["downsampled"] is False and len(full["points"]) == 20 and full["node_id"] == "WQ-01"
    ds = (await world.http.get("/api/v1/nodes/WQ-01/telemetry", params={"max_points": 5})).json()
    assert ds["downsampled"] is True and 1 <= len(ds["points"]) <= 5
    assert [p["t"] for p in ds["points"]] == sorted(p["t"] for p in ds["points"])
    mean = sum(range(20)) / 20
    total = sum(p["readings"]["temp_c"] for p in ds["points"]) / len(ds["points"])
    assert abs(total - mean) < 2.0
    events = (await world.http.get("/api/v1/nodes/WQ-01/events")).json()
    assert events[0]["kind"] == "boot"
    assert (await world.http.get("/api/v1/nodes/WQ-99")).status_code == 404
    assert (await world.http.get("/api/v1/nodes/WQ-99/telemetry")).status_code == 404
