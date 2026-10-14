"""GsClient against a mock transport, and the /ws/events registry watcher."""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from bcs_sim.clock import ManualClock
from bcs_sim.gs_client import GsClient, GsError, RegistryWatcher, SimNodeSpec
from bcs_sim.inspector import InspectorTap

TOKEN = "sim-token-value"


def _client(handler) -> GsClient:  # type: ignore[no-untyped-def]
    return GsClient("http://127.0.0.1:8700", TOKEN, transport=httpx.MockTransport(handler))


def test_registry_parses_nodes_and_sends_token():
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["token"] = req.headers.get("X-BCS-Sim-Token", "")
        return httpx.Response(
            200,
            json={
                "site_id": "KSL",
                "nodes": [
                    {
                        "node_id": "WQ-01",
                        "node_type": "water_quality",
                        "position": {"e_m": 1, "s_m": 2},
                        "zone_label": "A1",
                    },
                    {
                        "node_id": "TG-01",
                        "node_type": "tide_gauge",
                        "position": {"e_m": 250, "s_m": 250},
                        "zone_label": None,
                    },
                ],
            },
        )

    specs = _client(handler).registry()
    assert seen == {"path": "/api/v1/internal/sim/registry", "token": TOKEN}
    assert specs == [
        SimNodeSpec("WQ-01", "water_quality", 1.0, 2.0, "A1", "KSL"),
        SimNodeSpec("TG-01", "tide_gauge", 250.0, 250.0, None, "KSL"),
    ]


def test_credentials_posts_node_ids_and_returns_passwords():
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(
            200, json={"credentials": [{"node_id": "SP-01", "username": "SP-01", "password": "p1"}]}
        )

    c = _client(handler)
    assert c.credentials(["SP-01"]) == {"SP-01": "p1"}
    c.credentials(None)
    assert bodies == [{"node_ids": ["SP-01"]}, {}]


def test_errors_raise_gs_error_without_leaking_token():
    c = _client(lambda req: httpx.Response(403, json={"error": {"code": "forbidden", "message": "no"}}))
    with pytest.raises(GsError) as e:
        c.registry()
    assert "403" in str(e.value) and TOKEN not in str(e.value)


def test_upload_session_is_multipart(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text('{"kind": "bcs.sim-session.v1"}\n', encoding="utf-8")
    got: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        got["path"] = req.url.path
        got["ctype"] = req.headers["content-type"]
        got["body"] = req.content
        return httpx.Response(201, json={"id": "abc"})

    assert _client(handler).upload_session({"id": "abc", "name": "n"}, f) == {"id": "abc"}
    assert got["path"] == "/api/v1/internal/sim/sessions" and got["ctype"].startswith("multipart/form-data")
    assert b'"kind": "bcs.sim-session.v1"' in got["body"] and b'"name": "n"' in got["body"]


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_watcher_tolerates_absent_ground_station():
    calls: list[dict] = []
    w = RegistryWatcher(f"http://127.0.0.1:{_closed_port()}", calls.append, retry_s=0.05)
    w.start()
    deadline = time.monotonic() + 15  # a refused connect takes about 2 s on Windows
    while w.attempts < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    w.stop()
    assert calls == [] and w.attempts >= 2 and not w.is_alive()


def test_watcher_forwards_node_registry_events():
    from websockets.sync.server import serve

    def handler(ws) -> None:  # type: ignore[no-untyped-def]
        ws.send(json.dumps({"v": 1, "type": "hello", "id": "1", "at": "x", "data": {}}))
        ws.send(json.dumps({"v": 1, "type": "zone.metrics", "id": "2", "at": "x", "data": {}}))
        ws.send(
            json.dumps(
                {
                    "v": 1,
                    "type": "node.registry",
                    "id": "3",
                    "at": "x",
                    "data": {"change": "installed", "node_ids": ["WQ-05"]},
                }
            )
        )
        time.sleep(0.5)

    calls: list[dict] = []
    with serve(handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        w = RegistryWatcher(f"http://127.0.0.1:{port}", calls.append, retry_s=0.05)
        w.start()
        deadline = time.monotonic() + 5
        while not calls and time.monotonic() < deadline:
            time.sleep(0.02)
        w.stop()
        server.shutdown()
    assert calls[0] == {"change": "installed", "node_ids": ["WQ-05"]}


def test_inspector_validates_and_feeds_listeners():
    tap = InspectorTap(ManualClock(datetime(2026, 10, 16, tzinfo=UTC)))
    seen: list = []
    tap.add_listener(seen.append)
    tap.emit("up", "WQ-01", "telemetry", "bcs/v1/KSL/nodes/WQ-01/telemetry", b"{bad")
    (p,) = tap.drain()
    assert p.valid is False and p.errors and p.payload == "{bad" and seen == [p]
    msg = p.message()
    assert msg["type"] == "inspector.packet" and msg["data"]["direction"] == "up"
    assert msg["data"]["at"] == "2026-10-16T00:00:00.000Z" and msg["data"]["valid"] is False
    assert tap.drain() == []


def test_lifecycle_calls_use_the_public_node_routes():
    calls: list[tuple[str, str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        calls.append((req.method, req.url.path, body))
        if req.url.path == "/api/v1/nodes":
            return httpx.Response(200, json={"node": {"id": "WQ-05"}, "key": None})
        return httpx.Response(200, json={"id": req.url.path.split("/")[4]})

    c = _client(handler)
    assert c.install_node("water_quality", 10, 20, "WQ-09") == "WQ-05"  # the registry assigns IDs (F1)
    c.move("WQ-05", 30, 40)
    c.remove_node("WQ-05")
    assert calls == [
        (
            "POST",
            "/api/v1/nodes",
            {"node_type": "water_quality", "source": "simulated", "position": {"e_m": 10, "s_m": 20}},
        ),
        ("POST", "/api/v1/nodes/WQ-05/move", {"position": {"e_m": 30, "s_m": 40}, "confirm": True}),
        ("POST", "/api/v1/nodes/WQ-05/decommission", {"confirm": True}),
    ]


def test_ground_station_error_keeps_status_and_body():
    err = {"error": {"code": "confirmation_required", "message": "confirm", "details": None}}
    c = _client(lambda _req: httpx.Response(409, json=err))
    with pytest.raises(GsError) as info:
        c.move_node("WQ-01", {"position": {"e_m": 1, "s_m": 2}})
    assert info.value.status == 409 and info.value.body == err
    assert TOKEN not in str(info.value)


def test_unreachable_ground_station_has_no_status():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(GsError) as info:
        _client(handler).create_node({"node_type": "soil_probe"})
    assert info.value.status is None and info.value.body is None
