import json
from datetime import UTC, datetime, timedelta

import pytest
from bcs_sim.clock import ManualClock
from bcs_sim.faults import FaultSet, OutgoingMsg

T0 = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)


def msg(n: int) -> OutgoingMsg:
    payload = json.dumps({"seq": n, "readings": {"ph": 7.8}}).encode()
    return OutgoingMsg(node_id="WQ-01", channel="telemetry", payload=payload, seq=n)


def is_json(b: bytes) -> bool:
    try:
        json.loads(b)
    except ValueError:
        return False
    return True


def test_stuck_holds_first_value():
    f = FaultSet(1)
    f.inject("stuck", {"parameter": "ph"})
    assert f.shape_readings({"ph": 7.8}, T0)["ph"] == f.shape_readings({"ph": 8.1}, T0)["ph"] == 7.8


def test_duplicate_and_out_of_order():
    f = FaultSet(1)
    f.inject("duplicate", {})
    assert [m.seq for m in f.shape_outgoing([msg(1), msg(2)], T0)] == [1, 1, 2, 2]
    f.clear("duplicate")
    f.inject("out_of_order", {})
    assert [m.seq for m in f.shape_outgoing([msg(1), msg(2), msg(3), msg(4)], T0)] == [2, 1, 4, 3]


def test_late_messages_are_held_then_released():
    f = FaultSet(1)
    f.inject("late", {"delay_s": 90})
    assert f.shape_outgoing([msg(1)], T0) == []
    assert [m.seq for m in f.shape_outgoing([], T0 + timedelta(seconds=90))] == [1]


def test_late_default_is_three_intervals():
    f = FaultSet(1)
    f.inject("late", {})
    assert f.shape_outgoing([msg(1)], T0, interval_s=30) == []
    assert f.shape_outgoing([], T0 + timedelta(seconds=89), interval_s=30) == []
    assert [m.seq for m in f.shape_outgoing([], T0 + timedelta(seconds=90), interval_s=30)] == [1]


def test_malformed_alternates_invalid_json_and_missing_field():
    f = FaultSet(1)
    f.inject("malformed", {})
    a, b = f.shape_outgoing([msg(1), msg(2)], T0)
    assert not is_json(a.payload) and is_json(b.payload) and "readings" not in json.loads(b.payload)


def test_drift_grows_linearly():
    f = FaultSet(1, clock=ManualClock(T0))
    f.inject("drift", {"parameter": "salinity_psu", "rate_per_h": 2.0})
    out = f.shape_readings({"salinity_psu": 28}, T0 + timedelta(hours=1.5))
    assert out["salinity_psu"] == pytest.approx(31.0)


def test_drift_without_clock_starts_on_first_use():
    f = FaultSet(1)
    f.inject("drift", {"parameter": "ph", "rate_per_h": 1.0})
    assert f.shape_readings({"ph": 7.0}, T0)["ph"] == pytest.approx(7.0)
    assert f.shape_readings({"ph": 7.0}, T0 + timedelta(hours=2))["ph"] == pytest.approx(9.0)


def test_spikes_seeded_and_rate_scaled():
    def count(seed):
        f = FaultSet(seed, clock=ManualClock(T0))
        f.inject("spikes", {"parameter": "ph", "magnitude": 10, "rate_per_min": 2.0, "sigma": 0.1})
        return sum(f.shape_readings({"ph": 7.0}, T0 + timedelta(seconds=s))["ph"] != 7.0 for s in range(600))

    assert count(3) == count(3)
    assert 5 < count(3) < 600


def test_active_clear_offline_and_low_battery():
    f = FaultSet(1)
    assert not f.is_offline()
    f.inject("offline", {})
    f.inject("low_battery", {"pct": 12})
    assert f.is_offline() and set(f.active()) == {"offline", "low_battery"}
    f.clear("offline")
    assert not f.is_offline()
    with pytest.raises(ValueError):
        f.inject("bogus", {})
