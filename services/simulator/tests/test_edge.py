import math
import secrets
from datetime import UTC, datetime, timedelta

import numpy as np
from bcs_protocol.generated.cmd_schema import Command
from bcs_protocol.generated.config_schema import NodeConfig
from bcs_protocol.timefmt import to_iso
from bcs_sim.clock import ManualClock
from bcs_sim.config import SimConfig
from bcs_sim.edge import EdgeLogic
from bcs_sim.environment import Environment
from bcs_sim.nodes.battery import Battery
from bcs_sim.nodes.models import SimNode, produce_readings
from bcs_sim.overrides import Overrides
from bcs_sim.scenarios import ScenarioBook, grid_zone_bounds

T0 = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)
WQ_NORMAL = {"salinity_psu": 28.0, "turbidity_ntu": 12.0, "do_mg_l": 6.5, "temp_c": 29.0, "ph": 7.8}
HEALTH = {"battery_pct": 100.0, "rssi_dbm": -70.0, "uptime_s": 10.0, "fw_version": "sim-1.0.0"}


def _config() -> NodeConfig:
    return NodeConfig.model_validate(
        {
            "schema": "bcs.config.v1",
            "site_id": "SIT",
            "node_id": "WQ-01",
            "config_version": 1,
            "issued_at": to_iso(T0),
            "demo_time_scale": True,
            "baseline_interval_s": 30,
            "investigation_interval_s": 2,
            "anomaly": {
                "window": 30,
                "z_threshold": 3.0,
                "stuck_window": 10,
                "stuck_epsilon": {
                    "salinity_psu": 0.01,
                    "turbidity_ntu": 0.01,
                    "do_mg_l": 0.005,
                    "temp_c": 0.005,
                    "ph": 0.005,
                },
            },
            "critical_bands": {
                "do_mg_l": {"min": 2.0},
                "ph": {"min": 6.5, "max": 9.0},
                "turbidity_ntu": {"max": 100},
                "salinity_psu": {"max": 45},
                "temp_c": {"max": 36},
            },
            "battery_low_pct": 15.0,
        }
    )


def edge(battery: Battery | None = None) -> EdgeLogic:
    node = SimNode("WQ-01", "water_quality", 250.0, 250.0, 0.0, seed=1)
    if battery is not None:
        node.battery = battery
    return EdgeLogic(node, _config(), ManualClock(T0))


def cmd(type_: str, params: dict, expires_at: datetime | None = None) -> Command:
    return Command.model_validate(
        {
            "schema": "bcs.cmd.v1",
            "site_id": "SIT",
            "node_id": "WQ-01",
            "command_id": "01900000-0000-7000-8000-" + secrets.token_hex(6),
            "type": type_,
            "params": params,
            "issued_at": to_iso(T0),
            "expires_at": to_iso(expires_at or T0 + timedelta(seconds=60)),
            "task_id": None,
            "reason": "test",
        }
    )


def feed(e: EdgeLogic, param: str, values: list[float]) -> None:
    for v in values:
        e.sample({**WQ_NORMAL, param: v}, HEALTH, T0)


def test_set_mode_investigation_acks_then_auto_returns_with_completed():
    e = edge()
    acks = e.handle(cmd("set_mode", {"mode": "investigation", "duration_s": 180}), T0)
    assert [a.status for a in acks] == ["accepted"] and e.interval_s() == 2
    assert [a.status for a in e.tick(T0 + timedelta(seconds=180))] == ["completed"] and e.interval_s() == 30


def test_retried_set_mode_does_not_supersede_itself():
    e = edge()
    c = cmd("set_mode", {"mode": "investigation", "duration_s": 180})
    assert [a.status for a in e.handle(c, T0)] == ["accepted"]
    again = e.handle(c, T0 + timedelta(seconds=5))  # the Ground Station's 5 s retry, same command_id
    assert [(a.command_id, a.status) for a in again] == [(c.command_id, "accepted")]
    newer = cmd("set_mode", {"mode": "investigation", "duration_s": 180})
    acks = e.handle(newer, T0 + timedelta(seconds=10))
    assert [(a.command_id, a.status, a.reason) for a in acks] == [
        (c.command_id, "completed", "superseded"),
        (newer.command_id, "accepted", None),
    ]


def test_expired_command_is_acked_expired():
    c = cmd("set_mode", {"mode": "investigation", "duration_s": 60}, expires_at=T0 - timedelta(seconds=1))
    assert [a.status for a in edge().handle(c, T0)] == ["expired"]


def test_spike_flag_on_z_above_3():
    e = edge()
    feed(e, "turbidity_ntu", [12.0 + 0.5 * math.sin(i) for i in range(30)])
    tel, events = e.sample({**WQ_NORMAL, "turbidity_ntu": 40.0}, HEALTH, T0)
    assert ("turbidity_ntu", "spike") in {(f.parameter, f.kind) for f in tel.root.flags}
    assert events[0].kind == "anomaly"


def test_stuck_flag_after_10_identical_samples():
    e = edge()
    feed(e, "salinity_psu", [28.0] * 10)
    assert ("salinity_psu", "stuck") in {(f.parameter, f.kind) for f in e.last.root.flags}


def test_threshold_flag_on_entering_critical_band():
    e = edge()
    feed(e, "do_mg_l", [5.0] * 5)
    tel, events = e.sample({**WQ_NORMAL, "do_mg_l": 1.5}, HEALTH, T0)
    assert ("do_mg_l", "threshold") in {(f.parameter, f.kind) for f in tel.root.flags}
    assert "threshold" in [ev.kind for ev in events if ev.parameter == "do_mg_l"]
    # staying beyond the threshold does not re-flag
    tel2, _ = e.sample({**WQ_NORMAL, "do_mg_l": 1.4}, HEALTH, T0)
    assert ("do_mg_l", "threshold") not in {(f.parameter, f.kind) for f in tel2.root.flags}


def test_ph_threshold_on_both_sides():
    e = edge()
    flagged = []
    for ph in [7.6, 6.2, 6.0, 7.5, 9.3, 9.4, 7.6, 6.4]:
        tel, _ = e.sample({**WQ_NORMAL, "ph": ph}, HEALTH, T0)
        flagged.append(("ph", "threshold") in {(f.parameter, f.kind) for f in tel.root.flags})
    # below 6.5 flags, staying low does not, back within [6.5, 9.0] re-arms, above 9.0 flags, and so on
    assert flagged == [False, True, False, False, True, False, False, True]
    # the bounds themselves are not critical
    e2 = edge()
    for ph in [6.5, 9.0]:
        tel, _ = e2.sample({**WQ_NORMAL, "ph": ph}, HEALTH, T0)
        assert ("ph", "threshold") not in {(f.parameter, f.kind) for f in tel.root.flags}


def test_battery_aware_interval_doubles_below_15():
    e = edge(battery=Battery(start_pct=14.0))
    assert e.interval_s() == 60


def test_battery_flag_and_event_when_low():
    e = edge(battery=Battery(start_pct=14.0))
    tel, events = e.sample(WQ_NORMAL, HEALTH, T0)
    assert ("battery_pct", "battery") in {(f.parameter, f.kind) for f in tel.root.flags}
    assert "battery_low" in [ev.kind for ev in events]


def test_sequence_increments_and_reboot_changes_boot_id():
    e = edge()
    a, _ = e.sample(WQ_NORMAL, HEALTH, T0)
    b, _ = e.sample(WQ_NORMAL, HEALTH, T0)
    assert b.root.seq == a.root.seq + 1
    acks = e.handle(cmd("reboot", {}), T0)
    assert [x.status for x in acks] == ["accepted"]
    assert e.node.boot_id != a.root.boot_id and e.node.seq == 0


def test_messages_are_simulated_and_not_replay():
    e = edge()
    tel, _ = e.sample(WQ_NORMAL, HEALTH, T0)
    assert tel.root.source == "simulated" and tel.root.replay is False
    ack = e.handle(cmd("ping", {}), T0)[0]
    assert ack.source == "simulated" and ack.replay is False


def test_due_follows_interval():
    e = edge()
    assert e.due(T0)
    e.sample(WQ_NORMAL, HEALTH, T0)
    assert not e.due(T0 + timedelta(seconds=29)) and e.due(T0 + timedelta(seconds=30))


def test_set_config_applies_and_emits_config_applied():
    e = edge()
    acks = e.handle(cmd("set_config", {"baseline_interval_s": 10, "config_version": 2}), T0)
    assert [a.status for a in acks] == ["accepted"] and e.interval_s() == 10
    assert [ev.kind for ev in e.drain_events()] == ["config_applied"]


def test_set_mode_investigation_without_duration_is_rejected():
    assert [a.status for a in edge().handle(cmd("set_mode", {"mode": "investigation"}), T0)] == ["rejected"]


def _pipeline(scenario=None, zone="C3"):
    clock = ManualClock(T0)
    env = Environment(SimConfig(), 3, clock)
    env.set_nature(diurnal=False, noise=False)
    book, ov = ScenarioBook(clock), Overrides(clock)
    node = SimNode("WQ-01", "water_quality", 250.0, 250.0, 0.0, seed=1)
    bounds = grid_zone_bounds()
    if scenario:
        book.apply(zone, scenario, ramp_s=0)
        clock.advance(10)
    at = clock.now()
    rng = np.random.default_rng(0)
    return produce_readings(node, env, book, ov, bounds, at, rng), env, node, at


def test_pipeline_heat_stress_lowers_do_through_solubility():
    base, *_ = _pipeline()
    heat, *_ = _pipeline("heat_stress")
    assert heat["temp_c"] > base["temp_c"] + 3 and heat["do_mg_l"] < base["do_mg_l"]


def test_pipeline_low_oxygen_blends_fraction_and_sediment_offset_is_additive():
    base, *_ = _pipeline()
    low, *_ = _pipeline("low_oxygen")
    assert low["do_mg_l"] < base["do_mg_l"] * 0.75
    sed, *_ = _pipeline("sediment_runoff")
    assert abs((base["do_mg_l"] - sed["do_mg_l"]) - 1.0) < 0.1


def test_events_have_their_own_distinct_seq_per_boot():
    e = edge(battery=Battery(start_pct=14.0))
    boot = e.boot_event(T0)
    e.apply_config(_config())
    (applied,) = e.drain_events()
    feed(e, "do_mg_l", [5.0] * 5)
    _, flagged = e.sample({**WQ_NORMAL, "do_mg_l": 1.5, "ph": 9.5}, HEALTH, T0)
    kinds = [ev.kind for ev in flagged]
    assert "threshold" in kinds and "battery_low" not in kinds  # battery_low fired during feed
    events = [boot, applied, *flagged]
    seqs = [ev.seq for ev in events]
    assert len(set(seqs)) == len(seqs) and seqs == sorted(seqs) and seqs[0] == 0
    assert all(ev.boot_id == boot.boot_id for ev in events)
    # telemetry seq is independent of the event counter
    assert e.last.root.seq == 5


def test_reboot_restarts_event_seq():
    e = edge()
    e.boot_event(T0)
    e.boot_event(T0)
    e.handle(cmd("reboot", {}), T0)
    (boot,) = e.drain_events()
    assert boot.kind == "boot" and boot.seq == 0 and e.node.event_seq == 1
