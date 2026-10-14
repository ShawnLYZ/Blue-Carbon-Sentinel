"""Headless scenario runner (Task 6): script validation, execution order, determinism, CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from bcs_sim import cli
from bcs_sim.clock import ManualClock
from bcs_sim.faults import KINDS
from bcs_sim.runner import ScriptError, load_script, run_script

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)  # = the fixture runtime's start
SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"
HEAD = "name: x\nseed: 1\nduration_s: 10\n"


def read(name: str) -> str:
    return (SCENARIO_DIR / f"{name}.yaml").read_text(encoding="utf-8")


DEMO = read("demo-sediment-b3")


def test_script_validation_reports_line():
    with pytest.raises(ScriptError) as e:
        load_script("name: x\nseed: 1\nduration_s: 10\nsteps:\n  - {at_s: 0, action: teleport}\n")
    assert e.value.line == 5 and "teleport" in e.value.message


@pytest.mark.parametrize(
    ("text", "line", "word"),
    [
        ("seed: 1\nduration_s: 10\nsteps: []\n", 1, "name"),
        (HEAD + "steps:\n  - {at_s: 20, action: stop_recording}\n", 5, "duration"),
        (HEAD + "steps:\n  - {at_s: 0, action: apply_scenario, zone: B3}\n", 5, "scenario"),
        (HEAD + "steps:\n  - {at_s: 0, action: inject_fault, node: WQ-01, fault: nope}\n", 5, "nope"),
        (HEAD + "steps:\n  - {at_s: 0, action: apply_scenario, zone: Z9, scenario: healthy}\n", 5, "Z9"),
        (HEAD + "bogus: 1\nsteps: []\n", 4, "bogus"),
        ("name: [unclosed\n", 2, "YAML"),
    ],
)
def test_script_validation_cases(text, line, word):
    with pytest.raises(ScriptError) as e:
        load_script(text)
    assert e.value.line == line and word in e.value.message


@pytest.mark.parametrize("name", ["demo-sediment-b3", "early-warning-salt", "faults-tour"])
def test_example_scripts_load(name):
    s = load_script(read(name))
    assert s.steps and [x.at_s for x in s.steps] == sorted(x.at_s for x in s.steps)


def test_same_seed_same_messages(fake_runtime_factory):
    a = run_script(load_script(DEMO), fake_runtime_factory(seed=42), ManualClock(T0), realtime=False)
    b = run_script(load_script(DEMO), fake_runtime_factory(seed=42), ManualClock(T0), realtime=False)
    assert a.published_count > 50 and a.published_digest == b.published_digest
    c = run_script(load_script(DEMO), fake_runtime_factory(seed=43), ManualClock(T0), realtime=False)
    assert c.published_digest != a.published_digest


def test_steps_execute_at_offsets(fake_runtime_factory):
    log = run_script(load_script(DEMO), fake_runtime_factory(seed=1), ManualClock(T0), realtime=False)
    assert [(s.at_s, s.action) for s in log.steps][:2] == [(0, "apply_scenario"), (90, "inject_fault")]
    assert log.errors == []


def test_runner_drives_the_runtime(fake_runtime_factory):
    rt = fake_runtime_factory(seed=1)
    script = load_script(
        "name: t\nseed: 1\nduration_s: 20\nsteps:\n"
        "  - {at_s: 0, action: apply_scenario, zone: B3, scenario: sediment_runoff, ramp_s: 5}\n"
        "  - {at_s: 5, action: inject_fault, node: WQ-02, fault: offline}\n"
        "  - {at_s: 5, action: set_battery, node: WQ-01, pct: 12}\n"
        "  - {at_s: 5, action: set_rssi, node: WQ-01, dbm: -95}\n"
        "  - {at_s: 5, action: set_value, node: SP-01, parameter: porewater_salinity_psu, value: 58}\n"
    )
    clock = ManualClock(T0)
    log = run_script(script, rt, clock, realtime=False)
    assert log.errors == []
    assert "B3" in rt.scenarios.active()
    assert "offline" in rt.faults("WQ-02").active()
    assert rt.nodes["WQ-01"].node.battery.pct == pytest.approx(12, abs=1)
    assert rt.nodes["WQ-01"].node.rssi_dbm == -95
    assert ("SP-01", "porewater_salinity_psu") in rt.overrides.active()
    assert (clock.now() - T0).total_seconds() >= 20
    assert rt.clock.now() == clock.now()  # the runtime's clock followed the runner's


def test_step_errors_are_collected_not_raised(fake_runtime_factory):
    rt = fake_runtime_factory(seed=1)
    script = load_script(
        "name: t\nseed: 1\nduration_s: 2\nsteps:\n"
        "  - {at_s: 0, action: inject_fault, node: NOPE-9, fault: offline}\n"
        "  - {at_s: 1, action: stop_recording}\n"
    )
    log = run_script(script, rt, ManualClock(T0), realtime=False)
    assert len(log.errors) == 2 and "NOPE-9" in log.errors[0]
    assert [s.ok for s in log.steps] == [False, False]


@pytest.mark.parametrize("name", ["early-warning-salt", "faults-tour"])
def test_other_scripts_run_clean(fake_runtime_factory, name):
    rt = fake_runtime_factory(seed=7)
    log = run_script(load_script(read(name)), rt, ManualClock(T0), realtime=False)
    assert log.errors == []
    if name == "faults-tour":
        assert {s.detail for s in log.steps if s.action == "inject_fault"} >= set(KINDS)
        assert len(rt.fake_gs.uploads) == 1  # the tour records itself


def test_demo_time_scale_mismatch_is_an_error(fake_runtime_factory):
    rt = fake_runtime_factory(seed=1, demo_time_scale=False)
    log = run_script(load_script(DEMO), rt, ManualClock(T0), realtime=False)
    assert any("demo_time_scale" in e for e in log.errors)


def test_cli_without_ground_station_exits_1(capsys, tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(DEMO, encoding="utf-8")
    argv = [
        "scenario",
        str(f),
        "--seed",
        "1",
        "--gs-url",
        "http://127.0.0.1:9",
        "--log",
        str(tmp_path / "l.json"),
    ]
    code = cli.main(argv)
    err = capsys.readouterr().err
    assert code == 1 and "Ground Station" in err and "Traceback" not in err


def test_cli_bad_script_exits_1(capsys, tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(
        "name: x\nseed: 1\nduration_s: 10\nsteps:\n  - {at_s: 0, action: teleport}\n", encoding="utf-8"
    )
    assert cli.main(["scenario", str(f)]) == 1
    assert "line 5" in capsys.readouterr().err
