"""Sentinel Protocol v1 contract tests: one valid and one invalid case per rule in addendum G2-G4."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from bcs_protocol.topics import parse_topic, topic
from bcs_protocol.validate import (
    READING_KEYS,
    VALIDATION_RANGES,
    ProtocolError,
    dedupe_key,
    parse_message,
)

PKG = Path(__file__).resolve().parents[1]

VALID = {
    "schema": "bcs.telemetry.v1",
    "site_id": "KSL",
    "node_id": "WQ-02",
    "node_type": "water_quality",
    "boot_id": "9f2c41ab07de",
    "seq": 418,
    "sampled_at": "2026-10-16T03:04:05.123Z",
    "mode": "investigation",
    "readings": {"salinity_psu": 27.4, "turbidity_ntu": 162.8, "do_mg_l": 4.12, "temp_c": 30.45, "ph": 7.62},
    "health": {"battery_pct": 86.5, "rssi_dbm": -63, "uptime_s": 5412, "fw_version": "sim-1.0.0"},
    "flags": [{"parameter": "turbidity_ntu", "kind": "threshold", "score": 1.0}],
    "source": "simulated",
    "replay": False,
}

SOIL = {
    **VALID,
    "node_id": "SP-01",
    "node_type": "soil_probe",
    "readings": {"porewater_salinity_psu": 31.2, "soil_moisture_pct": 64.5},
    "flags": [],
}
TIDE = {
    **VALID,
    "node_id": "TG-01",
    "node_type": "tide_gauge",
    "readings": {"water_level_cm": -120},
    "flags": [],
}

STATUS = {
    "schema": "bcs.status.v1",
    "site_id": "KSL",
    "node_id": "WQ-01",
    "state": "offline",
    "at": "2026-10-16T03:00:00.000Z",
    "reason": "last_will",
    "mode": None,
    "interval_s": None,
    "fw_version": "sim-1.0.0",
    "boot_id": "9f2c41ab07de",
    "source": "simulated",
    "replay": False,
}

EVENT = {
    "schema": "bcs.event.v1",
    "site_id": "KSL",
    "node_id": "WQ-02",
    "boot_id": "9f2c41ab07de",
    "seq": 3,
    "at": "2026-10-16T03:04:05.123Z",
    "kind": "anomaly",
    "parameter": "turbidity_ntu",
    "value": 162.8,
    "score": 4.2,
    "details": {"window": 30},
    "source": "simulated",
    "replay": False,
}

ACK = {
    "schema": "bcs.ack.v1",
    "site_id": "KSL",
    "node_id": "WQ-01",
    "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
    "at": "2026-10-16T03:00:01.000Z",
    "status": "accepted",
    "reason": None,
    "source": "simulated",
    "replay": False,
}

CMD = {
    "schema": "bcs.cmd.v1",
    "site_id": "KSL",
    "node_id": "WQ-01",
    "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
    "type": "set_mode",
    "params": {"mode": "investigation", "duration_s": 120},
    "issued_at": "2026-10-16T03:00:00.000Z",
    "expires_at": "2026-10-16T03:00:30.000Z",
    "task_id": None,
    "reason": "test",
}

CONFIG = {
    "schema": "bcs.config.v1",
    "site_id": "KSL",
    "node_id": "WQ-01",
    "config_version": 2,
    "issued_at": "2026-10-16T03:00:00.000Z",
    "demo_time_scale": True,
    "baseline_interval_s": 30,
    "investigation_interval_s": 2,
    "anomaly": {"window": 30, "z_threshold": 3.0, "stuck_window": 10, "stuck_epsilon": {"ph": 0.005}},
    "critical_bands": {"do_mg_l": {"min": 2.0}, "ph": {"min": 6.5, "max": 9.0}},
    "battery_low_pct": 15,
}


def _dump(d) -> bytes:
    return json.dumps(d).encode()


def _fails(channel: str, d: dict, needle: str) -> None:
    with pytest.raises(ProtocolError) as e:
        parse_message(channel, _dump(d))
    assert any(needle in err for err in e.value.errors), e.value.errors


def _mut(base: dict, fn) -> dict:
    d = copy.deepcopy(base)
    fn(d)
    return d


# --- telemetry (G2, G3, G4) ---------------------------------------------------------------------


def test_valid_telemetry_parses_to_water_quality_model():
    m = parse_message("telemetry", json.dumps(VALID).encode())
    assert m.root.node_type == "water_quality" and m.root.readings.turbidity_ntu == 162.8


@pytest.mark.parametrize("d", [SOIL, TIDE], ids=["soil_probe", "tide_gauge"])
def test_other_node_types_parse(d):
    m = parse_message("telemetry", _dump(d))
    assert m.root.node_type == d["node_type"]


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d["readings"].pop("ph"), "ph"),
        (lambda d: d["readings"].update(ph=14.5), "ph"),
        (lambda d: d["readings"].update(ph=-0.1), "ph"),
        (lambda d: d["readings"].update(salinity_psu=60.1), "salinity_psu"),
        (lambda d: d["readings"].update(turbidity_ntu=4000.1), "turbidity_ntu"),
        (lambda d: d["readings"].update(do_mg_l=-1), "do_mg_l"),
        (lambda d: d["readings"].update(temp_c=45.5), "temp_c"),
        (lambda d: d["readings"].update(extra_reading=1), "extra_reading"),
        (lambda d: d["readings"].update(ph="7"), "ph"),
        (lambda d: d.update(node_id="XX-01"), "node_id"),
        (lambda d: d.update(node_id="WQ-1"), "node_id"),
        (lambda d: d.update(site_id="ksl"), "site_id"),
        (lambda d: d.update(site_id="KSLX"), "site_id"),
        (lambda d: d.update(boot_id="NOT-HEX"), "boot_id"),
        (lambda d: d.update(boot_id="9F2C41AB07DE"), "boot_id"),
        (lambda d: d.update(extra=1), "extra"),
        (lambda d: d.update(node_type="soil_probe"), "readings"),
        (lambda d: d.update(node_type="weather"), "node_type"),
        (lambda d: d.update(schema="bcs.telemetry.v2"), "schema"),
        (lambda d: d.update(seq=-1), "seq"),
        (lambda d: d.update(seq=1.5), "seq"),
        (lambda d: d.update(sampled_at="2026-10-16T03:04:05Z"), "sampled_at"),
        (lambda d: d.update(sampled_at="2026-10-16T11:04:05.123+08:00"), "sampled_at"),
        (lambda d: d.update(sampled_at="2026-13-16T03:04:05.123Z"), "sampled_at"),
        (lambda d: d.update(mode="standby"), "mode"),
        (lambda d: d.update(source="cloud"), "source"),
        (lambda d: d.update(replay="no"), "replay"),
        (lambda d: d["health"].update(battery_pct=100.5), "battery_pct"),
        (lambda d: d["health"].update(rssi_dbm=1), "rssi_dbm"),
        (lambda d: d["health"].update(rssi_dbm=-121), "rssi_dbm"),
        (lambda d: d["health"].update(uptime_s=-1), "uptime_s"),
        (lambda d: d["health"].update(fw_version="x" * 33), "fw_version"),
        (lambda d: d["health"].pop("rssi_dbm"), "rssi_dbm"),
        (lambda d: d["flags"][0].update(parameter="bogus"), "parameter"),
        (lambda d: d["flags"][0].update(kind="boom"), "kind"),
        (lambda d: d["flags"][0].update(score="hi"), "score"),
        (lambda d: d.pop("flags"), "flags"),
    ],
)
def test_invalid_telemetry_is_rejected_with_reason(mutate, needle):
    d = copy.deepcopy(VALID)
    mutate(d)
    with pytest.raises(ProtocolError) as e:
        parse_message("telemetry", json.dumps(d).encode())
    assert any(needle in err for err in e.value.errors)


def test_flag_parameter_may_be_battery_pct():
    d = copy.deepcopy(VALID)
    d["flags"] = [{"parameter": "battery_pct", "kind": "battery", "score": 12}]
    assert parse_message("telemetry", _dump(d)).root.flags[0].parameter == "battery_pct"


@pytest.mark.parametrize(
    "base,key,bad",
    [
        (SOIL, "porewater_salinity_psu", 120.5),
        (SOIL, "soil_moisture_pct", 100.1),
        (TIDE, "water_level_cm", 501),
        (TIDE, "water_level_cm", -501),
    ],
)
def test_out_of_range_other_types(base, key, bad):
    _fails("telemetry", _mut(base, lambda d: d["readings"].update({key: bad})), key)


def test_range_boundaries_are_inclusive():
    d = copy.deepcopy(VALID)
    d["readings"].update(salinity_psu=0, turbidity_ntu=4000, do_mg_l=20, temp_c=45, ph=14)
    parse_message("telemetry", _dump(d))
    d = copy.deepcopy(TIDE)
    d["readings"] = {"water_level_cm": 500}
    parse_message("telemetry", _dump(d))


def test_reading_tables_match_g4():
    assert READING_KEYS == {
        "water_quality": ("salinity_psu", "turbidity_ntu", "do_mg_l", "temp_c", "ph"),
        "soil_probe": ("porewater_salinity_psu", "soil_moisture_pct"),
        "tide_gauge": ("water_level_cm",),
    }
    assert VALIDATION_RANGES == {
        "salinity_psu": (0, 60),
        "turbidity_ntu": (0, 4000),
        "do_mg_l": (0, 20),
        "temp_c": (0, 45),
        "ph": (0, 14),
        "porewater_salinity_psu": (0, 120),
        "soil_moisture_pct": (0, 100),
        "water_level_cm": (-500, 500),
    }


def test_json_schema_ranges_agree_with_validation_ranges():
    defs = json.loads((PKG / "schemas" / "telemetry.schema.json").read_text(encoding="utf-8"))["$defs"]
    props = {}
    for name in ("WaterQualityReadings", "SoilProbeReadings", "TideGaugeReadings"):
        props.update(defs[name]["properties"])
    assert {k: (p["minimum"], p["maximum"]) for k, p in props.items()} == VALIDATION_RANGES


def test_ts_reading_keys_match_python():
    src = (PKG / "ts" / "index.ts").read_text(encoding="utf-8")
    for node_type, keys in READING_KEYS.items():
        m = re.search(rf"{node_type}:\s*\[([^\]]*)\]", src)
        assert m, node_type
        assert tuple(re.findall(r'"([a-z_]+)"', m.group(1))) == keys


# --- status -------------------------------------------------------------------------------------


def test_status_last_will_shape():
    m = parse_message("status", json.dumps(STATUS).encode())
    assert m.state == "offline"


def test_status_online_shape():
    d = {**STATUS, "state": "online", "reason": None, "mode": "baseline", "interval_s": 30}
    m = parse_message("status", _dump(d))
    assert m.mode == "baseline" and m.interval_s == 30


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.update(state="sleeping"), "state"),
        (lambda d: d.update(reason="crashed"), "reason"),
        (lambda d: d.update(mode="turbo"), "mode"),
        (lambda d: d.update(at="yesterday"), "at"),
        (lambda d: d.update(schema="bcs.event.v1"), "schema"),
        (lambda d: d.pop("fw_version"), "fw_version"),
        (lambda d: d.update(boot_id="zz"), "boot_id"),
        (lambda d: d.update(extra=True), "extra"),
    ],
)
def test_invalid_status(mutate, needle):
    _fails("status", _mut(STATUS, mutate), needle)


# --- event --------------------------------------------------------------------------------------


def test_valid_event_and_nullable_fields():
    assert parse_message("event", _dump(EVENT)).kind == "anomaly"
    d = {**EVENT, "kind": "boot", "parameter": None, "value": None, "score": None, "details": {}}
    assert parse_message("event", _dump(d)).parameter is None


@pytest.mark.parametrize(
    "kind", ["anomaly", "threshold", "stuck", "battery_low", "boot", "config_applied", "malformed_input"]
)
def test_all_node_event_kinds_accepted(kind):
    parse_message("event", _dump({**EVENT, "kind": kind}))


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.update(kind="malformed"), "kind"),  # Ground Station kind, not a node kind
        (lambda d: d.update(kind="offline"), "kind"),
        (lambda d: d.update(seq=-2), "seq"),
        (lambda d: d.update(details="text"), "details"),
        (lambda d: d.update(details={"blob": "x" * 2100}), "details"),
        (lambda d: d.update(value="high"), "value"),
        (lambda d: d.pop("boot_id"), "boot_id"),
        (lambda d: d.update(extra=1), "extra"),
    ],
)
def test_invalid_event(mutate, needle):
    _fails("event", _mut(EVENT, mutate), needle)


# --- ack ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["accepted", "rejected", "completed", "expired"])
def test_valid_ack(status):
    assert parse_message("ack", _dump({**ACK, "status": status})).status == status


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.update(status="pending"), "status"),
        (lambda d: d.update(command_id="not-a-uuid"), "command_id"),
        (lambda d: d.update(reason=5), "reason"),
        (lambda d: d.update(at="2026-10-16"), "at"),
        (lambda d: d.update(extra=1), "extra"),
    ],
)
def test_invalid_ack(mutate, needle):
    _fails("ack", _mut(ACK, mutate), needle)


# --- cmd ----------------------------------------------------------------------------------------


def test_set_mode_investigation_requires_duration():
    cmd = {
        "schema": "bcs.cmd.v1",
        "site_id": "KSL",
        "node_id": "WQ-01",
        "command_id": "01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f",
        "type": "set_mode",
        "params": {"mode": "investigation"},
        "issued_at": "2026-10-16T03:00:00.000Z",
        "expires_at": "2026-10-16T03:00:30.000Z",
        "task_id": None,
        "reason": "test",
    }
    with pytest.raises(ProtocolError) as e:
        parse_message("cmd", json.dumps(cmd).encode())
    assert any("duration_s" in err for err in e.value.errors)


def test_valid_commands():
    assert parse_message("cmd", _dump(CMD)).params["duration_s"] == 120
    base = _mut(CMD, lambda d: d.update(params={"mode": "baseline"}))
    parse_message("cmd", _dump(base))  # duration optional for baseline
    parse_message("cmd", _dump(_mut(CMD, lambda d: d["params"].update(interval_s=2.5))))
    parse_message("cmd", _dump(_mut(CMD, lambda d: d.update(type="ping", params={}))))
    parse_message("cmd", _dump(_mut(CMD, lambda d: d.update(type="reboot", params={}))))
    parse_message(
        "cmd",
        _dump(_mut(CMD, lambda d: d.update(type="set_config", params={"baseline_interval_s": 60}))),
    )
    parse_message("cmd", _dump(_mut(CMD, lambda d: d.update(task_id="01928f3e-5b7c-7d2a-9c4e-0a1b2c3d4e5f"))))


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.update(type="format_disk"), "type"),
        (lambda d: d.update(command_id="123"), "command_id"),
        (lambda d: d.update(reason="r" * 201), "reason"),
        (lambda d: d.update(params={"mode": "sleep", "duration_s": 5}), "mode"),
        (lambda d: d.update(params={"duration_s": 5}), "mode"),
        (lambda d: d["params"].update(duration_s=0), "duration_s"),
        (lambda d: d["params"].update(duration_s="long"), "duration_s"),
        (lambda d: d["params"].update(interval_s=-1), "interval_s"),
        (lambda d: d["params"].update(bogus=1), "bogus"),
        (lambda d: d.update(type="ping", params={"x": 1}), "params"),
        (lambda d: d.update(type="reboot", params={"x": 1}), "params"),
        (lambda d: d.update(type="set_config", params={"nonsense": 1}), "nonsense"),
        (lambda d: d.update(type="set_config", params={"baseline_interval_s": 0}), "baseline_interval_s"),
        (lambda d: d.update(expires_at="soon"), "expires_at"),
        (lambda d: d.pop("issued_at"), "issued_at"),
        (lambda d: d.update(task_id=7), "task_id"),
        (lambda d: d.update(extra=1), "extra"),
    ],
)
def test_invalid_cmd(mutate, needle):
    _fails("cmd", _mut(CMD, mutate), needle)


# --- config -------------------------------------------------------------------------------------


def test_valid_config():
    m = parse_message("config", _dump(CONFIG))
    assert m.config_version == 2 and m.critical_bands.do_mg_l.min == 2.0 and m.critical_bands.ph.max == 9.0


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.update(config_version=-1), "config_version"),
        (lambda d: d.update(demo_time_scale="yes"), "demo_time_scale"),
        (lambda d: d.update(baseline_interval_s=0), "baseline_interval_s"),
        (lambda d: d["anomaly"].update(stuck_epsilon={"bogus": 1}), "bogus"),
        (lambda d: d["anomaly"].update(window=0), "window"),
        (lambda d: d["critical_bands"].update(ph={"lo": 1}), "lo"),
        (lambda d: d.update(battery_low_pct=101), "battery_low_pct"),
        (lambda d: d.update(schema="bcs.config.v2"), "schema"),
        (lambda d: d.update(extra=1), "extra"),
    ],
)
def test_invalid_config(mutate, needle):
    _fails("config", _mut(CONFIG, mutate), needle)


# --- payload / channel level --------------------------------------------------------------------


def test_non_json_payload_is_protocol_error():
    with pytest.raises(ProtocolError):
        parse_message("telemetry", b"\xff\x00garbage")


def test_non_object_json_and_unknown_channel():
    with pytest.raises(ProtocolError):
        parse_message("telemetry", b"[1,2,3]")
    with pytest.raises(ProtocolError):
        parse_message("nope", _dump(VALID))


def test_schema_const_must_match_channel():
    _fails("status", VALID, "schema")


# --- topics -------------------------------------------------------------------------------------


def test_topic_round_trip_and_foreign_topic():
    assert topic("KSL", "WQ-01", "telemetry") == "bcs/v1/KSL/nodes/WQ-01/telemetry"
    assert parse_topic("bcs/v1/KSL/nodes/WQ-01/ack") == ("KSL", "WQ-01", "ack")
    with pytest.raises(ValueError):
        parse_topic("other/x")


@pytest.mark.parametrize(
    "bad",
    [
        "bcs/v2/KSL/nodes/WQ-01/ack",
        "bcs/v1/KSL/nodes/WQ-01/bogus",
        "bcs/v1/KSL/nodes/WQ-01",
        "bcs/v1/KSL/nodes/WQ-01/ack/extra",
        "bcs/v1/ksl/nodes/WQ-01/ack",
        "bcs/v1/KSL/nodes/XX-01/ack",
        "",
    ],
)
def test_parse_topic_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_topic(bad)


def test_topic_rejects_bad_parts():
    with pytest.raises(ValueError):
        topic("KSL", "WQ-01", "bogus")
    with pytest.raises(ValueError):
        topic("ksl", "WQ-01", "ack")


@pytest.mark.parametrize("channel", ["telemetry", "event", "status", "ack", "cmd", "config"])
def test_every_channel_round_trips(channel):
    assert parse_topic(topic("KSL", "SP-12", channel)) == ("KSL", "SP-12", channel)


# --- dedupe (G5.6) ------------------------------------------------------------------------------


def test_dedupe_key_telemetry_and_event():
    assert dedupe_key(parse_message("telemetry", _dump(VALID))) == ("WQ-02", "9f2c41ab07de", 418)
    assert dedupe_key(parse_message("event", _dump(EVENT))) == ("WQ-02", "9f2c41ab07de", 3)


# --- cross-field rules: status mode (G3) and replay/source (G2) ----------------------------------


def test_offline_status_requires_null_mode():
    _fails("status", _mut(STATUS, lambda d: d.update(mode="investigation")), "mode")
    parse_message("status", _dump(STATUS))  # offline with mode null
    online = {**STATUS, "state": "online", "reason": None, "mode": "investigation", "interval_s": 2}
    assert parse_message("status", _dump(online)).mode == "investigation"


@pytest.mark.parametrize(
    "channel,base",
    [("telemetry", VALID), ("status", STATUS), ("event", EVENT), ("ack", ACK)],
)
def test_replay_only_for_simulated_source(channel, base):
    _fails(channel, {**base, "source": "hardware", "replay": True}, "replay")
    parse_message(channel, _dump({**base, "source": "simulated", "replay": True}))
    parse_message(channel, _dump({**base, "source": "hardware", "replay": False}))
