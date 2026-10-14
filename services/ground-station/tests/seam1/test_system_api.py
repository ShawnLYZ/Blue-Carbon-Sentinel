"""Seam 1: system, site, events socket and test mode of the Ground Station API."""

import asyncio

import pytest
from bcs_gs.api.app import Overrides, create_app
from bcs_gs.core.config import Settings


async def test_unbuilt_route_returns_501_with_milestone():
    """Every I2 route is built as of M7; the 501 mechanism is checked on a stand-in route."""
    import httpx
    from bcs_gs.api.errors import install_error_handlers, not_implemented
    from fastapi import FastAPI

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/unbuilt")
    async def unbuilt():
        not_implemented("M7")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/unbuilt")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented" and r.json()["error"]["details"] == {
        "milestone": "M7"
    }


async def test_public_config_exposes_only_mapbox_token(gs):
    body = (await gs.http.get("/api/v1/system/config")).text
    assert gs.settings.mapbox_public_token.get_secret_value() in body
    secrets = gs.settings.secret_values_except_mapbox()
    assert secrets  # the fixture injects fake secrets so this check has teeth
    for secret in secrets:
        assert secret not in body
    cfg = (await gs.http.get("/api/v1/system/config")).json()
    assert cfg["sim_url"] == "http://127.0.0.1:8701" and cfg["site"]["id"] == "KSL"
    assert cfg["demo_time"]["capture_interval_s"] == 10


async def test_public_config_sim_url_follows_the_sim_port_setting(gs):
    gs.services.settings.sim_port = 9123
    cfg = (await gs.http.get("/api/v1/system/config")).json()
    assert cfg["sim_url"] == "http://127.0.0.1:9123"


async def test_site_and_zones_basic(gs):
    site = (await gs.http.get("/api/v1/site")).json()
    assert site["id"] == "KSL" and len(site["zones"]) == 25 and len(site["planned_sites"]) == 4
    zones = (await gs.http.get("/api/v1/zones")).json()
    assert len(zones) == 25 and zones[0]["zone"]["id"] == "KSL-A1" and zones[0]["metrics"] is None


async def test_sites_and_zones_are_upserted_into_the_store(gs):
    rows = gs.services.repo.query("SELECT COUNT(*) AS n FROM zones")
    assert rows[0]["n"] == 25
    assert gs.services.repo.get("sites", {"id": "KSL"})["name"]


async def test_events_socket_says_hello_then_status(gs):
    async with gs.events() as ev:
        hello = await ev.next()
        assert hello["type"] == "hello" and hello["v"] == 1 and hello["data"]["version"]
        gs.clock.advance(5)
        assert (await ev.wait_for("system.status"))["data"]["version"]


async def test_start_with_failing_cloud_buffers_and_serves(gs_failing_cloud):  # Review Focus 1
    r = await gs_failing_cloud.http.get("/api/v1/system/status")
    assert r.status_code == 200 and r.json()["sync"]["state"] in ("buffering", "offline")
    assert r.json()["sync"]["queue"] > 0
    for _ in range(100):  # the first background pass fails right after start
        st = (await gs_failing_cloud.http.get("/api/v1/system/status")).json()
        sync = next(c for c in st["components"] if c["id"] == "sync")
        if sync["details"]["failures"] >= 1:  # consecutive failed passes: perf samples lag only at 0 (M8)
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"no failure reported: {sync}")


async def test_system_status_shape(gs):
    st = (await gs.http.get("/api/v1/system/status")).json()
    assert {c["id"] for c in st["components"]} == {
        "camera", "ground_station", "broker", "cloud", "sync", "ai", "image_service", "gpu", "ollama", "simulator",
    }  # fmt: skip
    assert st["started_at"].endswith("Z") and st["depth"]["mode"] == "off"
    assert st["cloud"]["storage_budget_bytes"] == 800_000_000


async def test_preflight_reports_each_check(gs):
    r = await gs.http.post("/api/v1/system/preflight")
    ids = {c["id"] for c in r.json()["checks"]}
    assert {"mapbox_token", "gemini_keys", "nvidia_key", "supabase", "disk"} <= ids
    assert (await gs.http.get("/api/v1/system/preflight")).json()["ran_at"] == r.json()["ran_at"]


async def test_settings_patch_persists(gs):
    await gs.http.patch("/api/v1/system/settings", json={"vertical_exaggeration": 1.5})
    assert (await gs.http.get("/api/v1/system/settings")).json()["vertical_exaggeration"] == 1.5


async def test_settings_validation_error_uses_envelope(gs):
    r = await gs.http.patch("/api/v1/system/settings", json={"vertical_exaggeration": 9})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_unknown_route_is_not_found_envelope(gs):
    r = await gs.http.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_test_routes_clock_cloud_reset(gs):
    t0 = gs.clock.now()
    assert (await gs.http.post("/api/v1/test/clock/advance", json={"seconds": 60})).status_code == 200
    assert (gs.clock.now() - t0).total_seconds() == 60
    await gs.http.post("/api/v1/test/clock/set", json={"at": "2026-10-16T03:04:05.123Z"})
    assert gs.clock.now().year == 2026 and gs.clock.now().day == 16
    await gs.http.post("/api/v1/test/cloud/fail", json={"failing": True})
    assert gs.cloud.failing is True
    await gs.http.patch("/api/v1/system/settings", json={"live_max_fps": 3})
    assert (await gs.http.post("/api/v1/test/reset")).status_code == 200
    assert (await gs.http.get("/api/v1/system/settings")).json()["live_max_fps"] == 10
    assert len((await gs.http.get("/api/v1/site")).json()["zones"]) == 25  # site rows are re-seeded


async def test_static_hosting_placeholder_pages(gs):
    for path in ("/", "/console/"):
        r = await gs.http.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_settings_secret_helper_excludes_mapbox():
    from pathlib import Path

    from bcs_gs.core.config import load_settings

    s: Settings = load_settings(
        Path(__file__).resolve().parents[4],
        env_file=None,
        mapbox_public_token="pk.m",
        nvidia_api_key="nv-secret-1",
    )
    assert "nv-secret-1" in s.secret_values_except_mapbox()
    assert "pk.m" not in s.secret_values_except_mapbox()
    assert create_app(s, overrides=Overrides(test_mode=False)) is not None


async def test_events_socket_closes_1013_on_overflow(gs):
    from websockets.exceptions import ConnectionClosed

    async with gs.events() as ev:
        assert (await ev.next())["type"] == "hello"
        await gs.http.post("/api/v1/test/events/burst", json={"count": 1500})
        with pytest.raises(ConnectionClosed) as info:
            while True:
                await ev.next()
        assert info.value.rcvd.code == 1013


async def test_events_envelope_and_sync_status(gs):
    async with gs.events() as ev:
        await ev.next()
        await gs.http.post("/api/v1/test/events/burst", json={"count": 1, "type": "x.y"})
        e = await ev.wait_for("x.y")
        assert e["v"] == 1 and e["data"] == {"i": 0} and e["at"].endswith("Z") and len(e["id"]) == 36


async def test_unit_secrets_never_reach_the_logs(gs, caplog):
    import logging

    logging.getLogger("bcs_gs.test").warning("key is %s", "sb-service-role-secret")
    from bcs_gs.core.logging import RedactFilter

    rec = logging.LogRecord("x", logging.WARNING, __file__, 1, "key %s", ("nvapi-secret-value",), None)
    assert RedactFilter().filter(rec) and "nvapi-secret-value" not in rec.getMessage()


async def test_bands_route_serves_the_configured_breakpoints(gs):
    body = (await gs.http.get("/api/v1/system/bands")).json()
    do = body["parameters"]["do_mg_l"]
    assert do["unit"] == "mg/L" and do["breakpoints"][0] == [0.5, 1.0]
    assert body["class_limits"] == {"low": 30, "medium": 60, "high": 80}
    assert set(body["parameters"]) >= {"salinity_psu", "turbidity_ntu", "ph", "temp_c"}
