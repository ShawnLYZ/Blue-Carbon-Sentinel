"""Runtime over the in-memory transport (no broker): the path the headless runner (Task 6) uses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bcs_protocol.validate import parse_message
from bcs_sim.client import MemoryHub
from bcs_sim.clock import ManualClock
from bcs_sim.config import load_sim_config
from bcs_sim.gs_client import SimNodeSpec
from bcs_sim.runtime import Runtime

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)
SPECS = [
    SimNodeSpec("WQ-01", "water_quality", 50.0, 50.0, "A1", "KSL"),
    SimNodeSpec("WQ-02", "water_quality", 160.0, 250.0, "B3", "KSL"),
    SimNodeSpec("SP-01", "soil_probe", 150.0, 150.0, "B2", "KSL"),
    SimNodeSpec("TG-01", "tide_gauge", 250.0, 250.0, "C3", "KSL"),
]


class StubGs:
    def __init__(self, specs: list[SimNodeSpec] | None = None) -> None:
        self.specs = list(specs or SPECS)
        self.cred_calls: list[list[str] | None] = []
        self.uploads: list[tuple[dict[str, Any], Path]] = []
        self.fail_upload = False

    def registry(self) -> list[SimNodeSpec]:
        return list(self.specs)

    def credentials(self, node_ids: list[str] | None = None) -> dict[str, str]:
        self.cred_calls.append(node_ids)
        ids = node_ids if node_ids is not None else [s.node_id for s in self.specs]
        return {n: f"pw-{n}-{len(self.cred_calls)}" for n in ids}

    def upload_session(self, meta: dict[str, Any], path: Path) -> dict[str, Any]:
        if self.fail_upload:
            raise ConnectionError("ground station unreachable")
        self.uploads.append((meta, path))
        return {"id": meta["id"]}

    def watch_registry(self, callback: Any) -> None:
        return None


def make(
    tmp_path: Path, seed: int = 42, gs: StubGs | None = None
) -> tuple[Runtime, ManualClock, MemoryHub, StubGs]:
    hub = MemoryHub()
    clock = ManualClock(T0)
    gs = gs or StubGs()
    rt = Runtime(load_sim_config(), gs, clock, seed=seed, client_factory=hub.factory, sessions_dir=tmp_path)
    rt.start()
    return rt, clock, hub, gs


def run_for(rt: Runtime, clock: ManualClock, seconds: float) -> None:
    for _ in range(round(seconds / 0.2)):
        clock.advance(0.2)
        rt.step(clock.now())


def payloads(hub: MemoryHub, node_id: str, channel: str) -> list[dict[str, Any]]:
    return [json.loads(m.payload) for m in hub.published if m.node_id == node_id and m.channel == channel]


def test_start_connects_every_node_and_announces_boot(tmp_path):
    rt, _, hub, gs = make(tmp_path)
    assert gs.cred_calls == [None] and set(rt.credentials) == {s.node_id for s in SPECS}
    for s in SPECS:
        st = json.loads(hub.retained[f"bcs/v1/KSL/nodes/{s.node_id}/status"])
        assert st["state"] == "online" and st["reason"] is None and st["mode"] == "baseline"
        boots = [p for p in payloads(hub, s.node_id, "event") if p["kind"] == "boot"]
        assert len(boots) == 1 and boots[0]["boot_id"] == st["boot_id"]


def test_step_publishes_valid_telemetry_on_ksl_topics(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    clock.advance(30)
    rt.step(clock.now())
    tel = [m for m in hub.published if m.channel == "telemetry"]
    assert {m.node_id for m in tel} == {s.node_id for s in SPECS}
    for m in tel:
        assert m.topic == f"bcs/v1/KSL/nodes/{m.node_id}/telemetry" and not m.retain
        parse_message("telemetry", m.payload)  # raises if invalid
    assert all(p.valid for p in rt.inspector.drain())


def test_sampling_follows_the_interval(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    run_for(rt, clock, 61)
    seqs = [p["seq"] for p in payloads(hub, "WQ-01", "telemetry")]
    assert seqs == [0, 1, 2]  # t=0.2, 30.2, 60.2 at the 30 s demo baseline


def test_same_seed_gives_same_readings(tmp_path):
    a = make(tmp_path / "a", seed=7)
    b = make(tmp_path / "b", seed=7)
    for rt, clock, _, _ in (a, b):
        run_for(rt, clock, 61)

    def readings(hub: MemoryHub) -> list[Any]:
        return [
            (m.node_id, json.loads(m.payload)["readings"]) for m in hub.published if m.channel == "telemetry"
        ]

    assert readings(a[2]) == readings(b[2]) and readings(a[2])


def test_elevations_follow_node_type(tmp_path):
    rt, *_ = make(tmp_path)
    assert {nid: n.node.elevation_cm for nid, n in rt.nodes.items()} == {
        "WQ-01": 0.0,
        "WQ-02": 0.0,
        "SP-01": 80.0,
        "TG-01": 100.0,
    }


def test_low_battery_fault_sets_battery(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    rt.faults("WQ-01").inject("low_battery", {"pct": 9})
    assert rt.nodes["WQ-01"].node.battery.pct == 9
    rt.faults("SP-01").inject("low_battery", {})
    assert rt.nodes["SP-01"].node.battery.pct < 15
    run_for(rt, clock, 1)
    tel = payloads(hub, "WQ-01", "telemetry")[-1]
    assert any(f["kind"] == "battery" for f in tel["flags"])
    view = next(v for v in rt.state() if v.node_id == "WQ-01")
    assert view.battery_pct < 10 and "low_battery" in view.faults


def test_offline_fault_drops_and_recovers(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    rt.faults("WQ-02").inject("offline", {})
    run_for(rt, clock, 31)
    st = json.loads(hub.retained["bcs/v1/KSL/nodes/WQ-02/status"])
    assert st["state"] == "offline" and st["reason"] == "last_will"
    assert len(payloads(hub, "WQ-02", "telemetry")) == 0
    assert next(v for v in rt.state() if v.node_id == "WQ-02").connected is False
    rt.faults("WQ-02").clear("offline")
    run_for(rt, clock, 1)
    st = json.loads(hub.retained["bcs/v1/KSL/nodes/WQ-02/status"])
    assert st["state"] == "online"
    assert len(payloads(hub, "WQ-02", "telemetry")) == 1


def test_late_fault_holds_then_releases_on_empty_steps(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    rt.faults("TG-01").inject("late", {"delay_s": 5})
    run_for(rt, clock, 1)
    assert payloads(hub, "TG-01", "telemetry") == []
    run_for(rt, clock, 5)
    assert len(payloads(hub, "TG-01", "telemetry")) == 1


def _cmd(
    node_id: str, ctype: str, params: dict[str, Any], cid: str = "0192a000-0000-7000-8000-000000000001"
) -> bytes:
    return json.dumps(
        {
            "schema": "bcs.cmd.v1",
            "site_id": "KSL",
            "node_id": node_id,
            "command_id": cid,
            "type": ctype,
            "params": params,
            "issued_at": "2026-10-16T03:04:05.123Z",
            "expires_at": "2026-10-16T04:04:05.123Z",
            "task_id": None,
            "reason": "test",
        }
    ).encode()


def test_command_is_handled_and_acked(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    hub.deliver("WQ-01", "cmd", _cmd("WQ-01", "set_mode", {"mode": "investigation", "duration_s": 10}))
    rt.step(clock.now())
    acks = payloads(hub, "WQ-01", "ack")
    assert acks and acks[0]["status"] == "accepted"
    st = json.loads(hub.retained["bcs/v1/KSL/nodes/WQ-01/status"])
    assert st["mode"] == "investigation" and st["interval_s"] == 2
    view = next(v for v in rt.state() if v.node_id == "WQ-01")
    assert view.mode == "investigation" and view.last_command.type == "set_mode"
    assert view.last_ack.status == "accepted"
    run_for(rt, clock, 11)
    assert payloads(hub, "WQ-01", "ack")[-1]["status"] == "completed"
    downs = [p for p in rt.inspector.drain() if p.direction == "down"]
    assert downs and downs[0].channel == "cmd" and downs[0].valid


def test_invalid_command_is_ignored_but_inspected(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    hub.deliver("WQ-01", "cmd", b"{not json")
    rt.step(clock.now())
    assert payloads(hub, "WQ-01", "ack") == []
    assert any(p.direction == "down" and not p.valid for p in rt.inspector.drain())


def _config(node_id: str, version: int, baseline: int = 60) -> bytes:
    return json.dumps(
        {
            "schema": "bcs.config.v1",
            "site_id": "KSL",
            "node_id": node_id,
            "config_version": version,
            "issued_at": "2026-10-16T03:04:05.123Z",
            "demo_time_scale": True,
            "baseline_interval_s": baseline,
            "investigation_interval_s": 2,
            "anomaly": {"window": 30, "z_threshold": 3.0, "stuck_window": 10, "stuck_epsilon": {}},
            "critical_bands": {},
            "battery_low_pct": 15,
        }
    ).encode()


def test_config_is_applied_once_per_version(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    hub.deliver("SP-01", "config", _config("SP-01", 3))
    hub.deliver("SP-01", "config", _config("SP-01", 3))  # retained re-delivery on reconnect
    rt.step(clock.now())
    applied = [p for p in payloads(hub, "SP-01", "event") if p["kind"] == "config_applied"]
    assert len(applied) == 1 and applied[0]["details"]["config_version"] == 3
    assert rt.nodes["SP-01"].edge.interval_s() == 60
    assert json.loads(hub.retained["bcs/v1/KSL/nodes/SP-01/status"])["interval_s"] == 60


def test_config_for_another_node_is_ignored(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    hub.deliver("SP-01", "config", _config("WQ-01", 3))
    rt.step(clock.now())
    assert not [p for p in payloads(hub, "SP-01", "event") if p["kind"] == "config_applied"]


def test_state_has_the_k1_simnode_shape(tmp_path):
    rt, clock, _, _ = make(tmp_path)
    rt.overrides.set("WQ-02", "ph", 6.5, "hold")
    rt.faults("WQ-02").inject("stuck", {"parameter": "ph"})
    run_for(rt, clock, 1)
    v = next(v for v in rt.state() if v.node_id == "WQ-02")
    d = v.model_dump()
    assert set(d) == {
        "node_id", "node_type", "position", "zone_label", "connected", "mode", "interval_s",
        "readings", "natural", "overrides", "battery_pct", "rssi_dbm", "faults",
        "last_command", "last_ack", "source",
    }  # fmt: skip
    assert d["position"] == {"e_m": 160.0, "s_m": 250.0} and d["zone_label"] == "B3"
    assert d["source"] == "simulated" and d["connected"] is True
    assert d["readings"]["ph"] == pytest.approx(6.5, abs=0.05) and d["natural"]["ph"] != 6.5
    assert d["overrides"] == {"ph": {"value": 6.5, "behaviour": "hold"}}
    assert d["faults"] == {"stuck": {"parameter": "ph"}}


def test_registry_change_adds_moves_and_removes(tmp_path):
    gs = StubGs()
    rt, clock, hub, _ = make(tmp_path, gs=gs)
    gs.specs = [s for s in SPECS if s.node_id != "TG-01"]
    gs.specs[0] = SimNodeSpec("WQ-01", "water_quality", 70.0, 60.0, "A1", "KSL")
    gs.specs.append(SimNodeSpec("SP-02", "soil_probe", 140.0, 260.0, "B3", "KSL"))
    rt.on_registry_change()
    assert gs.cred_calls[-1] == ["SP-02"]
    assert set(rt.nodes) == {"WQ-01", "WQ-02", "SP-01", "SP-02"}
    assert "TG-01" not in rt.credentials
    assert json.loads(hub.retained["bcs/v1/KSL/nodes/TG-01/status"])["reason"] == "shutdown"
    assert (rt.nodes["WQ-01"].node.e_m, rt.nodes["WQ-01"].node.s_m) == (70.0, 60.0)
    run_for(rt, clock, 1)
    assert payloads(hub, "SP-02", "telemetry")


def test_registry_change_key_regenerated_reconnects(tmp_path):
    rt, _, hub, gs = make(tmp_path)
    old = rt.credentials["SP-01"]
    rt.on_registry_change({"change": "key_regenerated", "node_ids": ["SP-01"]})
    assert gs.cred_calls[-1] == ["SP-01"] and rt.credentials["SP-01"] != old
    assert hub.links["SP-01"].password == rt.credentials["SP-01"] and hub.links["SP-01"].connected


def test_stop_closes_cleanly(tmp_path):
    rt, _, hub, _ = make(tmp_path)
    rt.stop()
    for s in SPECS:
        st = json.loads(hub.retained[f"bcs/v1/KSL/nodes/{s.node_id}/status"])
        assert st["state"] == "offline" and st["reason"] == "shutdown" and st["mode"] is None


def test_recorder_writes_k5_and_uploads(tmp_path):
    rt, clock, _, gs = make(tmp_path)
    rt.recorder.start("rehearsal one")
    run_for(rt, clock, 31)
    meta = rt.recorder.stop()
    lines = [json.loads(x) for x in Path(meta.path).read_text(encoding="utf-8").splitlines()]
    head = lines[0]
    assert head["kind"] == "bcs.sim-session.v1" and head["name"] == "rehearsal one" and head["seed"] == 42
    assert {n["node_id"] for n in head["nodes"]} == {s.node_id for s in SPECS}
    assert set(head["nodes"][0]) == {"node_id", "node_type", "e_m", "s_m"}
    body = lines[1:]
    assert body and all(set(x) == {"t_ms", "node_id", "channel", "payload"} for x in body)
    assert {x["channel"] for x in body} <= {"telemetry", "event"}
    assert body[0]["t_ms"] >= 0 and body[-1]["t_ms"] <= 31_000
    assert Path(meta.path).parent == tmp_path
    assert meta.message_count == len(body) and meta.uploaded is True
    up_meta, up_path = gs.uploads[0]
    assert up_meta["id"] == meta.id and up_meta["kind"] == "recording" and up_path == Path(meta.path)
    assert up_meta["message_count"] == len(body)


def test_recording_starts_while_the_runtime_steps(tmp_path):
    """Recorder.start must not hold its lock while it asks the runtime for the node list: a step holds the
    runtime lock and publishes into the recorder (lock-order inversion -> deadlock)."""
    import threading
    import time

    rt, clock, _, _ = make(tmp_path)
    original = rt.recorder._nodes

    def slow_nodes() -> list[dict[str, Any]]:
        time.sleep(0.05)  # widen the window: the stepping thread takes the runtime lock and publishes
        return original()

    rt.recorder._nodes = slow_nodes
    stop = threading.Event()
    step_lock = threading.Lock()  # the stepper and the main thread share the ManualClock

    def stepper() -> None:
        while not stop.is_set():
            with step_lock:
                clock.advance(30)  # every node samples (and publishes into the recorder) on every step
                now = clock.now()
            rt.step(now)

    t = threading.Thread(target=stepper, daemon=True)
    t.start()
    try:
        for i in range(5):
            done = threading.Event()

            def record(i: int = i, done: threading.Event = done) -> None:
                rt.recorder.start(f"r{i}")
                rt.recorder.stop()
                done.set()

            threading.Thread(target=record, daemon=True).start()
            assert done.wait(5), "recording start/stop deadlocked with the stepping runtime"
    finally:
        stop.set()
        t.join(5)


def test_recorder_keeps_local_file_when_upload_fails(tmp_path):
    gs = StubGs()
    gs.fail_upload = True
    rt, clock, _, _ = make(tmp_path, gs=gs)
    rt.recorder.start("r")
    run_for(rt, clock, 1)
    meta = rt.recorder.stop()
    assert meta.uploaded is False and meta.upload_error and Path(meta.path).is_file()


def test_replay_restamps(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    rt.recorder.start("r1")
    run_for(rt, clock, 61)
    meta = rt.recorder.stop()
    original = [
        json.loads(x)["payload"] for x in Path(meta.path).read_text(encoding="utf-8").splitlines()[1:]
    ]
    orig_boot = {p["boot_id"] for p in original}
    start = len(hub.published)
    rt.replayer.replay(meta.path)
    assert rt.replayer.active
    replay_start = clock.now()
    run_for(rt, clock, 61)
    replayed = [m for m in hub.published[start:] if json.loads(m.payload).get("replay") is True]
    assert len(replayed) == len(original)
    tel = [json.loads(m.payload) for m in replayed if m.channel == "telemetry" and m.node_id == "WQ-01"]
    assert [p["seq"] for p in tel] == [0, 1, 2]
    assert len({p["boot_id"] for p in tel}) == 1 and not {p["boot_id"] for p in tel} & orig_boot
    assert all(p["source"] == "simulated" for p in tel)
    assert all(datetime.fromisoformat(p["sampled_at"]) >= replay_start for p in tel)
    for m in replayed:
        parse_message(m.channel, m.payload)
    for nid in {m.node_id for m in replayed}:
        ev = [json.loads(m.payload)["seq"] for m in replayed if m.node_id == nid and m.channel == "event"]
        assert ev == list(range(len(ev)))  # events re-numbered on their own counter
    # live telemetry of replayed nodes pauses during the replay
    window = hub.published[start:]
    last = max(i for i, m in enumerate(window) if json.loads(m.payload).get("replay") is True)
    live = [m for m in window[:last] if m.channel == "telemetry" and not json.loads(m.payload)["replay"]]
    assert live == []
    run_for(rt, clock, 1)
    assert not rt.replayer.active


def test_supervisor_retries_until_ground_station_answers(tmp_path):
    import time

    from bcs_sim.clock import SystemClock
    from bcs_sim.gs_client import GsError
    from bcs_sim.runtime import RuntimeSupervisor

    class FlakyGs(StubGs):
        calls = 0

        def registry(self) -> list[SimNodeSpec]:
            FlakyGs.calls += 1
            if FlakyGs.calls < 3:
                raise GsError("GET /internal/sim/registry: HTTP 501")
            return super().registry()

    hub = MemoryHub()
    gs = FlakyGs()

    def factory() -> Runtime:
        return Runtime(
            load_sim_config(), gs, SystemClock(), 1, client_factory=hub.factory, sessions_dir=tmp_path
        )

    sup = RuntimeSupervisor(factory, retry_s=0.05, period_s=0.05)
    sup.start()
    try:
        deadline = time.monotonic() + 5
        while not any(m.channel == "telemetry" for m in hub.published) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert FlakyGs.calls >= 3 and sup.runtime is not None and sup.runtime.started
        assert any(m.channel == "telemetry" for m in hub.published)
    finally:
        sup.stop()
    assert sup.runtime.started is False


def test_published_event_seqs_are_unique_per_boot(tmp_path):
    rt, clock, hub, _ = make(tmp_path)
    hub.deliver("WQ-01", "config", _config("WQ-01", 1))
    rt.faults("WQ-01").inject("low_battery", {"pct": 5})
    rt.overrides.set("WQ-01", "do_mg_l", 0.5, "hold")
    run_for(rt, clock, 61)
    events = payloads(hub, "WQ-01", "event")
    kinds = {p["kind"] for p in events}
    assert {"boot", "config_applied", "battery_low"} <= kinds
    keys = [(p["boot_id"], p["seq"]) for p in events]
    assert len(set(keys)) == len(keys)
    assert [p["seq"] for p in events] == list(range(len(events)))
