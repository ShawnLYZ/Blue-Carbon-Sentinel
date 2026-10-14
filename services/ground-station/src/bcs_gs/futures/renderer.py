"""FutureRenderer: after every ready forecast, writes the code-only future textures and heights.

For each year (2026-2035, 2026 being the real capture with zero change, ruling R21) and each scenario it
writes ``futures/{forecast_id}/{scenario}/{year}/texture.jpg`` and ``height.png`` (addendum H5) to the
MediaStore, queued for the cloud (H6). The CPU work runs in a worker thread, off the event loop.

The inputs are the base capture's ``image.jpg``, ``classes.png`` and ``height.png`` (test-mode seeded
captures carry synthetic ones, ruling R22a). Without them nothing is written and no image is substituted.
Every render ends by handing over to the illustrations: ``on_rendered(forecast_id, error)`` (the
IllustrationJobs, Task 6) with ``error`` None after a successful render, or the reason when the base media
is missing or the render fails (ruling R22c), so nothing waits for ever. Without ``on_rendered`` it
publishes four ``illustration.ready`` placeholders itself (2030, 2035 x without, with): ``skipped``, or
``failed`` with the reason.

Catch-up (ruling R22b): on start the latest 3 ready forecasts that lack futures are rendered, and
``ensure`` (called on a futures media 404) starts one background render of a ready forecast whose files
are missing. A forecast is never rendered twice at once, nor retried by ``ensure`` after a failed render.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np

from bcs_gs.capture.artefacts import BUCKET as CAPTURE_BUCKET
from bcs_gs.capture.artefacts import decode_indexed_png
from bcs_gs.core.aio import cancel_and_wait, to_thread_settled
from bcs_gs.core.ids import uuid7
from bcs_gs.futures.heights import future_heights, zone_changes_for
from bcs_gs.futures.repaint import ZoneGrid, repaint
from bcs_gs.vegetation.metrics import zone_index_image

log = logging.getLogger("bcs_gs.futures")

BUCKET = "futures"
SCENARIOS = ("without", "with")
ILLUSTRATED_YEARS = (2030, 2035)
JPEG_QUALITY = 85
CATCH_UP_LATEST = 3
CONTENT_TYPES = {"texture": "image/jpeg", "height": "image/png"}


def future_key(forecast_id: str, scenario: str, year: int, kind: str) -> str:
    """Storage key (H5) for ``kind`` texture or height."""
    return f"{forecast_id}/{scenario}/{year}/{'texture.jpg' if kind == 'texture' else 'height.png'}"


class NoBaseMedia(Exception):
    """The forecast cannot be rendered: its base capture has no stored raster, class map or height map."""


class _Abandoned(Exception):
    """The render was cancelled (``cancel``): its thread stops before writing another file."""


class FutureRenderer:
    def __init__(self, *, repo: Any, bus: Any, media: Any, site: Any, fusion: Any) -> None:
        self._repo, self._bus, self._media, self._site, self._fusion = repo, bus, media, site, fusion
        self._sub: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._bg: set[asyncio.Task[Any]] = set()
        self._inflight: set[str] = set()
        self._failed: set[str] = set()  # not retried by ``ensure`` in this process
        self._gen = 0  # bumped by ``cancel``: a render thread of an older generation writes nothing more
        self.on_rendered: Callable[[str, str | None], None] | None = None  # IllustrationJobs.on_rendered

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        self._sub = self._bus.subscribe(1000)
        self._listener = asyncio.create_task(self._listen(), name="futures-listen")
        self._spawn(self._catch_up(), "futures-catch-up")

    async def stop(self) -> None:
        if self._sub is not None:
            self._sub.close()
        self._gen += 1
        await cancel_and_wait([t for t in (self._listener, *self._bg) if t is not None])
        self._bg.clear()

    async def cancel(self) -> None:
        """Cancel the renders in progress (the listener stays) and wait until their threads stopped, so no
        futures file is written afterwards (test reset; ruling R30)."""
        self._gen += 1
        await cancel_and_wait(list(self._bg))
        self._bg.clear()
        self._inflight.clear()

    def reset(self) -> None:
        """The media files are removed by the test reset; forget what was tried. A render thread started
        since ``cancel`` writes no further file."""
        self._gen += 1
        self._failed.clear()

    def _spawn(self, coro: Any, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                if ev.type == "forecast.ready" and ev.data.get("status") == "ready":
                    self._spawn(self.render(ev.data["forecast_id"]), "futures-render")
            if not sub.overflowed:
                return
            self._sub = self._bus.subscribe(1000)

    # ---- catch-up and lazy render (ruling R22b) -----------------------------------------------------
    def _incomplete(self, forecast_id: str, summary: dict[str, Any] | None) -> bool:
        years = [int(y) for y in (summary or {}).get("years", [])]
        return not all(
            self._media.path(BUCKET, future_key(forecast_id, sc, y, "texture")).is_file()
            for sc in SCENARIOS
            for y in years
        )

    def _missing(self) -> list[str]:
        rows = self._repo.query(
            "SELECT id, summary FROM forecasts WHERE status = 'ready' "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (CATCH_UP_LATEST,), table="forecasts",
        )  # fmt: skip
        return [r["id"] for r in rows if self._incomplete(r["id"], r["summary"])]

    async def _catch_up(self) -> None:
        try:
            for fid in await asyncio.to_thread(self._missing):
                await self.render(fid)
        except Exception:
            log.exception("futures catch-up failed")

    async def ensure(self, forecast_id: str) -> bool:
        """A futures media 404: start one background render when the forecast is ready and its files are
        missing. Returns True when a render was started."""
        if forecast_id in self._inflight or forecast_id in self._failed:
            return False

        def needed() -> bool:
            row = self._repo.get("forecasts", {"id": forecast_id})
            return (
                row is not None and row["status"] == "ready" and self._incomplete(forecast_id, row["summary"])
            )

        if not await asyncio.to_thread(needed):
            return False
        self._inflight.add(forecast_id)  # claimed now: a second 404 right away starts nothing
        self._spawn(self.render(forecast_id, claimed=True), "futures-lazy-render")
        return True

    # ---- render -------------------------------------------------------------------------------------
    async def render(self, forecast_id: str, *, claimed: bool = False) -> bool:
        """Write every texture and height of the forecast; True when files were written. Always ends with
        the four illustration placeholders (see the module doc). Not run twice at once for a forecast."""
        if forecast_id in self._inflight and not claimed:
            return False
        self._inflight.add(forecast_id)
        try:
            await to_thread_settled(self._render_sync, forecast_id, self._gen)
        except (asyncio.CancelledError, _Abandoned):
            raise
        except NoBaseMedia as exc:
            self._failed.add(forecast_id)
            self._finished(forecast_id, str(exc))
            return False
        except Exception as exc:
            self._failed.add(forecast_id)
            log.exception("rendering the futures of forecast %s failed", forecast_id)
            self._finished(forecast_id, f"{type(exc).__name__}: {exc}"[:300])
            return False
        finally:
            self._inflight.discard(forecast_id)
        self._failed.discard(forecast_id)
        self._finished(forecast_id, None)
        return True

    def _finished(self, forecast_id: str, error: str | None) -> None:
        if self.on_rendered is not None:
            self.on_rendered(forecast_id, error)
        elif error is None:
            self._placeholders(forecast_id, "skipped", "illustrations are not generated")
        else:
            self._placeholders(forecast_id, "failed", error)

    def _placeholders(self, forecast_id: str, status: str, error: str) -> None:
        for scenario in SCENARIOS:
            for year in ILLUSTRATED_YEARS:
                self._bus.publish(
                    "illustration.ready",
                    {
                        "id": uuid7(), "forecast_id": forecast_id, "year": year, "scenario": scenario,
                        "status": status, "url": None, "provider": "none", "model": "none", "error": error,
                    },
                )  # fmt: skip

    def read_inputs(self, base_capture_id: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        row = self._repo.get("captures", {"id": base_capture_id})
        media = (row or {}).get("media") or {}
        if not all(media.get(k) for k in ("image", "classes", "height")):
            return None
        paths = {k: self._media.path(CAPTURE_BUCKET, media[k]) for k in ("image", "classes", "height")}
        if not all(p.is_file() for p in paths.values()):
            return None
        bgr = cv2.imread(str(paths["image"]), cv2.IMREAD_COLOR)
        height = cv2.imread(str(paths["height"]), cv2.IMREAD_UNCHANGED)
        if bgr is None or height is None:
            return None
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        classes = decode_indexed_png(paths["classes"].read_bytes())
        if classes.shape != rgb.shape[:2] or height.shape != classes.shape:
            return None
        return rgb, classes, height

    def grid(self, size: int) -> ZoneGrid:
        labels, ids = zone_index_image(self._site, size)
        return ZoneGrid(labels, ids, float(self._site.site().size_m) / size)

    @staticmethod
    def base_state(row: dict[str, Any], zone_ids: Any) -> dict[str, Any]:
        """Each zone's starting stressors as stored with the forecast (``summary.base_stressors``), never
        the live assessments, so a forecast's renders are reproducible. A row without them has none."""
        stored = (row.get("summary") or {}).get("base_stressors") or {}
        return {z: SimpleNamespace(stressors=dict(stored.get(z) or {})) for z in zone_ids}

    def _render_sync(self, forecast_id: str, gen: int | None = None) -> None:
        row = self._repo.get("forecasts", {"id": forecast_id})
        if row is None or row["status"] != "ready":
            raise NoBaseMedia(f"forecast {forecast_id} is not ready")
        inputs = self.read_inputs(row["base_capture_id"])
        if inputs is None:
            raise NoBaseMedia("the base capture has no stored raster, class map or height map")
        rgb, classes, height = inputs
        grid = self.grid(rgb.shape[0])
        state = self.base_state(row, grid.ids)
        years = sorted({int(y) for y in (row["summary"] or {}).get("years", [])})
        for scenario in SCENARIOS:
            for year in years:
                changes = zone_changes_for(row, scenario, year, state)
                out = repaint(rgb, classes, changes, grid=grid)
                ok, buf = cv2.imencode(
                    ".jpg", cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                if not ok:
                    raise RuntimeError("could not encode a future texture")
                self._check(gen)
                self._put(forecast_id, scenario, year, "texture", buf.tobytes())
                ok, buf = cv2.imencode(".png", future_heights(height, classes, changes, grid=grid))
                if not ok:
                    raise RuntimeError("could not encode a future height map")
                self._check(gen)
                self._put(forecast_id, scenario, year, "height", buf.tobytes())

    def _check(self, gen: int | None) -> None:
        if gen is not None and gen != self._gen:
            raise _Abandoned("the render was cancelled")

    def _put(self, forecast_id: str, scenario: str, year: int, kind: str, data: bytes) -> None:
        self._media.put(
            BUCKET, future_key(forecast_id, scenario, year, kind), data, CONTENT_TYPES[kind], cloud=True
        )
