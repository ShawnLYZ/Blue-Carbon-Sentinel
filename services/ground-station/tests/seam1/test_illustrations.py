"""M5 Task 6: FLUX keyframe illustrations over the real app (seam 1). A FakeIllustrator is injected through
``Overrides`` (this module overrides the ``gs_illustrator`` fixture); automated tests never call NVIDIA."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import cv2
import numpy as np
import pytest
from bcs_gs.futures import jobs as jobs_mod
from bcs_gs.futures.illustrator import IllustratorError
from gs_forecast import (
    FakeIllustrator,
    FluxWorld,
    illustration_rows,
    run_and_wait,
    wait_all_illustrations,
    wait_count,
)

SUFFIX = "Keep everything else identical; top-down view of a handmade clay mangrove model."


@pytest.fixture
def gs_illustrator() -> FakeIllustrator:
    return FakeIllustrator()


@pytest.fixture
async def world_ready_flux_ok(world_ready: Any, gs_illustrator: FakeIllustrator) -> AsyncIterator[FluxWorld]:
    yield FluxWorld(world_ready, gs_illustrator)


@pytest.fixture
async def world_ready_flux_failing(
    world_ready: Any, gs_illustrator: FakeIllustrator
) -> AsyncIterator[FluxWorld]:
    gs_illustrator.error = IllustratorError("credits", "NVIDIA returned 402")
    yield FluxWorld(world_ready, gs_illustrator)


async def test_illustrator_failure_marks_failed_and_keeps_repaint(world_ready_flux_failing):  # Review Focus 1
    f = await run_and_wait(world_ready_flux_failing)
    ills = await wait_all_illustrations(world_ready_flux_failing, f["id"])
    assert {i["status"] for i in ills} <= {"failed", "skipped"} and all(
        i["error"] or i["status"] == "skipped" for i in ills
    )
    assert any(i["status"] == "failed" and i["error"].startswith("credits") for i in ills)
    assert world_ready_flux_failing.flux.calls >= 1
    r = await world_ready_flux_failing.http.get(f"/api/v1/media/futures/{f['id']}/with/2035/texture")
    assert r.status_code == 200


async def test_cached_illustration_not_requested_twice(world_ready_flux_ok):
    f = await run_and_wait(world_ready_flux_ok)
    await wait_all_illustrations(world_ready_flux_ok, f["id"])
    calls_before = world_ready_flux_ok.flux.calls
    assert calls_before >= 1  # something changed enough to be illustrated
    await world_ready_flux_ok.illustrations.run(f["id"])
    assert world_ready_flux_ok.flux.calls == calls_before


async def test_ready_illustration_is_stored_composited_and_announced_once(world_ready_flux_ok, monkeypatch):
    # In this world every zone passes the threshold (about 3 m of erosion everywhere by 2030), so the
    # changed set is pinned to one zone to see the compositing.
    monkeypatch.setattr(jobs_mod, "changed_zones", lambda *a, **k: ["KSL-B3"])
    w = world_ready_flux_ok
    async with w.events() as ev:
        f = await run_and_wait(w)
        rows = await wait_all_illustrations(w, f["id"])
        await wait_count(ev, "illustration.ready", lambda d: d["forecast_id"] == f["id"], 4, 30)
        await asyncio.sleep(0.3)
        got = [e["data"] for e in ev.all("illustration.ready") if e["data"]["forecast_id"] == f["id"]]
    assert len(got) == 4  # exactly one per row end state
    assert sorted((r["scenario"], r["year"]) for r in rows) == [
        ("with", 2030), ("with", 2035), ("without", 2030), ("without", 2035),
    ]  # fmt: skip
    ready = [r for r in rows if r["status"] == "ready"]
    assert len(ready) == 4
    svc = w.gs.services
    base = svc.futures.read_inputs(f["base_capture_id"])[0]
    for r in ready:
        assert r["media_key"] == f"{f['id']}/illustrations/{r['scenario']}-{r['year']}.jpg"
        assert (
            r["provider"] == "fake" and r["model"] == "black-forest-labs/flux.2-klein-4b" and r["seed"] == 42
        )
        assert r["instruction"].endswith(SUFFIX) and len(r["cache_key"]) == 64 and r["error"] is None
        img = cv2.imread(str(svc.media.path("futures", r["media_key"])), cv2.IMREAD_COLOR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        assert img.shape == (512, 512, 3)
        # Inverted colours inside changed zones only: most of the image stays the real capture.
        diff = np.abs(img.astype(int) - base.astype(int)).max(axis=2)
        b3 = svc.futures.grid(512).mask("KSL-B3")
        assert (diff[b3] > 60).mean() > 0.9  # inverted inside the changed zone
        assert diff[~b3].mean() < 3 and (diff[~b3] > 60).mean() < 0.001  # the real capture (JPEG) outside
        assert r["instruction"].count(".") == 2 and "central-west zone" in r["instruction"]  # B3
        evd = next(d for d in got if d["id"] == r["id"])
        assert evd["status"] == "ready" and evd["url"] == f"/api/v1/media/illustrations/{r['id']}.jpg"
    assert len(w.flux.instructions) == len(ready)


async def test_no_changed_zones_skips_without_calling(world_ready_flux_ok, monkeypatch):
    monkeypatch.setattr(jobs_mod, "changed_zones", lambda *a, **k: [])
    f = await run_and_wait(world_ready_flux_ok)
    rows = await wait_all_illustrations(world_ready_flux_ok, f["id"])
    assert {r["status"] for r in rows} == {"skipped"} and world_ready_flux_ok.flux.calls == 0
    assert all(r["media_key"] is None for r in rows)


async def test_budget_exhausted_rows_end_failed(world_ready_flux_ok):
    w = world_ready_flux_ok
    w.flux.delay_s = 1.0
    w.gs.services.illustrations.budget_s = 0.3
    f = await run_and_wait(w)
    rows = await wait_all_illustrations(w, f["id"])
    failed = [r for r in rows if r["status"] == "failed"]
    assert w.flux.calls == 1  # the first call runs out the budget; nothing else starts
    assert any(r["error"].startswith("timeout") for r in failed)
    assert len(failed) >= 2 and sum(r["error"] == "budget exhausted" for r in failed) == len(failed) - 1
    assert all(r["status"] in {"failed", "skipped"} for r in rows)


async def test_rows_are_pending_until_their_job_ends(world_ready_flux_ok):
    w = world_ready_flux_ok
    w.flux.delay_s = 1.0
    f = await run_and_wait(w)
    deadline = asyncio.get_running_loop().time() + 30
    while len(rows := await illustration_rows(w, f["id"])) < 4:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)
    assert "pending" in {r["status"] for r in rows}  # created first, then run one after another
    await wait_all_illustrations(w, f["id"])


async def test_rerun_after_the_sticky_window_calls_again(world_ready_flux_failing, monkeypatch):
    w = world_ready_flux_failing
    f = await run_and_wait(w)
    await wait_all_illustrations(w, f["id"])
    before = w.flux.calls
    w.flux.error = None
    await w.illustrations.run(f["id"])  # credits failures are sticky (R25): still no call
    assert w.flux.calls == before
    later = time.monotonic() + jobs_mod.STICKY_S + 1
    monkeypatch.setattr(jobs_mod, "_sticky_clock", lambda: later)  # 30 min on
    await w.illustrations.run(f["id"])
    rows = await illustration_rows(w, f["id"])
    assert w.flux.calls > before and "ready" in {r["status"] for r in rows}


EXAMPLE_ID_422 = "NVIDIA returned 422 (Expected: example_id, got: base64)"


@pytest.mark.parametrize(
    "error",
    [IllustratorError("bad_response", EXAMPLE_ID_422), IllustratorError("auth", "NVIDIA returned 401"),
     IllustratorError("credits", "NVIDIA returned 429")],
)  # fmt: skip
async def test_sticky_failure_makes_one_call_then_none(world_ready_flux_ok, error):  # ruling R25
    w = world_ready_flux_ok
    w.flux.error = error
    f = await run_and_wait(w)
    rows = await wait_all_illustrations(w, f["id"])
    assert w.flux.calls == 1  # the first row's call fails; the other three make none
    assert len(rows) == 4 and all(r["status"] == "failed" and r["error"] == str(error) for r in rows)
    await w.illustrations.run(f["id"])  # a rerun inside the window: still no call
    assert w.flux.calls == 1
    rows = await illustration_rows(w, f["id"])
    assert all(r["status"] == "failed" and r["error"] == str(error) for r in rows)


async def test_non_sticky_failure_is_retried_on_each_row(world_ready_flux_ok):
    w = world_ready_flux_ok
    w.flux.error = IllustratorError("server", "NVIDIA returned 503")
    f = await run_and_wait(w)
    await wait_all_illustrations(w, f["id"])
    assert w.flux.calls == 4


@pytest.mark.parametrize("stage", ["_load", "_ensure_rows"])
async def test_run_failure_fails_every_row_with_an_event(world_ready_flux_ok, monkeypatch, stage):  # R22c
    def boom(self, *a, **k):
        raise RuntimeError(f"{stage} boom")

    monkeypatch.setattr(jobs_mod.IllustrationJobs, stage, boom)
    w = world_ready_flux_ok
    async with w.events() as ev:
        f = await run_and_wait(w)
        rows = await wait_all_illustrations(w, f["id"])
        await wait_count(ev, "illustration.ready", lambda d: d["forecast_id"] == f["id"], 4, 30)
        await asyncio.sleep(0.3)
        got = [e["data"] for e in ev.all("illustration.ready") if e["data"]["forecast_id"] == f["id"]]
    assert all(r["status"] == "failed" and r["error"] == f"RuntimeError: {stage} boom" for r in rows)
    assert sorted(d["id"] for d in got) == sorted(r["id"] for r in rows)
    assert w.flux.calls == 0


async def test_row_failure_while_building_the_instruction_fails_that_row(world_ready_flux_ok, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("instruction boom")

    monkeypatch.setattr(jobs_mod, "build_instruction", boom)
    w = world_ready_flux_ok
    async with w.events() as ev:
        f = await run_and_wait(w)
        rows = await wait_all_illustrations(w, f["id"])
        await wait_count(ev, "illustration.ready", lambda d: d["forecast_id"] == f["id"], 4, 30)
        await asyncio.sleep(0.3)
        n = len([e for e in ev.all("illustration.ready") if e["data"]["forecast_id"] == f["id"]])
    assert n == 4 and w.flux.calls == 0
    assert all(r["status"] == "failed" and r["error"] == "RuntimeError: instruction boom" for r in rows)


async def test_illustrated_zones_are_capped_at_6(world_ready_flux_ok):  # ruling R24
    w = world_ready_flux_ok
    f = await run_and_wait(w)
    rows = await wait_all_illustrations(w, f["id"])
    ready = [r for r in rows if r["status"] == "ready"]
    assert ready
    for r in ready:
        body = r["instruction"][: -len(SUFFIX)]
        assert 1 <= body.count(".") <= 6  # one sentence per illustrated zone


async def test_illustration_routes_serve_ready_rows(world_ready_flux_ok):
    w = world_ready_flux_ok
    f = await run_and_wait(w)
    rows = await wait_all_illustrations(w, f["id"])
    listed = {r["id"]: r for r in (await w.http.get(f"/api/v1/forecasts/{f['id']}/illustrations")).json()}
    ready = [r for r in rows if r["status"] == "ready"]
    assert ready
    for r in ready:
        assert listed[r["id"]]["url"] == f"/api/v1/media/illustrations/{r['id']}.jpg"
        got = await w.http.get(listed[r["id"]]["url"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
        assert got.content[:2] == b"\xff\xd8"
    for r in rows:
        if r["status"] != "ready":
            assert listed[r["id"]]["url"] is None
            assert (await w.http.get(f"/api/v1/media/illustrations/{r['id']}.jpg")).status_code == 404
