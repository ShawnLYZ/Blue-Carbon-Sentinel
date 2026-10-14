"""Repository-wide test fixtures shared by every service: a real Mosquitto broker.

``mosquitto`` runs the broker with dynamic-security on and anonymous access off, on a free loopback
port with a temporary data directory (bootstrapped through ``bcs_gs.broker``; test code may import
``bcs_gs``, production simulator code may not). The test is skipped when no ``mosquitto`` binary is
installed.
"""

from __future__ import annotations

import secrets
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class BrokerHandle:
    host: str
    port: int
    admin_user: str
    admin_password: str


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_broker(tmp_path: Path, admin_pw: str) -> Iterator[BrokerHandle]:
    from bcs_gs.broker import bootstrap, find_mosquitto

    exe = find_mosquitto()
    if exe is None:
        pytest.skip("mosquitto binary not found")
    port = _free_port()
    var = tmp_path / "var"
    bootstrap(var, "admin", admin_pw, port)
    proc = subprocess.Popen(
        [exe, "-c", str(var / "mosquitto" / "mosquitto.conf")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if proc.poll() is not None:
                raise RuntimeError("mosquitto exited at start")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("mosquitto did not start listening") from None
                time.sleep(0.05)
        yield BrokerHandle("127.0.0.1", port, "admin", admin_pw)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture
def mosquitto(tmp_path: Path) -> Iterator[BrokerHandle]:
    """A real Mosquitto (dynamic-security on, anonymous off) on a free port with a temp data dir."""
    yield from _run_broker(tmp_path, secrets.token_urlsafe(24))


@pytest.fixture
def mosquitto_short_pw(tmp_path: Path) -> Iterator[BrokerHandle]:
    """Admin password under 12 characters: bootstrap must use `mosquitto_ctrl dynsec init`."""
    yield from _run_broker(tmp_path, "short-pw")
