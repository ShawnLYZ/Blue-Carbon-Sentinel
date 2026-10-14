"""Seam-1 forecast helpers and fixtures (M5), built on ``world``. Reused by the plan (Task 4) and
illustration (Task 6) tests.

- ``world_ready``: ``world`` with a healthy evidence-grade baseline, then a later evidence-grade capture
  with a flagged zone (KSL-B3), and that zone's assessments for the flagged capture stored: the code-only
  one and the RiskInterpreter's (the flag starts an AI interpretation). Test mode: every role answers from
  the rules tier. Waiting for both keeps late assessments from changing forecast inputs mid-test.
- ``await run_and_wait(world, plan_id=None)``: ``POST /forecasts``, wait for its ``forecast.ready`` and
  return the stored forecast (asserted ``ready``).
- ``await seed_varied(world)``: a new evidence-grade capture where every zone has its own canopy (KSL-B3
  stays flagged), so every zone has its own parameter cache key. Returns once every zone whose
  canopy changed has its assessment for this capture stored (KSL-B3 repeats its previous assessment, which
  the fusion engine skips).
- ``install_cloud_fpe(world, delay_s=0)``: a fake Gemini provider that answers every
  ForecastParameterEstimator call with a valid output (after ``delay_s`` real seconds); returns it
  (``.calls`` counts calls).
- ``await on_gs_loop(world, fn)``: run ``await fn()`` on the Ground Station's event loop.
- ``await propose_and_wait(world, zone_ids=None)``: ``POST /plans/propose``, wait for the draft's
  ``plan.updated`` (its plan ID is the request ID) and return the stored version 1.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from gs_assess import FLAG_CANOPY_PCT, _seed_capture, seed_flag

FORECAST_TIMEOUT_S = 30


async def start_forecast(world: Any, plan_id: str | None = None) -> str:
    body = {} if plan_id is None else {"plan_id": plan_id}
    r = await world.http.post("/api/v1/forecasts", json=body)
    assert r.status_code == 202, r.text
    return r.json()["forecast_id"]


async def run_and_wait(world: Any, plan_id: str | None = None, *, status: str = "ready") -> dict[str, Any]:
    async with world.events() as ev:
        fid = await start_forecast(world, plan_id)
        e = await ev.wait_for("forecast.ready", lambda d: d["forecast_id"] == fid, timeout=FORECAST_TIMEOUT_S)
    assert e["data"]["status"] == status, e
    r = await world.http.get(f"/api/v1/forecasts/{fid}")
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["status"] == status, f
    return f


async def propose_and_wait(world: Any, zone_ids: list[str] | None = None) -> dict[str, Any]:
    body = {} if zone_ids is None else {"zone_ids": zone_ids}
    async with world.events() as ev:
        r = await world.http.post("/api/v1/plans/propose", json=body)
        assert r.status_code == 202, r.text
        plan_id = r.json()["request_id"]
        await ev.wait_for("plan.updated", lambda d: d["plan_id"] == plan_id, timeout=FORECAST_TIMEOUT_S)
    r = await world.http.get(f"/api/v1/plans/{plan_id}")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["version"] == 1 and p["source"] == "ai" and p["status"] == "draft", p
    return p


@pytest.fixture
async def world_ready(world: Any) -> AsyncIterator[Any]:
    async with world.events() as ev:
        cap = await seed_flag(world, "KSL-B3")  # healthy baseline first, then the flagged capture

        def flagged(d: dict[str, Any]) -> bool:
            return d["zone_id"] == "KSL-B3" and d.get("capture_id") == cap["id"]

        # The code-only assessment, then the RiskInterpreter's one the flag starts in the background.
        await wait_count(ev, "zone.assessed", flagged, 2, timeout=15)
    yield world


async def wait_count(ev: Any, type: str, pred: Any, n: int, timeout: float) -> list[dict[str, Any]]:
    """Wait until the event view holds at least ``n`` ``type`` events matching ``pred(data)``."""
    deadline = time.monotonic() + timeout
    while True:
        found = [e for e in ev.all(type) if pred(e["data"])]
        if len(found) >= n:
            return found
        if time.monotonic() > deadline:
            raise AssertionError(f"{len(found)} of {n} {type} events within {timeout} s")
        await asyncio.sleep(0.02)


async def seed_varied(world: Any) -> dict[str, Any]:
    zones = [z["zone"]["id"] for z in (await world.http.get("/api/v1/zones")).json()]
    metrics = {z: {"canopy_pct": 51.0 + 0.3 * i} for i, z in enumerate(zones)}  # under 10 pp loss
    metrics["KSL-B3"] = {"canopy_pct": FLAG_CANOPY_PCT}  # as before: the fusion engine skips its repeat
    changed = set(zones) - {"KSL-B3"}
    async with world.events() as ev:
        cap = await _seed_capture(world, metrics)

        def assessed(d: dict[str, Any]) -> bool:
            return d["zone_id"] in changed and d.get("capture_id") == cap["id"]

        await wait_count(ev, "zone.assessed", assessed, len(changed), timeout=15)
    return cap


class CloudFpe:
    """Stands in for Gemini: a valid FPE output (the rules defaults) for every call."""

    def __init__(self, output: dict[str, Any], delay_s: float = 0.0) -> None:
        self.output, self.delay_s = output, delay_s
        self.provider = "gemini"
        self.calls = 0

    async def generate(self, model: str, req: Any, key_slot: int | None) -> dict:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return dict(self.output)


def install_cloud_fpe(world: Any, delay_s: float = 0.0) -> CloudFpe:
    svc = world.gs.services
    defaults = svc.settings.forecast.rules_defaults
    out = {
        "params": {k: dict(v) for k, v in defaults.items()},
        "justification": {k: "test" for k in defaults},
    }
    prov = CloudFpe(out, delay_s)
    svc.ai.providers["gemini"] = prov
    return prov


async def on_gs_loop(world: Any, fn: Any) -> Any:
    loop = world.gs.services.tasking.loop
    assert loop is not None, "services not started"
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(fn(), loop))


async def attach_base_media(world: Any) -> dict[str, Any]:
    """The latest capture. Seeded captures carry synthetic image / classes / height files themselves
    (ruling R22a), so there is nothing to attach; kept for callers written before that."""
    return (await world.http.get("/api/v1/captures/latest")).json()


async def strip_base_media(world: Any) -> None:
    """Remove the media keys of every capture row (a capture whose files are gone)."""
    svc = world.gs.services

    def strip() -> None:
        for row in svc.repo.query("SELECT * FROM captures", table="captures"):
            svc.repo.upsert("captures", {**row, "media": {}}, sync=False)

    await asyncio.to_thread(strip)


async def run_and_render(world: Any) -> dict[str, Any]:
    """``run_and_wait`` plus the forecast's four ``illustration.ready`` events (the IllustrationJobs run
    after the files are written). Returns the stored forecast."""
    async with world.events() as ev:
        fid = await start_forecast(world)
        await ev.wait_for("forecast.ready", lambda d: d["forecast_id"] == fid, timeout=FORECAST_TIMEOUT_S)
        await wait_count(ev, "illustration.ready", lambda d: d["forecast_id"] == fid, 4, FORECAST_TIMEOUT_S)
    return (await world.http.get(f"/api/v1/forecasts/{fid}")).json()


# ---- illustrations (Task 6) -------------------------------------------------------------------------
TERMINAL = {"ready", "failed", "skipped"}


class FakeIllustrator:
    """Stands in for NVIDIA FLUX through ``Overrides``: the edit is a generated array (the input with its
    colours inverted, JPEG-encoded), never a stored image. ``error`` makes every call raise it after
    ``delay_s`` real seconds; ``calls`` counts calls and ``instructions`` keeps what was asked."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None
        self.delay_s = 0.0
        self.instructions: list[str] = []

    async def edit(self, image_jpeg: bytes, instruction: str, size: Any, seed: int, steps: int) -> bytes:
        import cv2
        import numpy as np

        self.calls += 1
        self.instructions.append(instruction)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        img = cv2.imdecode(np.frombuffer(image_jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape[:2] == (size[1], size[0]) and seed == 42 and steps == 4
        ok, buf = cv2.imencode(".jpg", 255 - img)
        assert ok
        return buf.tobytes()


class _JobsOnLoop:
    def __init__(self, world: Any) -> None:
        self._world = world

    async def run(self, forecast_id: str) -> None:
        jobs = self._world.gs.services.illustrations
        await on_gs_loop(self._world, lambda: jobs.run(forecast_id))


class FluxWorld:
    """``world_ready`` plus ``flux`` (the injected FakeIllustrator) and ``illustrations`` (``run`` reruns a
    forecast's illustration jobs on the Ground Station's loop). Everything else is the world's."""

    def __init__(self, world: Any, flux: FakeIllustrator) -> None:
        self._world, self.flux, self.illustrations = world, flux, _JobsOnLoop(world)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._world, name)


async def illustration_rows(world: Any, forecast_id: str) -> list[dict[str, Any]]:
    """The forecast's illustration rows, read from the repository (the listing route is Task 7's)."""
    rows = await world.rows("illustrations", forecast_id=forecast_id)
    return sorted(rows, key=lambda r: (r["scenario"], r["year"]))


async def wait_all_illustrations(world: Any, forecast_id: str, timeout: float = 60) -> list[dict[str, Any]]:
    """Wait until the forecast has its 4 illustration rows, none of them pending; return them."""
    deadline = time.monotonic() + timeout
    while True:
        rows = await illustration_rows(world, forecast_id)
        if len(rows) == 4 and all(r["status"] in TERMINAL for r in rows):
            return rows
        if time.monotonic() > deadline:
            raise AssertionError(f"illustrations of {forecast_id} not done: {[r['status'] for r in rows]}")
        await asyncio.sleep(0.05)
