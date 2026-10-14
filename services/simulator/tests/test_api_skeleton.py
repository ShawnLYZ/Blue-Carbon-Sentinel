import asyncio
import json

import httpx
import pytest
from bcs_sim.app import create_sim_app
from bcs_sim.config import SimSettings, load_sim_settings

K1_ROUTES = [
    ("GET", "/api/v1/state"),
    ("GET", "/api/v1/scenarios"),
    ("POST", "/api/v1/zones/{zone_label}/scenario"),
    ("DELETE", "/api/v1/zones/{zone_label}/scenario"),
    ("POST", "/api/v1/nodes/{node_id}/overrides"),
    ("DELETE", "/api/v1/nodes/{node_id}/overrides/{parameter}"),
    ("POST", "/api/v1/nodes/{node_id}/health"),
    ("POST", "/api/v1/nodes/{node_id}/faults"),
    ("DELETE", "/api/v1/nodes/{node_id}/faults/{kind}"),
    ("PATCH", "/api/v1/nature"),
    ("POST", "/api/v1/lifecycle/install"),
    ("POST", "/api/v1/lifecycle/{node_id}/move"),
    ("POST", "/api/v1/lifecycle/{node_id}/remove"),
    ("POST", "/api/v1/recording/start"),
    ("POST", "/api/v1/recording/stop"),
    ("GET", "/api/v1/sessions"),
    ("POST", "/api/v1/sessions/{session_id}/replay"),
    ("POST", "/api/v1/replay/stop"),
    ("POST", "/api/v1/scenario-runs"),
    ("GET", "/api/v1/scenario-runs/{run_id}"),
]


def sim_settings(**kw) -> SimSettings:
    return load_sim_settings(env_file=None, **kw)


@pytest.fixture
async def sim_http():
    app = create_sim_app(sim_settings(demo_time_scale="on"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_state_route_returns_empty_skeleton(sim_http):
    s = (await sim_http.get("/api/v1/state")).json()
    assert s["nodes"] == [] and s["demo_time_scale"] is True
    assert s == {
        "broker_connected": False,
        "demo_time_scale": True,
        "fast_forward": 1,
        "nature": {},
        "nodes": [],
        "zone_scenarios": {},
        "recording": None,
        "replay": None,
    }


def test_every_k1_route_declared():
    paths = {(m.upper(), p) for p, i in create_sim_app(sim_settings()).openapi()["paths"].items() for m in i}
    assert [r for r in K1_ROUTES if r not in paths] == []


async def test_cors_allows_ground_station_origin(sim_http):
    r = await sim_http.options(
        "/api/v1/state", headers={"Origin": "http://127.0.0.1:8700", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:8700"


async def test_cors_rejects_other_origin(sim_http):
    r = await sim_http.options(
        "/api/v1/state", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in r.headers


async def test_runtime_routes_answer_503_until_the_runtime_starts(sim_http):
    assert (await sim_http.get("/api/v1/scenarios")).status_code == 200  # static catalogue
    r = await sim_http.post("/api/v1/replay/stop")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "upstream_unavailable" and err["details"] == {"last_error": None}


async def test_unknown_route_and_wrong_method_use_the_i1_envelope(sim_http):
    r = await sim_http.get("/api/v1/no-such-route")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Not Found", "details": None}}
    r = await sim_http.delete("/api/v1/state")
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"


async def test_validation_failure_uses_the_i1_envelope_with_422():
    app = create_sim_app(sim_settings())

    @app.get("/api/v1/_probe")
    async def probe(n: int) -> dict[str, int]:
        return {"n": n}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/_probe", params={"n": "abc"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and err["message"] == "Request validation failed."
    assert err["details"]["errors"][0]["loc"] == ["query", "n"]


async def test_demo_time_scale_off_reports_false():
    app = create_sim_app(sim_settings(demo_time_scale="off"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/state")).json()["demo_time_scale"] is False


async def test_ws_accepts_and_sends_status():
    app = create_sim_app(sim_settings())
    incoming = [{"type": "websocket.connect"}]
    sent: list[dict] = []
    disconnect = asyncio.Event()

    async def receive():
        if incoming:
            return incoming.pop(0)
        await disconnect.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(msg):
        sent.append(msg)
        if msg["type"] == "websocket.send":
            disconnect.set()

    scope = {"type": "websocket", "path": "/ws", "headers": [], "query_string": b"", "subprotocols": []}
    await app(scope, receive, send)
    assert sent[0]["type"] == "websocket.accept"
    assert json.loads(sent[1]["text"])["type"] == "sim.status"


def test_dotenv_escapes_are_unescaped(tmp_path):
    env = tmp_path / ".env"
    env.write_text(r'BCS_SIM_SHARED_TOKEN="a\"b\\c"' + "\n", encoding="utf-8")  # file holds "a\"b\\c"
    assert load_sim_settings(env_file=env).sim_shared_token.get_secret_value() == r'a"b\c'
