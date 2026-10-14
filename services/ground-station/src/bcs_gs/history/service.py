"""HistoryService (spec section 18): the 2016-2025 stand-in series per zone.

Generated once per site after the first baseline (at BACKGROUND priority) and again on request. The series
is always labelled as AI-generated; real points are the canopy % per zone per capture year taken from the
evidence-grade captures. Emits ``history.updated {generation_id}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.ai.roles._common import RoleConfig
from bcs_gs.ai.roles.base import Priority
from bcs_gs.ai.roles.history_synthesizer import HistoryInput, HistorySynthesizer
from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.core.ids import uuid7

log = logging.getLogger("bcs_gs.history")

LABEL = "AI-generated baseline — stand-in for the Sentinel-2 archive"


def source_chip(
    repo: Any, ai_call_id: str | None, tier: str = "rules", model: str | None = None
) -> m.SourceChip:
    """The chip of a stored AI result, read back from its ``ai_calls`` row (tier, model, cache hit)."""
    row = repo.get("ai_calls", {"id": ai_call_id}) if ai_call_id else None
    if row is None:
        return m.SourceChip(tier=tier, model=model, cached=False, ai_call_id=ai_call_id)
    return m.SourceChip(
        tier=row["tier"], model=row["model"], cached=bool(row["cache_hit"]), ai_call_id=ai_call_id
    )


def _seed(baseline_id: str, nonce: str | None = None) -> int:
    """The synthesis seed: from the baseline (first generation), plus the request's nonce on regenerate."""
    text = baseline_id if nonce is None else f"{baseline_id}:{nonce}"
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


class HistoryService:
    def __init__(
        self, *, repo: Any, bus: Any, clock: Any, settings: Any, site: Any, captures: Any, gateway: Any
    ) -> None:
        self._repo, self._bus, self._clock, self._site = repo, bus, clock, site
        self._captures, self._gateway = captures, gateway
        self._role = HistorySynthesizer(RoleConfig.from_settings(settings))
        self._sub: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._bg: set[asyncio.Task[Any]] = set()
        self._busy = False

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        self._sub = self._bus.subscribe(1000)
        self._listener = asyncio.create_task(self._listen(), name="history-listen")

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

    def reset(self) -> None:
        self._busy = False

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                if ev.type == "baseline.updated":
                    self._spawn(self.ensure_generated(), "history-ensure")
            if not sub.overflowed:
                return
            self._sub = self._bus.subscribe(1000)

    def _spawn(self, coro: Any, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    # ---- generation ---------------------------------------------------------------------------------
    async def ensure_generated(self) -> str | None:
        """Generate once, after the first baseline: a no-op when a generation exists or one is running.
        Returns the new generation ID, or None when nothing was generated."""
        if self._busy:
            return None
        exists = await asyncio.to_thread(
            lambda: bool(self._repo.query("SELECT id FROM history_series LIMIT 1", table="history_series"))
        )
        if exists:
            return None
        return await self._generate(Priority.BACKGROUND)

    async def regenerate(self) -> str:
        """Operator request: a new generation in the background; returns a request ID."""
        if await asyncio.to_thread(self._captures.baseline) is None:
            raise ApiError("conflict", 409, "History is generated from the baseline; there is none yet.")
        request_id = uuid7()
        # A fresh seed per request: new inputs, so the operator gets a new series rather than a repeat.
        self._spawn(self._generate(Priority.OPERATOR, nonce=request_id), "history-regenerate")
        return request_id

    async def _generate(self, priority: Priority, nonce: str | None = None) -> str | None:
        if self._busy:
            return None
        self._busy = True
        try:
            baseline = await asyncio.to_thread(self._captures.baseline)
            if baseline is None:
                return None
            inp = HistoryInput(
                zones={
                    z.zone_id: {"canopy_pct": z.canopy_pct, "vari_mean": z.vari_mean}
                    for z in baseline.zone_metrics
                },
                site_context=self._context(),
                seed=_seed(baseline.id, nonce),
            )
            result = await self._gateway.call(self._role, inp, priority)
            generation_id = uuid7()
            await asyncio.to_thread(self._store, generation_id, result)
            self._bus.publish("history.updated", {"generation_id": generation_id})
            return generation_id
        except Exception:
            log.exception("history synthesis failed")
            return None
        finally:
            self._busy = False

    def _context(self) -> str:
        s = self._site.site()
        return f"{s.name}, {s.region}: a {s.size_m:g} m square mangrove restoration site."

    def _store(self, generation_id: str, result: Any) -> None:
        now = to_iso(self._clock.now())
        site_id = self._site.site().id
        with self._repo.transaction():
            for zone_id, points in result.output.series.items():
                for p in points:
                    self._repo.insert(
                        "history_series",
                        {
                            "id": uuid7(), "generation_id": generation_id, "site_id": site_id,
                            "zone_id": zone_id, "year": p.year,
                            "metrics": {"canopy_pct": p.canopy_pct, "vari_equiv": p.vari_equiv, "note": p.note},
                            "ai_call_id": result.source.ai_call_id, "label": LABEL, "created_at": now,
                        },
                    )  # fmt: skip

    # ---- read ---------------------------------------------------------------------------------------
    def latest(self) -> m.History:
        """The newest generation plus the real capture points (blocking)."""
        real = self._real()
        head = self._repo.query(
            "SELECT * FROM history_series ORDER BY created_at DESC, id DESC LIMIT 1", table="history_series"
        )
        if not head:
            return m.History(label=LABEL, series={}, real=real)
        gen = head[0]["generation_id"]
        rows = self._repo.query(
            "SELECT * FROM history_series WHERE generation_id = ? ORDER BY zone_id, year",
            (gen,), table="history_series",
        )  # fmt: skip
        series: dict[str, list[m.HistoryYear]] = {}
        for r in rows:
            series.setdefault(r["zone_id"], []).append(
                m.HistoryYear(
                    year=r["year"],
                    canopy_pct=r["metrics"]["canopy_pct"],
                    vari_equiv=r["metrics"]["vari_equiv"],
                    note=r["metrics"].get("note"),
                )
            )
        return m.History(
            generation_id=gen, label=head[0]["label"] or LABEL,
            source=source_chip(self._repo, head[0]["ai_call_id"]), series=series, real=real,
        )  # fmt: skip

    def _real(self) -> list[m.HistoryReal]:
        """Canopy % per zone for the newest evidence-grade capture of each calendar year."""
        years = self._repo.query(
            "SELECT DISTINCT substr(taken_at, 1, 4) AS y FROM captures WHERE evidence_grade = 1 ORDER BY y"
        )
        out: list[m.HistoryReal] = []
        for y in years:
            cap = self._repo.query(
                "SELECT * FROM captures WHERE evidence_grade = 1 AND substr(taken_at, 1, 4) = ? "
                "ORDER BY taken_at DESC, id DESC LIMIT 1", (y["y"],), table="captures",
            )  # fmt: skip
            if not cap:
                continue
            for z in self._repo.query(
                "SELECT * FROM zone_metrics WHERE capture_id = ? ORDER BY zone_id", (cap[0]["id"],),
                table="zone_metrics",
            ):  # fmt: skip
                out.append(
                    m.HistoryReal(
                        t=cap[0]["taken_at"],
                        zone_id=z["zone_id"],
                        canopy_pct=z["canopy_pct"],
                        vari_mean=z["vari_mean"],
                    )
                )
        return out
