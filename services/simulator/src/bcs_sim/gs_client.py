"""Ground Station client for the simulator (addendum I4 internal routes, J2 ``/ws/events``).

Routes (loopback only, header ``X-BCS-Sim-Token``), under ``{gs_url}/api/v1``:

- ``GET /internal/sim/registry`` -> ``{"site_id": "KSL", "nodes": [{"node_id", "node_type",
  "position": {"e_m", "s_m"}, "zone_label"}]}`` (a bare list of nodes is accepted too; a node may
  carry its own ``site_id``; flat ``e_m``/``s_m`` and ``id``/``zone_id`` are tolerated);
- ``POST /internal/sim/credentials`` ``{node_ids?}`` -> ``{"credentials": [{node_id, username, password}]}``;
- ``POST /internal/sim/sessions``: multipart, ``file`` (the K5 JSONL) and ``meta`` (JSON text);
- the public node routes ``POST /nodes``, ``/nodes/{id}/move``, ``/nodes/{id}/decommission`` and
  ``GET /coverage`` (lifecycle delegation; a Ground Station error keeps its status and I1 body in ``GsError``).

Passwords are returned to the caller and never logged. ``RegistryWatcher`` follows ``/ws/events``
in a background thread and forwards ``node.registry`` data; it tolerates an absent Ground Station
and reconnects.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("bcs_sim.gs_client")
API = "/api/v1"
DEFAULT_SITE = "KSL"
TIMEOUT_S = 10.0


class GsError(RuntimeError):
    """A Ground Station call failed (unreachable, refused or malformed answer).

    ``status`` and ``body`` are the HTTP status and decoded JSON body when the Ground Station answered
    with an error (the I1 envelope), so callers can pass it through unchanged; both are None when the
    Ground Station could not be reached."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class SimNodeSpec:
    node_id: str
    node_type: str
    e_m: float
    s_m: float
    zone_label: str | None = None
    site_id: str = DEFAULT_SITE


def _spec(raw: dict[str, Any], site_id: str) -> SimNodeSpec:
    pos = raw.get("position") or raw
    return SimNodeSpec(
        node_id=str(raw.get("node_id") or raw["id"]),
        node_type=str(raw["node_type"]),
        e_m=float(pos["e_m"]),
        s_m=float(pos["s_m"]),
        zone_label=raw.get("zone_label", raw.get("zone_id")),
        site_id=str(raw.get("site_id") or site_id),
    )


class GsClient:
    def __init__(
        self,
        gs_url: str,
        sim_token: str | None,
        *,
        site_id: str = DEFAULT_SITE,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self.gs_url = gs_url.rstrip("/")
        self.site_id = site_id
        headers = {"X-BCS-Sim-Token": sim_token} if sim_token else {}
        self._http = httpx.Client(
            base_url=self.gs_url + API, headers=headers, timeout=timeout_s, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise GsError(f"{method} {path}: Ground Station unreachable ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            code, body = "", None
            try:
                body = r.json()
                code = body.get("error", {}).get("code", "") if isinstance(body, dict) else ""
            except ValueError:
                pass
            raise GsError(
                f"{method} {path}: HTTP {r.status_code} {code}".rstrip(), status=r.status_code, body=body
            )
        try:
            return r.json()
        except ValueError as exc:
            raise GsError(f"{method} {path}: answer is not JSON") from exc

    def registry(self) -> list[SimNodeSpec]:
        body = self._call("GET", "/internal/sim/registry")
        nodes = body if isinstance(body, list) else body.get("nodes", [])
        site = self.site_id if isinstance(body, list) else str(body.get("site_id") or self.site_id)
        try:
            return [_spec(n, site) for n in nodes]
        except (KeyError, TypeError, ValueError) as exc:
            raise GsError(f"registry answer malformed: {exc!r}") from exc

    def credentials(self, node_ids: list[str] | None = None) -> dict[str, str]:
        body = self._call(
            "POST", "/internal/sim/credentials", json={} if node_ids is None else {"node_ids": list(node_ids)}
        )
        try:
            return {str(c["node_id"]): str(c["password"]) for c in body["credentials"]}
        except (KeyError, TypeError) as exc:
            raise GsError("credentials answer malformed") from exc

    def upload_session(self, meta: dict[str, Any], path: Path) -> dict[str, Any]:
        p = Path(path)
        files = {"file": (p.name, p.read_bytes(), "application/x-ndjson")}
        return self._call("POST", "/internal/sim/sessions", files=files, data={"meta": json.dumps(meta)})

    # ---- public node routes (I2), used by the simulator's lifecycle routes and the runner ---------------
    def create_node(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /nodes`` with ``body`` as given; returns the Ground Station's ``{node, key}``."""
        return self._call("POST", "/nodes", json=body)

    def move_node(self, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /nodes/{id}/move`` with ``body`` (``{position, confirm}``); returns the Node."""
        return self._call("POST", f"/nodes/{node_id}/move", json=body)

    def decommission_node(self, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /nodes/{id}/decommission`` with ``body`` (``{confirm}``); returns the Node."""
        return self._call("POST", f"/nodes/{node_id}/decommission", json=body)

    def coverage(self) -> dict[str, Any]:
        """``GET /coverage`` (zones and coverage-gap suggestions)."""
        return self._call("GET", "/coverage")

    def install_node(self, node_type: str, e_m: float, s_m: float, node_id: str | None = None) -> str:
        """Install a simulated node at a site position; returns the ID the Ground Station gave it (F1: IDs are
        assigned by the registry, so a requested ``node_id`` is only checked, never imposed)."""
        body = {"node_type": node_type, "source": "simulated", "position": {"e_m": e_m, "s_m": s_m}}
        new_id = str(self.create_node(body)["node"]["id"])
        if node_id and node_id != new_id:
            log.warning("requested node ID %s, the Ground Station assigned %s", node_id, new_id)
        return new_id

    def move(self, node_id: str, e_m: float, s_m: float) -> dict[str, Any]:
        """Move a node (confirmed)."""
        return self.move_node(node_id, {"position": {"e_m": e_m, "s_m": s_m}, "confirm": True})

    def remove_node(self, node_id: str) -> dict[str, Any]:
        """Decommission a node (confirmed)."""
        return self.decommission_node(node_id, {"confirm": True})

    def watch_registry(self, callback: Callable[[dict[str, Any]], None]) -> RegistryWatcher:
        w = RegistryWatcher(self.gs_url, callback)
        w.start()
        return w


class RegistryWatcher(threading.Thread):
    """Follows ``/ws/events`` and calls ``callback(data)`` for each ``node.registry`` event.

    Reconnects after ``retry_s`` (doubling up to ``max_retry_s``) whenever the Ground Station is absent
    or the socket drops. ``stop()`` ends the thread within about a second.
    """

    def __init__(
        self,
        gs_url: str,
        callback: Callable[[dict[str, Any]], None],
        *,
        retry_s: float = 1.0,
        max_retry_s: float = 10.0,
    ) -> None:
        super().__init__(name="bcs-sim-registry-watch", daemon=True)
        base = gs_url.rstrip("/")
        self.url = ("ws" + base[4:] if base.startswith("http") else base) + "/ws/events"
        self.callback = callback
        self.retry_s = retry_s
        self.max_retry_s = max_retry_s
        self.attempts = 0
        self._stop_evt = threading.Event()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_evt.set()  # the receive loop polls every second
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout)

    def run(self) -> None:
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect

        delay = self.retry_s
        while not self._stop_evt.is_set():
            self.attempts += 1
            try:
                with connect(self.url, open_timeout=5, close_timeout=1) as ws:
                    delay = self.retry_s
                    while not self._stop_evt.is_set():
                        try:
                            raw = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        self._handle(raw)
            except (OSError, WebSocketException, TimeoutError) as exc:
                log.debug("registry watch: %s", type(exc).__name__)
            if self._stop_evt.wait(delay):
                break
            delay = min(delay * 2, self.max_retry_s)

    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if isinstance(msg, dict) and msg.get("type") == "node.registry":
            try:
                self.callback(dict(msg.get("data") or {}))
            except Exception:
                log.exception("registry change handler failed")
