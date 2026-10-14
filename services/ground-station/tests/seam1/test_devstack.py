"""Dev stack: broker, Ground Station and simulator as children (task 13, addendum D2/D4)."""

import httpx
from bcs_gs.devstack import devstack


def test_devstack_test_mode_comes_up_healthy_and_stops(tmp_path):
    with devstack(test_mode=True, data_dir=tmp_path / "Blue Carbon Sentinel" / "var") as s:  # spaces
        assert httpx.get(f"{s.gs_url}/api/v1/system/status", timeout=10).status_code == 200
        assert httpx.get(f"{s.sim_url}/api/v1/state", timeout=10).status_code == 200
        pids = sorted(f.name for f in s.run_dir.glob("*.pid"))
        assert pids == ["gs.pid", "mosquitto.pid", "sim.pid"]
    assert not any(p.is_running() for p in s.processes)


def test_devstack_refuses_a_broker_port_held_by_someone_else(tmp_path):
    import socket

    import pytest
    from bcs_gs.devstack import DevStackError

    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        with pytest.raises(DevStackError, match="stop and disable the Mosquitto service"):
            devstack(test_mode=True, data_dir=tmp_path, broker_port=port)
    assert not list((tmp_path / "var" / "run").glob("*.pid"))


def test_devstack_startup_failure_reports_child_stderr_tail(tmp_path):
    """Finding 7: children's stderr goes to <data_dir>/var/logs/<name>.err.log and a failed start
    quotes its tail (test mode only)."""
    import socket

    import pytest
    from bcs_gs.devstack import DevStackError

    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        with pytest.raises(DevStackError) as info:
            devstack(test_mode=True, data_dir=tmp_path, gs_port=port, ready_timeout=60)
    msg = str(info.value)
    log = tmp_path / "var" / "logs" / "gs.err.log"
    assert "Ground Station" in msg and str(log) in msg and "last lines:" in msg
    body = log.read_text(encoding="utf-8", errors="replace")
    assert body.strip() and msg.rstrip().endswith(body.rstrip().splitlines()[-1])
    assert (tmp_path / "var" / "logs" / "mosquitto.err.log").exists()
    assert not list((tmp_path / "var" / "run").glob("*.pid"))


def test_failure_detail_inlines_tail_only_in_test_mode(tmp_path):
    from bcs_gs.devstack import _failure_detail, log_tail

    log = tmp_path / "gs.err.log"
    log.write_text("".join(f"line {i}\n" for i in range(100)), encoding="utf-8")
    assert log_tail(log).splitlines() == [f"line {i}" for i in range(70, 100)]
    assert "line 99" in _failure_detail(log, test_mode=True)
    real = _failure_detail(log, test_mode=False)
    assert str(log) in real and "line" not in real.replace(str(log), "")
    assert log_tail(tmp_path / "missing.log") == ""
