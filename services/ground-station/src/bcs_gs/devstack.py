"""Cross-platform dev stack: broker, Ground Station and simulator as child processes (addendum D2, D4).

``devstack(test_mode=True, data_dir=...)`` is used by tests and CI; ``bcs-gs devstack --test-mode``
is the foreground form Playwright uses as its web server.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Self

import psutil

from bcs_gs.broker import bootstrap, find_mosquitto

HOST = "127.0.0.1"
SIM_DEFAULT_PORT = 8701
READY_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 8.0
LOG_TAIL_LINES = 30
LOG_TAIL_CHARS = 4000


class DevStackError(RuntimeError):
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


@dataclass
class DevStack:
    gs_url: str
    sim_url: str
    broker_port: int
    run_dir: Path
    processes: list[psutil.Process] = field(default_factory=list)  # every process we started
    servers: list[subprocess.Popen[Any]] = field(default_factory=list, repr=False)  # broker, GS, sim
    log_dir: Path | None = None
    _logs: list[IO[bytes]] = field(default_factory=list, repr=False)  # children's stderr files
    _stopped: bool = False

    def alive(self) -> bool:
        return all(p.poll() is None for p in self.servers)

    def stop(self) -> None:
        """Terminate the children (and their descendants), then delete the pid files."""
        if self._stopped:
            return
        self._stopped = True
        victims: list[psutil.Process] = []
        for proc in self.processes:
            try:
                victims.extend(proc.children(recursive=True))
            except psutil.Error:
                pass
            victims.append(proc)
        for proc in victims:
            try:
                proc.terminate()
            except psutil.Error:
                pass
        _gone, alive = psutil.wait_procs(victims, timeout=STOP_TIMEOUT_S)
        for proc in alive:
            try:
                proc.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=STOP_TIMEOUT_S)
        for popen in self.servers:
            try:
                popen.wait(STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                pass
            if popen.stdout is not None:
                popen.stdout.close()
        for fh in self._logs:
            try:
                fh.close()
            except OSError:
                pass
        for pidfile in self.run_dir.glob("*.pid"):
            pidfile.unlink(missing_ok=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()


def _read_ready(popen: subprocess.Popen[str], name: str, timeout: float) -> str:
    """The URL from the child's ``READY <url>`` line; raises if it exits or stays silent.

    A thread keeps reading afterwards so the child's stdout pipe never fills up.
    """
    result: list[str] = []

    def reader() -> None:
        assert popen.stdout is not None
        try:
            for line in popen.stdout:
                if line.startswith("READY ") and not result:
                    result.append(line.split(" ", 1)[1].strip())
        except (OSError, ValueError):
            pass

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + timeout
    while not result:
        if popen.poll() is not None:
            raise DevStackError(f"{name} exited with code {popen.returncode} before it was ready")
        if time.monotonic() > deadline:
            raise DevStackError(f"{name} was not ready within {timeout:.0f} s")
        time.sleep(0.05)
    return result[0]


def log_tail(path: Path, lines: int = LOG_TAIL_LINES, max_chars: int = LOG_TAIL_CHARS) -> str:
    """Last ``lines`` lines of a child's stderr log (at most ``max_chars``); empty if none."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").rstrip()
    tail = "\n".join(text.splitlines()[-lines:])
    return tail[-max_chars:]


def _failure_detail(log: Path, test_mode: bool) -> str:
    """Where to look after a failed start. Test mode has no real secrets, so the tail is inlined;
    otherwise only the path is given (the real stack's logs may mention configuration)."""
    if not test_mode:
        return f" (stderr: {log})"
    tail = log_tail(log)
    if not tail:
        return f" (stderr: {log}, empty)"
    return f" (stderr: {log}); last lines:\n{tail}"


def _wait_port(port: int, popen: subprocess.Popen[Any], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if popen.poll() is not None:
            raise DevStackError("mosquitto exited at start (is its port already in use?)")
        try:
            socket.create_connection((HOST, port), timeout=0.2).close()
            return
        except OSError:
            if time.monotonic() > deadline:
                raise DevStackError("mosquitto did not start listening") from None
            time.sleep(0.05)


def _listener_pid(port: int, popen: subprocess.Popen[Any]) -> int:
    """PID listening on ``port`` if it is our child or one of its descendants, else the child's pid.

    A venv launcher can sit between us and the real server; a foreign holder is never recorded.
    """
    try:
        ours = {popen.pid} | {c.pid for c in psutil.Process(popen.pid).children(recursive=True)}
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port and c.pid in ours:
                return int(c.pid)
    except (psutil.Error, OSError):
        pass
    return popen.pid


def _port_in_use(port: int) -> bool:
    try:
        socket.create_connection((HOST, port), timeout=0.3).close()
        return True
    except OSError:
        return False


def devstack(
    test_mode: bool,
    data_dir: Path,
    *,
    gs_port: int | None = None,
    sim_port: int | None = None,
    broker_port: int | None = None,
    ready_timeout: float = READY_TIMEOUT_S,
    log_dir: Path | None = None,
) -> DevStack:
    """Start Mosquitto, the Ground Station and the simulator; return when all three listen.

    ``data_dir`` is the state root (as ``--data-dir``: state lives in ``<data_dir>/var``).
    Test mode: free ports unless given (``0`` also means free), a throw-away broker admin, no real
    ``.env``, fake cloud, rules-only AI and no camera. The Ground Station runs on the system clock,
    because the simulator always runs in real time (a frozen Ground Station clock would see every
    command as expired and every sample as from the future). Otherwise the real ports
    (8700, 8701, 1883) and the repository ``.env`` are used.

    Each child's stderr is appended to ``<log_dir>/<name>.err.log`` (default ``<data_dir>/var/logs``;
    names ``mosquitto``, ``gs``, ``sim``) and closed on stop. A start-up failure names that log, and in
    test mode includes its tail.
    """
    from bcs_gs.cli import DEFAULT_PORT, REPO_ROOT

    gs_p = (0 if test_mode else DEFAULT_PORT) if gs_port is None else gs_port
    sim_p = (0 if test_mode else SIM_DEFAULT_PORT) if sim_port is None else sim_port
    bp = broker_port if broker_port else (free_port() if test_mode else 1883)

    data_dir = Path(data_dir)
    var = data_dir / "var"
    run_dir = var / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    logs = Path(log_dir) if log_dir is not None else var / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    exe = find_mosquitto()
    if exe is None:
        raise DevStackError("mosquitto was not found (install it, or add it to PATH)")

    if _port_in_use(bp):
        raise DevStackError(
            f"port {bp} is already in use. If the Windows Mosquitto service is running, "
            "stop and disable the Mosquitto service, then try again."
        )

    env = dict(os.environ)
    gs_extra: list[str] = []
    sim_extra: list[str] = []
    if test_mode:
        admin_user, admin_pw = "admin", secrets.token_urlsafe(24)
        env.update(
            BCS_BROKER_ADMIN_USER=admin_user,
            BCS_BROKER_ADMIN_PASSWORD=admin_pw,
            BCS_GS_MQTT_PASSWORD=secrets.token_urlsafe(24),
            BCS_SIM_SHARED_TOKEN=secrets.token_urlsafe(24),
        )
        # An env file that does not exist: test mode never reads the real .env.
        no_env = str(data_dir / "no-such.env")
        gs_extra = ["--test-mode", "--ai", "rules", "--cloud", "fake", "--no-camera"]
        gs_extra += ["--env-file", no_env]
        sim_extra = ["--env-file", no_env]
    else:
        from bcs_gs.core.config import load_settings

        env_file = REPO_ROOT / ".env"
        settings = load_settings(REPO_ROOT, env_file=env_file if env_file.is_file() else None)
        if settings.broker_admin_password is None:
            raise DevStackError("BCS_BROKER_ADMIN_PASSWORD is not set (see .env.example)")
        admin_user = settings.broker_admin_user
        admin_pw = settings.broker_admin_password.get_secret_value()
    if not sim_p:
        sim_p = free_port()  # the Ground Station must be told the simulator port before it starts
    env["BCS_BROKER_PORT"] = str(bp)
    env["BCS_SIM_PORT"] = str(sim_p)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    bootstrap(var, admin_user, admin_pw, bp)

    stack = DevStack(gs_url="", sim_url="", broker_port=bp, run_dir=run_dir, log_dir=logs)

    def record(name: str, popen: subprocess.Popen[Any], port: int) -> None:
        pid = _listener_pid(port, popen)
        (run_dir / f"{name}.pid").write_text(str(pid), encoding="ascii")
        if pid != popen.pid:
            stack.processes.append(psutil.Process(pid))

    current: list[str] = []  # name of the child being started, for the failure message

    def spawn(name: str, cmd: list[str], pipe: bool) -> subprocess.Popen[Any]:
        current[:] = [name]
        err = (logs / f"{name}.err.log").open("ab")
        stack._logs.append(err)
        err.write(f"--- devstack start {time.strftime('%Y-%m-%dT%H:%M:%S')} ---\n".encode())
        err.flush()
        popen: subprocess.Popen[Any] = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE if pipe else subprocess.DEVNULL,
            stderr=err,
            text=pipe or None,
            encoding="utf-8" if pipe else None,
        )
        stack.servers.append(popen)
        stack.processes.append(psutil.Process(popen.pid))
        return popen

    try:
        broker = spawn("mosquitto", [exe, "-c", str(var / "mosquitto" / "mosquitto.conf")], pipe=False)
        _wait_port(bp, broker, 15)
        record("mosquitto", broker, bp)

        gs = spawn(
            "gs",
            [sys.executable, "-m", "bcs_gs.cli", "run", "--port", str(gs_p), "--data-dir", str(data_dir),
             "--broker-port", str(bp), *gs_extra],
            pipe=True,
        )  # fmt: skip
        stack.gs_url = _read_ready(gs, "Ground Station", ready_timeout)
        record("gs", gs, int(stack.gs_url.rsplit(":", 1)[1]))

        sim = spawn(
            "sim",
            [sys.executable, "-m", "bcs_sim.cli", "run", "--port", str(sim_p), "--gs-url", stack.gs_url,
             *sim_extra],
            pipe=True,
        )  # fmt: skip
        stack.sim_url = _read_ready(sim, "simulator", ready_timeout)
        record("sim", sim, int(stack.sim_url.rsplit(":", 1)[1]))
    except DevStackError as exc:
        stack.stop()  # closes the logs first, so the tail is complete
        detail = _failure_detail(logs / f"{current[0]}.err.log", test_mode) if current else ""
        raise DevStackError(f"{exc}{detail}") from None
    except BaseException:
        stack.stop()
        raise
    return stack


def run_foreground(
    gs_port: int, sim_port: int, data_dir: Path | None, test_mode: bool, log_dir: Path | None = None
) -> int:
    """``bcs-gs devstack``: start everything, print the URLs, wait for Ctrl+C or SIGTERM, stop all."""
    import signal

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    tmp = None
    if data_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="bcs-devstack-", ignore_cleanup_errors=True)
        data_dir = Path(tmp.name)
    try:
        stack = devstack(test_mode, data_dir, gs_port=gs_port, sim_port=sim_port, log_dir=log_dir)
    except DevStackError as exc:
        print(f"devstack failed: {exc}", file=sys.stderr, flush=True)
        return 1
    print(f"READY {stack.gs_url} sim={stack.sim_url} broker_port={stack.broker_port}", flush=True)
    try:
        while not stop.wait(0.5):
            if not stack.alive():
                print("a child process exited; stopping", file=sys.stderr, flush=True)
                break
    finally:
        stack.stop()
        if tmp is not None:
            tmp.cleanup()
    return 0
