from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from bcs_sim.clock import ManualClock
from bcs_sim.config import load_sim_config
from bcs_sim.environment import Environment, apply_noise
from bcs_sim.oxygen import do_saturation_mg_l

CFG = load_sim_config()
T0 = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)


def myt(y, mo, d, h):
    return datetime(y, mo, d, h, tzinfo=UTC) - timedelta(hours=8)


def _scan(env):
    ts = [T0 + timedelta(minutes=m) for m in range(0, 750, 5)]
    return min(ts, key=env.level_cm), max(ts, key=env.level_cm)


def high_tide(env):
    return _scan(env)[1]


def low_tide(env):
    return _scan(env)[0]


def test_oxygen_solubility_known_values():
    assert do_saturation_mg_l(25, 0) == pytest.approx(8.26, abs=0.05)
    assert do_saturation_mg_l(25, 35) == pytest.approx(6.76, abs=0.08)
    assert do_saturation_mg_l(30, 35) < do_saturation_mg_l(25, 35) < do_saturation_mg_l(25, 0)


def test_tide_period_and_fast_forward_keep_real_timestamps():
    env = Environment(CFG, seed=1, clock=ManualClock(T0))
    t = T0
    assert env.level_cm(t) == pytest.approx(env.level_cm(t + timedelta(hours=12.42)), abs=0.5)
    env.set_fast_forward(186.3)
    assert env.level_cm(t) == pytest.approx(env.level_cm(t + timedelta(minutes=4)), abs=0.5)


def test_salinity_rises_on_flood():
    env = Environment(CFG, 1, ManualClock(T0))
    hi, lo = high_tide(env), low_tide(env)
    assert (
        env.natural("water_quality", 100, 100, 0, hi)["salinity_psu"]
        > env.natural("water_quality", 100, 100, 0, lo)["salinity_psu"]
    )


def test_temperature_peaks_mid_afternoon_myt():
    env = Environment(CFG, 1, ManualClock(T0))
    t15, t03 = myt(2026, 10, 16, 15), myt(2026, 10, 16, 3)
    assert env.natural("water_quality", 0, 0, 0, t15)["temp_c"] == pytest.approx(31, abs=0.01)
    assert env.natural("water_quality", 0, 0, 0, t03)["temp_c"] == pytest.approx(27, abs=0.01)


def test_noise_statistics_and_resolution():
    rng = np.random.default_rng(7)
    xs = [apply_noise({"do_mg_l": 6.0}, rng, CFG)["do_mg_l"] for _ in range(4000)]
    assert np.std(xs) == pytest.approx(0.05, rel=0.1) and all(round(x, 2) == x for x in xs)


def test_soil_relaxes_when_exposed_and_wets_when_inundated():
    env = Environment(CFG, 1, ManualClock(T0))
    hi, lo = high_tide(env), low_tide(env)
    assert env.natural("soil_probe", 1, 1, 0, hi)["soil_moisture_pct"] == 55.0
    dry = env.natural("soil_probe", 2, 2, 10_000, hi)  # never inundated: starts at the dry value
    assert dry["soil_moisture_pct"] == 35.0
    wet = env.natural("soil_probe", 1, 1, 100, hi)  # same key, now above sea level -> relaxes down
    later = env.natural("soil_probe", 1, 1, 100, hi + timedelta(hours=2))
    assert 35 < later["soil_moisture_pct"] <= wet["soil_moisture_pct"]
    assert env.natural("tide_gauge", 0, 0, 0, lo)["water_level_cm"] == env.level_cm(lo)


def test_set_nature_flags_and_clamped_noise():
    env = Environment(CFG, 1, ManualClock(T0))
    env.set_nature(tide=False, diurnal=False)
    assert env.level_cm(T0) == 0
    assert env.natural("water_quality", 0, 0, 0, myt(2026, 10, 16, 15))["temp_c"] == 29
    assert apply_noise({"ph": 99.0}, np.random.default_rng(1), CFG)["ph"] == 14
