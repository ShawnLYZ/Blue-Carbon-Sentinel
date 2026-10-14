"""TreeService: tree points from a capture's raster and class map, stored in site coordinates (F4).

The TreeLocator answers in normalised 0-1000 (y, x) on the raster. Each point becomes raster pixels
(``u_px``, ``v_px``) and site metres (``e_m``, ``s_m``) through the SiteRegistry, and gets its zone.
Runs on the baseline, on plan application (M5 calls ``locate``) and on request. Emits ``trees.updated``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import cv2
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.ai.roles._common import RoleConfig
from bcs_gs.ai.roles.base import Priority
from bcs_gs.ai.roles.tree_locator import TreeInput, TreeLocator
from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.capture.artefacts import BUCKET, CLASS_PALETTE, decode_indexed_png
from bcs_gs.core.aio import to_thread_settled
from bcs_gs.core.ids import uuid7
from bcs_gs.history.service import source_chip

log = logging.getLogger("bcs_gs.trees")


class TreeService:
    def __init__(
        self, *, repo: Any, bus: Any, clock: Any, settings: Any, site: Any, captures: Any, media: Any,
        gateway: Any,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._clock, self._site = repo, bus, clock, site
        self._captures, self._media, self._gateway = captures, media, gateway
        self._role = TreeLocator(RoleConfig.from_settings(settings))
        self._sub: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._bg: set[asyncio.Task[Any]] = set()

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        self._sub = self._bus.subscribe(1000)
        self._listener = asyncio.create_task(self._listen(), name="trees-listen")

    async def stop(self) -> None:
        if self._sub is not None:
            self._sub.close()
        tasks = [t for t in (self._listener, *self._bg) if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._bg.clear()

    async def cancel_work(self) -> None:
        """Cancel the work in flight and wait until it ended, then listen again (test reset; ruling R30)."""
        await self.stop()
        self.start()

    def reset(self) -> None:
        """Nothing is held in memory; the table is cleared by the test reset."""

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                if ev.type == "baseline.updated":
                    self._spawn(self._on_baseline(ev.data.get("capture_id")), "trees-baseline")
            if not sub.overflowed:
                return
            self._sub = self._bus.subscribe(1000)

    def _spawn(self, coro: Any, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def _on_baseline(self, capture_id: str | None) -> None:
        try:
            await self._run(capture_id, Priority.BACKGROUND)
        except ApiError:
            pass  # a baseline without a class map (seeded) has nothing to locate
        except Exception:
            log.exception("tree location on the baseline failed")

    # ---- locate -------------------------------------------------------------------------------------
    async def locate(self, capture_id: str | None = None, priority: Priority = Priority.OPERATOR) -> str:
        """Locate trees in the capture (default: the latest evidence-grade capture with a class map) in
        the background; returns a request ID. 409 when no class map exists."""
        loaded = await to_thread_settled(self._load, capture_id)
        request_id = uuid7()
        self._spawn(self._store_from(loaded, priority), "trees-locate")
        return request_id

    async def _run(self, capture_id: str | None, priority: Priority) -> None:
        await self._store_from(await to_thread_settled(self._load, capture_id), priority)

    def _load(self, capture_id: str | None) -> tuple[str, np.ndarray, bytes]:
        """(capture ID, class codes, raster JPEG). Blocking. A capture without a stored raster is
        given a JPEG rendered from its class map."""
        if capture_id is None:
            found = self._captures.latest_class_map()
            if found is None:
                raise ApiError("conflict", 409, "No capture with a class map yet.")
            capture_id, classes = found
        else:
            row = self._repo.get("captures", {"id": capture_id})
            if row is None:
                raise ApiError("not_found", 404, f"No capture {capture_id}.")
            key = (row.get("media") or {}).get("classes")
            path = self._media.path(BUCKET, key) if key else None
            if path is None or not path.exists():
                raise ApiError("conflict", 409, f"Capture {capture_id} has no class map.")
            classes = decode_indexed_png(path.read_bytes())
        return capture_id, classes, self._raster_jpeg(capture_id, classes)

    def _raster_jpeg(self, capture_id: str, classes: np.ndarray) -> bytes:
        row = self._repo.get("captures", {"id": capture_id}) or {}
        key = (row.get("media") or {}).get("image")
        if key:
            path = self._media.path(BUCKET, key)
            if path.exists():
                return path.read_bytes()
        palette = np.array(CLASS_PALETTE, np.uint8)[:, ::-1]  # RGB -> BGR for OpenCV
        ok, buf = cv2.imencode(".jpg", palette[np.clip(classes, 0, len(palette) - 1)])
        if not ok:
            raise RuntimeError("could not encode the class-map raster")
        return buf.tobytes()

    async def _store_from(self, loaded: tuple[str, np.ndarray, bytes], priority: Priority) -> None:
        capture_id, classes, jpeg = loaded
        try:
            result = await self._gateway.call(
                self._role, TreeInput(raster_jpeg=jpeg, classes=classes), priority
            )
            payload = await to_thread_settled(self._store, capture_id, result)
            self._bus.publish("trees.updated", payload.model_dump(mode="json"))
        except Exception:
            log.exception("tree location failed")

    def _convert(self, out: Any) -> list[m.TreePoint]:
        size = self._site.site().size_m
        raster_px = self._site.metres_to_raster(float(size), 0.0)[0]
        points: list[m.TreePoint] = []
        for p in out.points:
            u, v = p.x / 1000.0 * raster_px, p.y / 1000.0 * raster_px
            e, s = self._site.raster_to_metres(u, v)
            e, s = min(max(e, 0.0), float(size)), min(max(s, 0.0), float(size))
            points.append(
                m.TreePoint(e_m=e, s_m=s, u_px=u, v_px=v, zone_id=self._site.zone_at(e, s), label=p.label)
            )
        return points

    def _store(self, capture_id: str, result: Any) -> m.TreePoints:
        points = self._convert(result.output)
        created = to_iso(self._clock.now())
        chip = result.source
        self._repo.insert(
            "tree_points",
            {
                "id": uuid7(), "capture_id": capture_id, "created_at": created,
                "points": [p.model_dump() for p in points], "tier": chip.tier, "model": chip.model,
                "ai_call_id": chip.ai_call_id,
            },
        )  # fmt: skip
        return m.TreePoints(capture_id=capture_id, created_at=created, source=chip, points=points)

    # ---- read ---------------------------------------------------------------------------------------
    def latest(self) -> m.TreePoints | None:
        """The newest stored tree points (blocking)."""
        rows = self._repo.query(
            "SELECT * FROM tree_points ORDER BY created_at DESC, id DESC LIMIT 1", table="tree_points"
        )
        if not rows:
            return None
        r = rows[0]
        return m.TreePoints(
            capture_id=r["capture_id"], created_at=r["created_at"],
            source=source_chip(self._repo, r["ai_call_id"], r["tier"], r["model"]),
            points=[m.TreePoint.model_validate(p) for p in r["points"]],
        )  # fmt: skip
