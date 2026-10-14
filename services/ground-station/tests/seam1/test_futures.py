"""M5 Task 5: the FutureRenderer's files and GET /media/futures over HTTP (seam 1, test-mode world)."""

from __future__ import annotations

import asyncio
import shutil

import cv2
import numpy as np
from bcs_gs.futures.renderer import FutureRenderer
from gs_forecast import on_gs_loop, run_and_render, start_forecast, strip_base_media, wait_count

YEARS = range(2026, 2036)


def mine(fid):
    return lambda d: d["forecast_id"] == fid


async def tex_at(world, fid, sc, y):
    b = (await world.http.get(f"/api/v1/media/futures/{fid}/{sc}/{y}/texture")).content
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


async def test_seeded_capture_forecast_renders_20_textures_and_20_heights(world_ready):
    f = await run_and_render(world_ready)  # no media attached: the seeded capture is synthetic (R22a)
    rows = await world_ready.rows("media_objects", bucket="futures")
    keys = {r["key"] for r in rows}
    want = {
        f"{f['id']}/{sc}/{y}/{name}" for sc in ("without", "with") for y in YEARS
        for name in ("texture.jpg", "height.png")
    }  # fmt: skip
    assert keys == want and len(keys) == 40
    assert all(r["state"] == "pending" for r in rows)  # queued for the cloud (H6)

    r = await world_ready.http.get(f"/api/v1/media/futures/{f['id']}/with/2035/texture")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR).shape == (512, 512, 3)
    r = await world_ready.http.get(f"/api/v1/media/futures/{f['id']}/without/2030/height")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    h = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert h.dtype == np.uint16 and h.shape == (512, 512)

    # 2026 is the real capture in both scenarios; 2035 without a plan has changed somewhere.
    a = await tex_at(world_ready, f["id"], "without", 2026)
    b = await tex_at(world_ready, f["id"], "with", 2026)
    assert (a == b).all()
    assert (a != await tex_at(world_ready, f["id"], "without", 2035)).any()


async def test_futures_media_404_for_unknown_forecast_and_bad_kind(world_ready):
    for path in ("nope/with/2035/texture", "nope/with/2035/height", "nope/sideways/2035/texture"):
        r = await world_ready.http.get(f"/api/v1/media/futures/{path}")
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json")  # an error, never an image
    f = await run_and_render(world_ready)
    r = await world_ready.http.get(f"/api/v1/media/futures/{f['id']}/with/2035/colour")
    assert r.status_code == 404


async def test_test_mode_illustrations_end_unavailable_or_skipped(world_ready):
    """After the render the IllustrationJobs (Task 6) run; test mode's DisabledIllustrator never reaches
    NVIDIA, so every row ends failed ("unavailable") or skipped, one event each."""
    async with world_ready.events() as ev:
        fid = await start_forecast(world_ready)
        await wait_count(ev, "illustration.ready", mine(fid), 4, 30)
        await asyncio.sleep(0.3)
        got = [e["data"] for e in ev.all("illustration.ready") if mine(fid)(e["data"])]
    assert sorted((d["scenario"], d["year"]) for d in got) == [
        ("with", 2030), ("with", 2035), ("without", 2030), ("without", 2035),
    ]  # fmt: skip
    assert all(d["url"] is None and d["status"] in {"failed", "skipped"} for d in got)
    assert all(d["error"].startswith("unavailable") for d in got if d["status"] == "failed")
    rows = await world_ready.rows("illustrations", forecast_id=fid)
    assert sorted(r["id"] for r in rows) == sorted(d["id"] for d in got)
    assert all(r["provider"] == "none" for r in rows)


async def test_no_base_media_ends_with_failed_placeholders_and_a_reason(world_ready):  # R22c
    await strip_base_media(world_ready)
    async with world_ready.events() as ev:
        fid = await start_forecast(world_ready)
        await wait_count(ev, "illustration.ready", mine(fid), 4, 30)
        got = [e["data"] for e in ev.all("illustration.ready") if mine(fid)(e["data"])]
    assert len(got) == 4 and all(d["status"] == "failed" and "no stored raster" in d["error"] for d in got)
    rows = await world_ready.rows("illustrations", forecast_id=fid)  # the rows carry the reason too
    assert len(rows) == 4 and all(r["status"] == "failed" and "no stored raster" in r["error"] for r in rows)
    r = await world_ready.http.get(f"/api/v1/media/futures/{fid}/with/2035/texture")
    assert r.status_code == 404


async def test_render_failure_ends_with_failed_placeholders_and_a_reason(world_ready, monkeypatch):  # R22c
    def boom(self, forecast_id, gen=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(FutureRenderer, "_render_sync", boom)
    async with world_ready.events() as ev:
        fid = await start_forecast(world_ready)
        await wait_count(ev, "illustration.ready", mine(fid), 4, 30)
        got = [e["data"] for e in ev.all("illustration.ready") if mine(fid)(e["data"])]
    assert all(d["status"] == "failed" and d["error"] == "RuntimeError: boom" for d in got)


def drop_futures(world):
    shutil.rmtree(world.gs.services.data_root / "var" / "media" / "futures", ignore_errors=True)


async def test_startup_catch_up_renders_ready_forecasts_missing_futures(world_ready):  # R22b
    f = await run_and_render(world_ready)
    drop_futures(world_ready)
    svc = world_ready.gs.services

    async def restart():
        r = FutureRenderer(repo=svc.repo, bus=svc.bus, media=svc.media, site=svc.site, fusion=svc.fusion)
        r.start()  # what the lifespan does at start
        return r

    async with world_ready.events() as ev:
        r = await on_gs_loop(world_ready, restart)
        await wait_count(ev, "illustration.ready", mine(f["id"]), 4, 30)
    await on_gs_loop(world_ready, r.stop)
    assert len(await world_ready.rows("media_objects", bucket="futures")) == 40
    assert (
        await world_ready.http.get(f"/api/v1/media/futures/{f['id']}/with/2035/height")
    ).status_code == 200


async def test_media_404_for_ready_forecast_starts_one_lazy_render(world_ready):  # R22b
    f = await run_and_render(world_ready)
    drop_futures(world_ready)
    url = f"/api/v1/media/futures/{f['id']}/with/2035/texture"
    async with world_ready.events() as ev:
        codes = [(await world_ready.http.get(url)).status_code for _ in range(3)]  # all 404, one render
        assert codes == [404, 404, 404]
        await wait_count(ev, "illustration.ready", mine(f["id"]), 4, 30)
        await asyncio.sleep(0.5)
        assert len([e for e in ev.all("illustration.ready") if mine(f["id"])(e["data"])]) == 4
    assert (await world_ready.http.get(url)).status_code == 200


async def test_render_uses_the_forecasts_stored_stressors_not_live_ones(world_ready):  # M5 follow-up
    f = await run_and_render(world_ready)
    svc = world_ready.gs.services
    row = (await world_ready.rows("forecasts", id=f["id"]))[0]
    stored = row["summary"]["base_stressors"]  # captured with the forecast (its starting state)
    assert set(stored) and all(isinstance(v, dict) for v in stored.values())
    before = await tex_at(world_ready, f["id"], "with", 2035)

    def live(*_a, **_k):
        raise AssertionError("the renderer read live assessments")

    svc.fusion.list_assessments = live
    await asyncio.to_thread(svc.futures._render_sync, f["id"])  # re-render: reproducible from the row alone
    assert (await tex_at(world_ready, f["id"], "with", 2035) == before).all()
