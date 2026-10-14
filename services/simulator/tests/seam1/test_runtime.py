"""Seam 1: the simulator runtime against a real Mosquitto and a fake Ground Station client."""

from __future__ import annotations

import json

from bcs_sim.clock import ManualClock
from bcs_sim.runtime import Runtime
from helpers import (
    T0,
    capture_published,
    cfg,
    eventually,
    gs_publisher,
    original_boot_ids,
    retained_status,
    run_for,
    start_rt,
    subscribe_all,
    topic_node,
)

ALL_8 = {"WQ-01", "WQ-02", "WQ-03", "WQ-04", "SP-01", "SP-02", "SP-03", "TG-01"}


async def test_runtime_publishes_telemetry_for_every_registered_node(mosquitto, fake_gs_with_8_nodes):
    clock = ManualClock(T0)
    rt = Runtime(
        cfg(), fake_gs_with_8_nodes, clock, seed=42, broker_host=mosquitto.host, broker_port=mosquitto.port
    )
    rt.start()
    try:
        got = subscribe_all(mosquitto, "bcs/v1/KSL/nodes/+/telemetry")

        def step_until_all_seen() -> bool:
            # A link that is mid-reconnect (a stale session of the same client ID being taken over) skips its
            # sample for that step and a lost QoS 1 publish is not replayed, so keep stepping like the real
            # runtime loop does instead of relying on a single step.
            clock.advance(30)
            rt.step(clock.now())
            return {topic_node(t) for t in got} == ALL_8

        await eventually(step_until_all_seen, timeout=10.0)
    finally:
        rt.stop()


async def test_start_publishes_retained_online_status(mosquitto, fake_gs_with_8_nodes):
    rt, _ = start_rt(mosquitto, fake_gs_with_8_nodes)
    st = retained_status(mosquitto, "TG-01")
    assert st["state"] == "online" and st["source"] == "simulated" and st["boot_id"]
    assert set(rt.credentials) == ALL_8


async def test_offline_fault_fires_last_will(mosquitto, fake_gs_with_8_nodes):
    rt, clock = start_rt(mosquitto, fake_gs_with_8_nodes)
    rt.faults("WQ-02").inject("offline", {})
    rt.step(clock.now())
    await eventually(lambda: retained_status(mosquitto, "WQ-02")["state"] == "offline")
    assert retained_status(mosquitto, "WQ-02")["reason"] == "last_will"
    rt.faults("WQ-02").clear("offline")
    rt.step(clock.now())
    await eventually(lambda: retained_status(mosquitto, "WQ-02")["state"] == "online")


async def test_clean_stop_publishes_shutdown_status(mosquitto, fake_gs_with_8_nodes):
    rt, _ = start_rt(mosquitto, fake_gs_with_8_nodes)
    rt.stop()
    st = retained_status(mosquitto, "SP-02")
    assert st["state"] == "offline" and st["reason"] == "shutdown"


async def test_replay_is_marked_and_restamped(tmp_path, mosquitto, fake_gs_with_8_nodes):
    rt, clock = start_rt(mosquitto, fake_gs_with_8_nodes, sessions_dir=tmp_path)
    rt.recorder.start("r1")
    run_for(rt, clock, 60)
    meta = rt.recorder.stop()
    msgs = capture_published(mosquitto)
    rt.replayer.replay(meta.path)
    run_for(rt, clock, 60)
    await eventually(lambda: any(json.loads(m.payload).get("replay") is True for m in list(msgs)))
    replayed = [m for m in list(msgs) if json.loads(m.payload).get("replay") is True]
    assert replayed and all(json.loads(m.payload)["source"] == "simulated" for m in replayed)
    assert {json.loads(m.payload)["boot_id"] for m in replayed}.isdisjoint(original_boot_ids(meta))
    assert fake_gs_with_8_nodes.uploads and fake_gs_with_8_nodes.uploads[0][0]["id"] == meta.id


async def test_inspector_marks_malformed_as_invalid(mosquitto, fake_gs_with_8_nodes):
    rt, clock = start_rt(mosquitto, fake_gs_with_8_nodes)
    rt.faults("SP-01").inject("malformed", {})
    run_for(rt, clock, 60)
    packets = rt.inspector.drain()
    assert any(p.direction == "up" and p.node_id == "SP-01" and p.valid is False for p in packets)
    assert any(p.direction == "up" and p.node_id == "SP-02" and p.valid is True for p in packets)


async def test_command_from_ground_station_is_acknowledged(mosquitto, fake_gs_with_8_nodes):
    """A cmd published as the Ground Station reaches the node, shows as a down packet and is acked."""
    rt, clock = start_rt(mosquitto, fake_gs_with_8_nodes)
    acks = subscribe_all(mosquitto, "bcs/v1/KSL/nodes/WQ-03/ack")
    pub = gs_publisher(mosquitto)
    cmd = {
        "schema": "bcs.cmd.v1",
        "site_id": "KSL",
        "node_id": "WQ-03",
        "command_id": "0192a000-0000-7000-8000-000000000001",
        "type": "ping",
        "params": {},
        "issued_at": "2026-10-16T03:04:05.123Z",
        "expires_at": "2026-10-16T04:04:05.123Z",
        "task_id": None,
        "reason": "test",
    }
    pub.publish("bcs/v1/KSL/nodes/WQ-03/cmd", json.dumps(cmd), qos=1)

    def pumped() -> bool:
        rt.step(clock.now())
        return bool(acks)

    await eventually(pumped)
    downs = [p for p in rt.inspector.drain() if p.direction == "down" and p.node_id == "WQ-03"]
    assert downs and downs[0].channel == "cmd" and downs[0].valid
    view = next(v for v in rt.state() if v.node_id == "WQ-03")
    assert view.last_command and view.last_command.type == "ping"
    assert view.last_ack and view.last_ack.status == "accepted"
