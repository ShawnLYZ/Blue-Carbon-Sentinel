"""IllustrationJobs: the FLUX keyframe illustrations of a forecast (2030 and 2035 x without and with).

After the FutureRenderer has written a forecast's code-only futures (or failed to), ``on_rendered`` starts
``run`` in the background. ``run``:

1. creates the 4 ``illustrations`` rows with status ``pending`` (an existing row is reused, so ``run`` is
   also the rerun entry point);
2. runs them one after another (one forecast at a time) within a total budget of ``budget_s`` = 60 s of
   real time (the ManualClock of tests does not move, and this budget is about a real network call);
3. ends every row ``ready``, ``failed`` (with an error) or ``skipped`` (no zone changed beyond the
   threshold, no NVIDIA call) and publishes one ``illustration.ready`` for each.

Per row: the cache key is the SHA-256 of (capture hash, forecast ID, year, scenario), the capture hash
being the SHA-256 of the base raster's pixels. A ``ready`` row with the same key whose file still exists is
reused without a call. Otherwise the changed zones (``changed_zones``, 2026 to the year, central run) get
an instruction, the base raster resized to 1024 x 1024 goes to the illustrator (seed 42, 4 steps), and
the result is composited only inside the changed zones' masks, downscaled to 512 and stored at
``futures/{forecast_id}/illustrations/{scenario}-{year}.jpg`` (cloud-queued). Pixels outside the changed
zones are copied from the real capture.

When the futures render failed (e.g. no base media) every row ends ``failed`` with that reason. A row not
started before the budget runs out ends ``failed`` with "budget exhausted"; a call cut by the budget ends
``failed`` with a ``timeout`` error. Any other failure of a row ends that row ``failed``; a failure of
the run itself (loading, creating rows) ends every row this run has not ended ``failed`` with the reason
(creating the rows first if needed), so no row stays ``pending`` without an event (R22c).

Sticky failures (ruling R25): ``auth``, ``credits`` and a ``bad_response`` mentioning ``example_id`` (the
hosted API refusing our image) would repeat on the next call. For 30 minutes of real monotonic time in
this process, every further row that would call ends ``failed`` with the same reason and no call is made
(skipped and cached rows are unaffected). ``reset`` forgets it. Rows left ``pending`` by a previous process are marked ``failed`` at
construction.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

import cv2
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.core.aio import cancel_and_wait, to_thread_settled
from bcs_gs.core.ids import uuid7
from bcs_gs.futures.composite import SIZE, composite, zone_masks_1024
from bcs_gs.futures.heights import zone_changes_for
from bcs_gs.futures.illustrator import FLUX_MODEL, IllustratorError
from bcs_gs.futures.instruction import DEFAULT_THRESHOLD, build_instruction, changed_zones
from bcs_gs.futures.renderer import BUCKET, ILLUSTRATED_YEARS, SCENARIOS
from bcs_gs.futures.repaint import ZoneChange

log = logging.getLogger("bcs_gs.futures.illustrations")

BUDGET_S = 60.0
STICKY_S = 30 * 60  # ruling R25
SEED = 42
OUT_SIZE = 512
JPEG_QUALITY = 85
INPUT_JPEG_QUALITY = 90
CONTENT_TYPE = "image/jpeg"
ORDER = tuple((sc, y) for sc in SCENARIOS for y in ILLUSTRATED_YEARS)


def _sticky_clock() -> float:
    """The clock of the sticky-failure window (ruling R25): real monotonic seconds, in-process."""
    return time.monotonic()


def is_sticky(exc: IllustratorError) -> bool:
    """Failures the next call would repeat: auth, credits, or a 422 refusing our image (ruling R25)."""
    return exc.kind in ("auth", "credits") or (exc.kind == "bad_response" and "example_id" in exc.detail)


def illustration_key(forecast_id: str, scenario: str, year: int) -> str:
    return f"{forecast_id}/illustrations/{scenario}-{year}.jpg"


def illustration_url(illustration_id: str) -> str:
    return f"/api/v1/media/illustrations/{illustration_id}.jpg"


def cache_key(capture_hash: str, forecast_id: str, year: int, scenario: str) -> str:
    return hashlib.sha256(f"{capture_hash}|{forecast_id}|{year}|{scenario}".encode()).hexdigest()


class _Inputs:
    """The base raster and what every job of one forecast shares."""

    def __init__(self, rgb: np.ndarray, grid: Any, state: dict[str, Any]) -> None:
        self.rgb, self.grid, self.state = rgb, grid, state
        self.capture_hash = hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
        self.rgb1024 = cv2.resize(rgb, (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(
            ".jpg",
            cv2.cvtColor(self.rgb1024, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, INPUT_JPEG_QUALITY],
        )
        if not ok:
            raise RuntimeError("could not encode the illustration input")
        self.jpeg1024 = buf.tobytes()
        self.rgb512 = (
            rgb if rgb.shape[:2] == (OUT_SIZE, OUT_SIZE)
            else cv2.resize(rgb, (OUT_SIZE, OUT_SIZE), interpolation=cv2.INTER_AREA)
        )  # fmt: skip


class IllustrationJobs:
    def __init__(
        self, *, repo: Any, bus: Any, media: Any, clock: Any, futures: Any, illustrator: Any, ai: Any
    ) -> None:
        self._repo, self._bus, self._media, self._clock = repo, bus, media, clock
        self._futures = futures
        self.illustrator = illustrator
        self.model = (getattr(ai, "models", None) or {}).get("image", FLUX_MODEL)
        image = getattr(ai, "image", None) or {}
        w, h = image.get("illustration_size", [SIZE, SIZE])
        self.size = (int(w), int(h))
        self.steps = int(image.get("steps", 4))
        self.budget_s = BUDGET_S
        self._lock: asyncio.Lock | None = None
        self._sticky: tuple[str, float] | None = None  # (reason, until on _sticky_clock)
        self._ended: set[str] = set()  # row IDs ended by the current run
        self._bg: set[asyncio.Task[Any]] = set()
        self._fail_stale_pending()

    # ---- lifecycle ----------------------------------------------------------------------------------
    def _fail_stale_pending(self) -> None:
        rows = self._repo.query("SELECT * FROM illustrations WHERE status = 'pending'", table="illustrations")
        now = to_iso(self._clock.now())
        for r in rows:
            self._repo.upsert(
                "illustrations",
                {**r, "status": "failed", "error": "interrupted by a restart", "updated_at": now},
            )

    def on_rendered(self, forecast_id: str, error: str | None) -> None:
        """The FutureRenderer finished (``error`` None) or failed (``error`` = reason): run the jobs."""
        t = asyncio.create_task(self.run(forecast_id, futures_error=error), name="illustrations")
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    def reset(self) -> None:
        """Forget a sticky failure (test reset)."""
        self._sticky = None

    def sticky_reason(self) -> str | None:
        """The active sticky failure's reason, or None once its window has passed."""
        if self._sticky is not None and _sticky_clock() < self._sticky[1]:
            return self._sticky[0]
        self._sticky = None
        return None

    async def stop(self) -> None:
        await self.cancel()

    async def cancel(self) -> None:
        """Cancel the runs in progress and wait until they ended (shutdown, test reset; ruling R30). Their
        database writes and file writes run to completion first (``to_thread_settled``)."""
        await cancel_and_wait(list(self._bg))
        self._bg.clear()

    # ---- run ----------------------------------------------------------------------------------------
    async def run(self, forecast_id: str, *, futures_error: str | None = None) -> list[dict[str, Any]]:
        """Create (or reuse) the forecast's 4 rows and run them one after another; returns the final rows."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self._ended = set()
            try:
                return await self._run(forecast_id, futures_error)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("illustrations of forecast %s failed", forecast_id)
                return await self._fail_rest(forecast_id, f"{type(exc).__name__}: {exc}"[:300])

    async def _fail_rest(self, forecast_id: str, reason: str) -> list[dict[str, Any]]:
        """After an unexpected failure of the run: every row of the forecast this run has not ended ends
        ``failed`` with ``reason`` (rows are created first when missing), one event each. If even that
        fails, four failed placeholder events are published, so nothing waits for ever (R22c)."""
        try:
            rows = await to_thread_settled(self._rows_or_new, forecast_id)
            return [await self._end(r, "failed", error=reason) for r in rows if r["id"] not in self._ended]
        except Exception:
            log.exception("failing the illustrations of forecast %s failed", forecast_id)
            for scenario, year in ORDER:
                self._bus.publish(
                    "illustration.ready",
                    {
                        "id": uuid7(), "forecast_id": forecast_id, "year": year, "scenario": scenario,
                        "status": "failed", "url": None, "provider": self.illustrator.name,
                        "model": self.model, "error": reason,
                    },
                )  # fmt: skip
            return []

    def _rows_or_new(self, forecast_id: str) -> list[dict[str, Any]]:
        existing = {
            (r["scenario"], int(r["year"])): r
            for r in self._repo.query(
                "SELECT * FROM illustrations WHERE forecast_id = ?", (forecast_id,), table="illustrations"
            )
        }
        now = to_iso(self._clock.now())
        rows = []
        for scenario, year in ORDER:
            row = existing.get((scenario, year))
            if row is None:
                key = cache_key("none", forecast_id, year, scenario)
                row = self._new_row(forecast_id, scenario, year, key, now)
                self._repo.insert("illustrations", row)
            rows.append(row)
        return rows

    def _new_row(self, forecast_id: str, scenario: str, year: int, key: str, now: str) -> dict[str, Any]:
        return {
            "id": uuid7(), "forecast_id": forecast_id, "year": year, "scenario": scenario,
            "media_key": None, "provider": self.illustrator.name, "model": self.model,
            "instruction": "", "seed": SEED, "status": "pending", "cache_key": key, "error": None,
            "created_at": now, "updated_at": now,
        }  # fmt: skip

    async def _run(self, forecast_id: str, futures_error: str | None) -> list[dict[str, Any]]:
        forecast, inputs, error = await to_thread_settled(self._load, forecast_id, futures_error)
        rows = await to_thread_settled(self._ensure_rows, forecast_id, inputs)
        if not rows:
            return []
        t0 = time.monotonic()
        out = []
        for row in rows:
            out.append(await self._one(row, forecast, inputs, error, t0))
        return out

    def _load(self, forecast_id: str, futures_error: str | None) -> tuple[Any, _Inputs | None, str | None]:
        forecast = self._repo.get("forecasts", {"id": forecast_id})
        if forecast is None:
            return None, None, "the forecast does not exist"
        if forecast["status"] != "ready":
            return forecast, None, futures_error or f"the forecast is {forecast['status']}"
        if futures_error is not None:
            return forecast, None, futures_error
        found = self._futures.read_inputs(forecast["base_capture_id"])
        if found is None:
            return forecast, None, "the base capture has no stored raster, class map or height map"
        rgb = found[0]
        grid = self._futures.grid(rgb.shape[0])
        return forecast, _Inputs(rgb, grid, self._futures.base_state(forecast, grid.ids)), None

    def _ensure_rows(self, forecast_id: str, inputs: _Inputs | None) -> list[dict[str, Any]]:
        if self._repo.get("forecasts", {"id": forecast_id}) is None:
            return []
        capture_hash = inputs.capture_hash if inputs is not None else "no-capture"
        now = to_iso(self._clock.now())
        existing = {
            (r["scenario"], int(r["year"])): r
            for r in self._repo.query(
                "SELECT * FROM illustrations WHERE forecast_id = ? ORDER BY created_at, id",
                (forecast_id,), table="illustrations",
            )
        }  # fmt: skip
        rows = []
        with self._repo.transaction():
            for scenario, year in ORDER:
                key = cache_key(capture_hash, forecast_id, year, scenario)
                row = existing.get((scenario, year))
                if row is None:
                    row = self._new_row(forecast_id, scenario, year, key, now)
                    self._repo.insert("illustrations", row)
                elif inputs is not None and row["cache_key"] != key:
                    row = {**row, "cache_key": key, "updated_at": now}
                    self._repo.upsert("illustrations", row)
                rows.append(row)
        return rows

    def _cached(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """A ready row with this row's cache key whose file exists (this row itself included)."""
        for r in self._repo.query(
            "SELECT * FROM illustrations WHERE cache_key = ? AND status = 'ready' ORDER BY updated_at DESC",
            (row["cache_key"],), table="illustrations",
        ):  # fmt: skip
            if r["media_key"] and self._media.path(BUCKET, r["media_key"]).is_file():
                return r
        return None

    async def _one(
        self, row: dict[str, Any], forecast: Any, inputs: _Inputs | None, error: str | None, t0: float
    ) -> dict[str, Any]:
        instruction: str | None = None
        try:
            cached = await to_thread_settled(self._cached, row)
            if cached is not None:
                return await self._end(
                    row, "ready", media_key=cached["media_key"], instruction=cached["instruction"],
                    provider=cached["provider"], model=cached["model"],
                )  # fmt: skip
            if error is not None or inputs is None:
                return await self._end(row, "failed", error=error or "no base media")
            scenario, year = row["scenario"], int(row["year"])
            changes = zone_changes_for(forecast, scenario, year, inputs.state)
            changed = changed_zones(forecast, scenario, year, DEFAULT_THRESHOLD, base_state=inputs.state)
            if not changed:
                return await self._end(row, "skipped", error="no zone changed enough to illustrate")
            instruction = build_instruction({z: changes.get(z, ZoneChange()) for z in changed}, scenario, year)
            sticky = self.sticky_reason()
            if sticky is not None:  # ruling R25: the same failure again, without a call
                return await self._end(row, "failed", error=sticky, instruction=instruction)
            remaining = self.budget_s - (time.monotonic() - t0)
            if remaining <= 0:
                return await self._end(row, "failed", error="budget exhausted", instruction=instruction)
            data = await asyncio.wait_for(
                self.illustrator.edit(inputs.jpeg1024, instruction, self.size, SEED, self.steps), remaining
            )
            media_key = await to_thread_settled(self._store, row, data, inputs, changed)
        except TimeoutError:
            msg = f"timeout: the {self.budget_s:g} s illustration budget ran out during the call"
            return await self._end(row, "failed", error=msg, instruction=instruction)
        except IllustratorError as exc:
            reason = str(exc)[:300]
            if is_sticky(exc):
                self._sticky = (reason, _sticky_clock() + STICKY_S)
            return await self._end(row, "failed", error=reason, instruction=instruction)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("illustration %s failed", row["id"])
            msg = f"{type(exc).__name__}: {exc}"[:300]
            return await self._end(row, "failed", error=msg, instruction=instruction)
        return await self._end(row, "ready", media_key=media_key, instruction=instruction)

    def _store(self, row: dict[str, Any], data: bytes, inputs: _Inputs, changed: list[str]) -> str:
        bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise IllustratorError("bad_response", "the image does not decode")
        ill = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if ill.shape[:2] != (SIZE, SIZE):
            ill = cv2.resize(ill, (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
        out = composite(inputs.rgb1024, ill, zone_masks_1024(inputs.grid, changed))
        out = cv2.resize(out, (OUT_SIZE, OUT_SIZE), interpolation=cv2.INTER_AREA)
        union = np.zeros((OUT_SIZE, OUT_SIZE), bool)
        for m in zone_masks_1024(inputs.grid, changed, size=OUT_SIZE):
            union |= m
        out[~union] = inputs.rgb512[~union]  # outside the changed zones: the real capture, exactly
        ok, buf = cv2.imencode(
            ".jpg", cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if not ok:
            raise RuntimeError("could not encode the illustration")
        key = illustration_key(row["forecast_id"], row["scenario"], int(row["year"]))
        self._media.put(BUCKET, key, buf.tobytes(), CONTENT_TYPE, cloud=True)
        return key

    async def _end(
        self,
        row: dict[str, Any],
        status: str,
        *,
        media_key: str | None = None,
        error: str | None = None,
        instruction: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        new = {
            **row, "status": status, "media_key": media_key if status == "ready" else None,
            "error": None if status == "ready" else error,
            "instruction": row["instruction"] if instruction is None else instruction,
            "provider": provider or self.illustrator.name, "model": model or self.model,
            "updated_at": to_iso(self._clock.now()),
        }  # fmt: skip
        await to_thread_settled(self._repo.upsert, "illustrations", new)
        self._ended.add(new["id"])
        self._bus.publish(
            "illustration.ready",
            {
                "id": new["id"], "forecast_id": new["forecast_id"], "year": int(new["year"]),
                "scenario": new["scenario"], "status": status,
                "url": illustration_url(new["id"]) if status == "ready" else None,
                "provider": new["provider"], "model": new["model"], "error": new["error"],
            },
        )  # fmt: skip
        return new
