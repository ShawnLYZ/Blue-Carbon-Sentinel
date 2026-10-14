"""The network and operating-system edge of preflight.

``Probes`` is the seam tests replace with ``FakeProbes``. ``RealProbes`` never raises: every probe
has a 5 s timeout and any failure becomes a negative answer. Error text is never returned or logged,
because a request error can carry the URL, and the URL can carry a key.
"""

from __future__ import annotations

import ipaddress
import logging
import secrets
import shutil
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

log = logging.getLogger("bcs_gs.status")

TIMEOUT_S = 5.0
OUR_PROCESS_NAMES = ("mosquitto", "python", "uv", "bcs-")
SUPABASE_API = "https://api.supabase.com/v1/projects"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
NVIDIA_FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b"
MAPBOX_TOKENS_URL = "https://api.mapbox.com/tokens/v2"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

PortOwner = Literal["free", "ours", "foreign"]
ProjectStatus = Literal["ACTIVE_HEALTHY", "INACTIVE", "UNKNOWN"]


class Probes(Protocol):
    def resolve_camera(self, host: str) -> str | None: ...
    def camera_status(self, ip: str) -> dict[str, Any] | None: ...
    def port_owner(self, port: int) -> PortOwner: ...
    def broker_login(self, host: str, port: int, user: str, pw: str) -> bool: ...
    def supabase_project_status(self, ref: str, token: str) -> ProjectStatus: ...
    def db_size(self) -> int | None: ...
    def gemini_models(self, key: str) -> bool: ...
    def nvidia_auth(self, key: str) -> bool: ...
    def mapbox_token(self, token: str) -> bool: ...
    def depth_model_present(self, path: Path) -> bool: ...
    def directml_available(self) -> bool: ...
    def ollama_models(self) -> list[str] | None: ...
    def free_disk_bytes(self, path: Path) -> int: ...


def _quiet(default: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Turn any exception into ``default``; log the probe name and exception type only."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                log.warning("probe %s failed: %s", fn.__name__, type(exc).__name__)
                return default

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return deco


class RealProbes:
    def __init__(
        self, run_dir: Path, supabase_url: str | None = None, service_key: str | None = None
    ) -> None:
        self._run_dir = run_dir
        self._supabase_url = supabase_url
        self._service_key = service_key

    # -- camera -----------------------------------------------------------------------------
    @_quiet(None)
    def resolve_camera(self, host: str) -> str | None:
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            pass
        # mDNS lookups can block far past a socket timeout on Windows, so bound them with a thread.
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            return pool.submit(socket.gethostbyname, host).result(timeout=TIMEOUT_S)
        except (OSError, FutureTimeout):
            return None
        finally:
            pool.shutdown(wait=False)

    @_quiet(None)
    def camera_status(self, ip: str) -> dict[str, Any] | None:
        r = httpx.get(f"http://{ip}/status", timeout=TIMEOUT_S)
        body = r.json() if r.status_code == 200 else None
        return body if isinstance(body, dict) else None

    # -- broker -----------------------------------------------------------------------------
    @_quiet("foreign")
    def port_owner(self, port: int) -> PortOwner:
        import psutil

        ours = self._our_pids()
        owners: set[int | None] = set()
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                owners.add(c.pid)
        if not owners:
            return "free"
        return "ours" if owners <= ours else "foreign"

    def _our_pids(self) -> set[int | None]:
        """PIDs from ``*.pid`` that still name one of our processes; stale files are deleted.

        A pid file is stale when the process is gone, is not mosquitto/python/uv, or started after
        the file was written (the pid was reused after a crash or reboot).
        """
        import psutil

        pids: set[int | None] = set()
        for f in self._run_dir.glob("*.pid"):
            try:
                pid = int(f.read_text(encoding="utf-8").strip())
                proc = psutil.Process(pid)
                name = proc.name().lower()
                fresh = proc.create_time() <= f.stat().st_mtime + 2
                if fresh and any(k in name for k in OUR_PROCESS_NAMES):
                    pids.add(pid)
                    continue
            except (OSError, ValueError, psutil.Error):
                pass
            f.unlink(missing_ok=True)
        return pids

    @_quiet(False)
    def broker_login(self, host: str, port: int, user: str, pw: str) -> bool:
        import paho.mqtt.client as mqtt

        done = threading.Event()
        result: list[bool] = []

        def on_connect(_c: Any, _u: Any, _f: Any, rc: Any, _p: Any) -> None:
            result.append(not getattr(rc, "is_failure", rc != 0))
            done.set()

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{user}-preflight-{secrets.token_hex(4)}",
            protocol=mqtt.MQTTv5,
        )
        client.username_pw_set(user, pw)
        client.on_connect = on_connect
        client.connect(host, port, keepalive=10)
        client.loop_start()
        try:
            return bool(done.wait(TIMEOUT_S) and result and result[0])
        finally:
            client.disconnect()
            client.loop_stop()

    # -- cloud ------------------------------------------------------------------------------
    @_quiet("UNKNOWN")
    def supabase_project_status(self, ref: str, token: str) -> ProjectStatus:
        r = httpx.get(
            f"{SUPABASE_API}/{ref}", headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT_S
        )
        if r.status_code != 200:
            return "UNKNOWN"
        status = str(r.json().get("status", ""))
        if status == "ACTIVE_HEALTHY":
            return "ACTIVE_HEALTHY"
        if status in ("INACTIVE", "PAUSING", "PAUSED"):
            return "INACTIVE"
        return "UNKNOWN"

    @_quiet(None)
    def db_size(self) -> int | None:
        if not (self._supabase_url and self._service_key):
            return None
        r = httpx.post(
            f"{self._supabase_url.rstrip('/')}/rest/v1/rpc/bcs_db_size",
            headers={"apikey": self._service_key, "Authorization": f"Bearer {self._service_key}"},
            json={},
            timeout=TIMEOUT_S,
        )
        return int(r.json()) if r.status_code == 200 else None

    # -- keys -------------------------------------------------------------------------------
    @_quiet(False)
    def gemini_models(self, key: str) -> bool:
        return (
            httpx.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": key}, timeout=TIMEOUT_S).status_code
            == 200
        )

    @_quiet(False)
    def nvidia_auth(self, key: str) -> bool:
        """An empty body is invalid (422) but only after authentication, so 422 proves the key
        without generating anything; 401 and 403 mean the key is rejected."""
        r = httpx.post(
            NVIDIA_FLUX_URL, headers={"Authorization": f"Bearer {key}"}, json={}, timeout=TIMEOUT_S
        )
        return r.status_code == 422

    @_quiet(False)
    def mapbox_token(self, token: str) -> bool:
        r = httpx.get(MAPBOX_TOKENS_URL, params={"access_token": token}, timeout=TIMEOUT_S)
        return r.status_code == 200

    # -- local ------------------------------------------------------------------------------
    @_quiet(False)
    def depth_model_present(self, path: Path) -> bool:
        return path.is_file()

    @_quiet(False)
    def directml_available(self) -> bool:
        import onnxruntime

        return "DmlExecutionProvider" in onnxruntime.get_available_providers()

    @_quiet(None)
    def ollama_models(self) -> list[str] | None:
        r = httpx.get(OLLAMA_TAGS_URL, timeout=TIMEOUT_S)
        if r.status_code != 200:
            return None
        return [str(m.get("name", "")) for m in r.json().get("models", [])]

    @_quiet(0)
    def free_disk_bytes(self, path: Path) -> int:
        p = path
        while not p.exists() and p != p.parent:
            p = p.parent
        return int(shutil.disk_usage(p).free)


class FakeProbes:
    """Deterministic probes for tests: everything is healthy until a test changes an attribute."""

    def __init__(self) -> None:
        self.camera: str | None = "192.168.1.50"
        self.camera_json: dict[str, Any] | None = {
            "fw_version": "0.1.0", "device_id": "CAM-01", "ip": "192.168.1.50", "rssi_dbm": -55,
        }  # fmt: skip
        self.broker_ok = True
        self.project_status: ProjectStatus = "ACTIVE_HEALTHY"
        self.db_bytes: int | None = 12_000_000
        self.gemini_ok = True
        self.nvidia_ok = True
        self.mapbox_ok = True
        self.depth_present = True
        self.directml = True
        self.ollama: list[str] | None = ["gemma4:e4b"]
        self.free_bytes = 200_000_000_000

    def resolve_camera(self, host: str) -> str | None:
        return self.camera

    def camera_status(self, ip: str) -> dict[str, Any] | None:
        return self.camera_json

    def port_owner(self, port: int) -> PortOwner:
        return "ours"

    def broker_login(self, host: str, port: int, user: str, pw: str) -> bool:
        return self.broker_ok

    def supabase_project_status(self, ref: str, token: str) -> ProjectStatus:
        return self.project_status

    def db_size(self) -> int | None:
        return self.db_bytes

    def gemini_models(self, key: str) -> bool:
        return self.gemini_ok

    def nvidia_auth(self, key: str) -> bool:
        return self.nvidia_ok

    def mapbox_token(self, token: str) -> bool:
        return self.mapbox_ok

    def depth_model_present(self, path: Path) -> bool:
        return self.depth_present

    def directml_available(self) -> bool:
        return self.directml

    def ollama_models(self) -> list[str] | None:
        return self.ollama

    def free_disk_bytes(self, path: Path) -> int:
        return self.free_bytes
