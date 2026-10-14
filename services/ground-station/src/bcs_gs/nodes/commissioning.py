"""Automatic commissioning (spec §12; addendum H2, H7, I3, J2): place the static Sentinel Nodes from
the latest evidence-grade capture's class map, or spread them out when the map shows too little.

Pure planning (``candidates``, ``plan_layout``) works on the 512 x 512 site raster of class codes
(F5: 1 canopy, 2 water, 3 mud, 4 other). Distances are in site metres (one pixel = 500/512 m).
``Commissioning`` applies a layout to the NodeRegistry and stores the run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.core.clock import Clock, RealClock
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.nodes.coverage import (
    CANOPY_CODE,
    DEFAULT_GRID,
    MUD_CODE,
    RADIUS_M,
    SOIL,
    TIDE,
    WATER,
    WATER_CODE,
    ZoneGrid,
    by_zone,
    coverage,
)
from bcs_gs.nodes.registry import PREFIXES

log = logging.getLogger("bcs_gs.commissioning")

DEFAULT_COUNTS = {"tg": 1, "wq": 4, "sp": 3}
SPACING_M = 80.0  # same-type spacing, mandatory
WQ_ERODE_PX = 2  # WQ: the water mask eroded by 2 px
SP_CANOPY_PX = 10  # SP: mud within 10 px of canopy
SUBSAMPLE_PX = 8  # one candidate per 8 x 8 block
MIN_WATER_MUD = 0.02  # below 2% of the site: low-confidence fallback
ANALYSIS_CELLS = 20  # 20 x 20 analysis cells of 25 m (F4)
NO_CAPTURE = "no capture available"
NO_WATER_MUD = "no water/mud visible"
TYPE_ORDER = (TIDE, WATER, SOIL)  # greedy order TG -> WQ -> SP
_KEYS = {TIDE: "tg", WATER: "wq", SOIL: "sp"}

Px = tuple[int, int]


@dataclass(frozen=True)
class Candidates:
    wq: list[Px]
    sp: list[Px]
    tg: list[Px]


@dataclass(frozen=True)
class NodePos:
    node_id: str
    node_type: str
    e_m: float
    s_m: float
    u_px: float
    v_px: float
    zone_id: str


@dataclass(frozen=True)
class Layout:
    positions: list[NodePos]
    method: str  # class_map | fallback_spread
    confidence: str  # high | low
    reasons: list[str] = field(default_factory=list)


# ---- candidates ------------------------------------------------------------------------------------
def _subsample(mask: np.ndarray) -> list[Px]:
    """One pixel per 8 x 8 block: the one nearest the block centre (raster order on ties)."""
    vs, us = np.nonzero(mask)
    if not len(us):
        return []
    c = (SUBSAMPLE_PX - 1) / 2
    d = (us % SUBSAMPLE_PX - c) ** 2 + (vs % SUBSAMPLE_PX - c) ** 2
    block = (vs // SUBSAMPLE_PX) * (mask.shape[1] // SUBSAMPLE_PX + 1) + us // SUBSAMPLE_PX
    order = np.lexsort((us, vs, d, block))  # by block, then distance, then raster order
    first = np.ones(len(order), bool)
    first[1:] = block[order][1:] != block[order][:-1]
    keep = order[first]
    keep = keep[np.lexsort((us[keep], vs[keep]))]  # raster order
    return [(int(us[i]), int(vs[i])) for i in keep]


def candidates(classes: np.ndarray) -> Candidates:
    """WQ: water eroded by 2 px; SP: mud within 10 px of canopy; TG: the shoreline of the largest
    water body. Each subsampled to one pixel per 8 px block, as (u, v) pixels."""
    water = (classes == WATER_CODE).astype(np.uint8)
    k = 2 * WQ_ERODE_PX + 1
    wq = cv2.erode(water, np.ones((k, k), np.uint8))
    not_canopy = (classes != CANOPY_CODE).astype(np.uint8)
    if not_canopy.all():
        sp = np.zeros_like(water)
    else:
        dist = cv2.distanceTransform(not_canopy, cv2.DIST_L2, 5)  # distance to the nearest canopy pixel
        sp = ((classes == MUD_CODE) & (dist <= SP_CANOPY_PX)).astype(np.uint8)
    tg = np.zeros_like(water)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(water, connectivity=8)
    if n > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        body = (labels == largest).astype(np.uint8)
        tg = body & (1 - cv2.erode(body, np.ones((3, 3), np.uint8)))  # body pixels next to land
    return Candidates(wq=_subsample(wq > 0), sp=_subsample(sp > 0), tg=_subsample(tg > 0))


# ---- layout ----------------------------------------------------------------------------------------
class _Planner:
    def __init__(self, grid: ZoneGrid, seed: int) -> None:
        self.grid = grid
        self.rng = np.random.default_rng(seed)
        self.zone_ids = grid.zone_ids()
        self.centres = grid.centres()
        self.covered = np.zeros(len(self.zone_ids), bool)
        self.placed: list[tuple[str, float, float]] = []  # (node_type, e, s)
        self.reasons: list[str] = []

    def choose(self, keys: np.ndarray) -> int:
        """Index of the smallest key row (lexicographic); remaining ties go to the seeded RNG."""
        rounded = np.round(keys, 6)
        order = np.lexsort(rounded.T[::-1])
        best = rounded[order[0]]
        ties = [int(i) for i in order if np.array_equal(rounded[i], best)]
        return ties[0] if len(ties) == 1 else int(self.rng.choice(sorted(ties)))

    def place(self, node_type: str, e: float, s: float) -> None:
        self.placed.append((node_type, e, s))
        r = RADIUS_M.get(node_type)
        if r is not None:
            d = np.hypot(self.centres[:, 0] - e, self.centres[:, 1] - s)
            self.covered |= d <= r + 1e-9

    def same_type_dist(self, node_type: str, em: np.ndarray) -> np.ndarray:
        pts = np.array([(e, s) for t, e, s in self.placed if t == node_type], float).reshape(-1, 2)
        if not len(pts):
            return np.full(len(em), np.inf)
        return np.hypot(em[:, None, 0] - pts[None, :, 0], em[:, None, 1] - pts[None, :, 1]).min(axis=1)

    def reason(self, text: str) -> None:
        if text not in self.reasons:
            self.reasons.append(text)

    def greedy(self, node_type: str, em: np.ndarray) -> int | None:
        """Most newly covered zones; then the smaller maximum distance to the zones it covers. Spacing
        to the same type >= 80 m is mandatory: None when no candidate keeps it."""
        ok = self.same_type_dist(node_type, em) >= SPACING_M - 1e-9
        if not ok.any():
            return None
        d = np.hypot(em[:, None, 0] - self.centres[None, :, 0], em[:, None, 1] - self.centres[None, :, 1])
        cov = d <= RADIUS_M[node_type] + 1e-9
        new = cov & ~self.covered[None, :]
        n_new = new.sum(axis=1)
        zones = np.where(n_new[:, None] > 0, new, cov)  # the zones it covers (newly, while any)
        maxd = np.where(zones, d, -np.inf).max(axis=1)
        maxd = np.where(np.isfinite(maxd), maxd, np.inf)
        idx = np.flatnonzero(ok)
        return int(idx[self.choose(np.stack([-n_new[idx], maxd[idx]], axis=1))])

    def spread(self, node_type: str, pool: np.ndarray, first_near: tuple[float, float] | None) -> int:
        """Farthest-point sampling over ``pool`` (metres), restricted to points >= 80 m from the same type
        and not on top of any placed node: the point nearest ``first_near`` when given, else the point
        farthest from everything placed."""
        ok = self.same_type_dist(node_type, pool) >= SPACING_M - 1e-9
        pts = np.array([(e, s) for _, e, s in self.placed], float).reshape(-1, 2)
        dmin = np.full(len(pool), np.inf)
        if len(pts):
            dmin = np.hypot(pool[:, None, 0] - pts[None, :, 0], pool[:, None, 1] - pts[None, :, 1]).min(
                axis=1
            )
        ok &= dmin > 1e-6
        idx = np.flatnonzero(ok) if ok.any() else np.arange(len(pool))  # 400 cells: never empty in practice
        if first_near is not None:
            d = np.hypot(pool[idx, 0] - first_near[0], pool[idx, 1] - first_near[1])
            return int(idx[self.choose(d[:, None])])
        return int(idx[self.choose(-dmin[idx][:, None])])


def _cell_centres(grid: ZoneGrid) -> np.ndarray:
    cell = grid.size_m / ANALYSIS_CELLS
    c = (np.arange(ANALYSIS_CELLS) + 0.5) * cell
    return np.array([(e, s) for s in c for e in c], float)


def plan_layout(
    classes: np.ndarray | None,
    counts: dict[str, int] | None = None,
    seed: int = 0,
    *,
    grid: ZoneGrid = DEFAULT_GRID,
) -> Layout:
    """Place ``counts`` nodes (default 1 TG, 4 WQ, 3 SP): greedy TG -> WQ -> SP on the class map, or
    the low-confidence fallback spread when there is no map or water and mud cover < 2% of it."""
    counts = {**DEFAULT_COUNTS, **(counts or {})}
    k = grid.m_per_px
    plan = _Planner(grid, seed)
    west_mid_m = (0.0, grid.size_m / 2)
    if classes is None:
        fallback, reasons = True, [NO_CAPTURE]
    else:
        frac = float(np.isin(classes, (WATER_CODE, MUD_CODE)).mean())
        fallback, reasons = frac < MIN_WATER_MUD, [NO_WATER_MUD]
    cand = None if fallback else candidates(classes)
    cells = _cell_centres(grid)
    spread_started = False
    picks: list[tuple[str, float, float]] = []
    for node_type in TYPE_ORDER:
        pool_px = [] if cand is None else getattr(cand, _KEYS[node_type])
        if cand is not None and not pool_px and counts[_KEYS[node_type]]:
            plan.reason(f"no {node_type} candidates visible")
        for _ in range(counts[_KEYS[node_type]]):
            if node_type == TIDE:
                if pool_px:  # the shoreline candidate nearest the west-edge midpoint
                    px = np.array(pool_px, float) + 0.5
                    i = plan.choose(
                        np.hypot(px[:, 0] - west_mid_m[0] / k, px[:, 1] - west_mid_m[1] / k)[:, None]
                    )
                    e, s = px[i] * k
                else:  # the seaward (west) edge midpoint
                    e, s = west_mid_m
            else:
                i = None
                if pool_px:
                    em = (np.array(pool_px, float) + 0.5) * k
                    i = plan.greedy(node_type, em)
                    if i is None:
                        plan.reason(f"too few {node_type} candidates {SPACING_M:.0f} m apart")
                if i is not None:
                    e, s = em[i]
                else:  # farthest-point spreading over the analysis-cell centres
                    first = None if spread_started else (grid.size_m / 2, grid.size_m / 2)
                    e, s = cells[plan.spread(node_type, cells, first)]
                    spread_started = True
            plan.place(node_type, float(e), float(s))
            picks.append((node_type, float(e), float(s)))
    seq: dict[str, int] = {}
    positions = []
    for node_type, e, s in picks:
        seq[node_type] = seq.get(node_type, 0) + 1
        positions.append(
            NodePos(
                node_id=f"{PREFIXES[node_type]}-{seq[node_type]:02d}",
                node_type=node_type,
                e_m=e,
                s_m=s,
                u_px=e / k,
                v_px=s / k,
                zone_id=grid.zone_at(e, s),
            )
        )
    if fallback:
        return Layout(positions, "fallback_spread", "low", reasons)
    return Layout(positions, "class_map", "low" if plan.reasons else "high", plan.reasons)


# ---- applying a layout ------------------------------------------------------------------------------
class ConfirmationRequired(Exception):
    """A re-commission moves installed nodes and needs ``confirm: true`` (I1)."""


class Commissioning:
    """Runs commissioning against the NodeRegistry and stores each run in ``commissioning_runs``.

    The first run (no active nodes) installs the nodes as simulated. A re-commission needs
    confirmation; it keeps the IDs in type order (WQ-01..04 stay WQ-01..04), moves each node, logs
    ``re_commissioned``, awaits ``on_recommission()`` (Task 10: cancel active tasks), and emits
    ``node.registry`` and ``coverage.updated``. Missing nodes of a type are installed; extra ones stay.
    """

    def __init__(
        self,
        registry: Any,
        captures: Any,
        site: Any,
        repo: Any,
        bus: EventBus,
        on_recommission: Callable[[], Awaitable[None]] | None = None,
        *,
        clock: Clock | None = None,
        media: Any = None,
        seed: int = 0,
    ) -> None:
        self.registry, self.captures, self.site, self.repo, self.bus = registry, captures, site, repo, bus
        self.on_recommission = on_recommission
        # Coverage-gap advice for coverage.updated (Task 10 sets it to TaskingController.gaps; blocking).
        self.gaps: Callable[[list[Any]], list[Any]] | None = None
        self.clock = clock or RealClock()
        self.media = media
        self.seed = seed
        self.grid = ZoneGrid.from_site(site)
        self._lock = asyncio.Lock()

    # ---- reads ---------------------------------------------------------------------------------
    def latest(self) -> m.CommissioningRun | None:
        rows = self.repo.query(
            "SELECT * FROM commissioning_runs ORDER BY created_at DESC, id DESC LIMIT 1",
            table="commissioning_runs",
        )
        return _to_model(rows[0]) if rows else None

    # ---- run -----------------------------------------------------------------------------------
    async def run(self, confirm: bool) -> m.CommissioningRun:
        async with self._lock:
            active = await asyncio.to_thread(self.registry.nodes)
            recommission = bool(active)
            if recommission and not confirm:
                raise ConfirmationRequired('Re-commissioning moves installed nodes; send {"confirm": true}.')
            found = await asyncio.to_thread(self._latest_class_map)
            capture_id, classes = found if found else (None, None)
            layout = await asyncio.to_thread(plan_layout, classes, None, self.seed, grid=self.grid)
            run_id = uuid7()
            row = await asyncio.to_thread(self._apply, run_id, capture_id, layout, active)
            if recommission and self.on_recommission is not None:
                await self.on_recommission()
            nodes = await asyncio.to_thread(self.registry.nodes)
        self.bus.publish(
            "node.registry",
            {
                "change": "re_commissioned" if recommission else "commissioned",
                "node_ids": [p["node_id"] for p in row["positions"]],
                "commissioning_run_id": run_id,
            },
        )
        gaps = await asyncio.to_thread(self.gaps, nodes) if self.gaps is not None else []
        cov = coverage(nodes, gaps, site=self.site, grid=self.grid)
        self.bus.publish("coverage.updated", cov.model_dump(mode="json"))
        log.info(
            "commissioning run %s: %s, %s confidence (%s)",
            run_id,
            layout.method,
            layout.confidence,
            "re-commission" if recommission else "first run",
        )
        return _to_model(row)

    def _latest_class_map(self) -> tuple[str, np.ndarray] | None:
        fn = getattr(self.captures, "latest_class_map", None)
        return fn() if callable(fn) else None

    def _apply(
        self, run_id: str, capture_id: str | None, layout: Layout, active: list[Any]
    ) -> dict[str, Any]:
        """Install or move the nodes (blocking: the registry talks to the broker), then store the run."""
        existing: dict[str, list[Any]] = {}
        for n in sorted(active, key=lambda n: n.id):
            existing.setdefault(n.node_type, []).append(n)
        positions = []
        for p in layout.positions:
            queue = existing.get(p.node_type) or []
            if queue:
                node = self.registry.recommission(queue.pop(0).id, p.e_m, p.s_m, commissioning_run_id=run_id)
            else:
                node, _ = self.registry.install(
                    p.node_type, "simulated", p.e_m, p.s_m, commissioning_run_id=run_id, emit=False
                )
            positions.append(
                {
                    "node_id": node.id,
                    "node_type": node.node_type,
                    "e_m": node.e_m,
                    "s_m": node.s_m,
                    "lat": node.lat,
                    "lng": node.lng,
                    "u_px": node.u_px,
                    "v_px": node.v_px,
                    "zone_id": node.zone_id,
                }
            )
        bz = by_zone(self.registry.nodes(), self.grid)
        row = {
            "id": run_id, "created_at": to_iso(self.clock.now()), "capture_id": capture_id,
            "method": layout.method, "confidence": layout.confidence, "reasons": list(layout.reasons),
            "positions": positions,
            "coverage": {
                "covered": [z for z, c in bz.items() if c["water"] or c["soil"]],
                "uncovered": [z for z, c in bz.items() if not (c["water"] or c["soil"])],
                "by_zone": bz,
            },
            "seed": self.seed,
        }  # fmt: skip
        self.repo.insert("commissioning_runs", row)
        if capture_id and self.media is not None:  # H7 / A2: the run's capture is kept
            cap = self.repo.get("captures", {"id": capture_id}) or {}
            self.media.set_protected("captures", list((cap.get("media") or {}).values()), True)
        return row


def _to_model(row: dict[str, Any]) -> m.CommissioningRun:
    cov = row.get("coverage") or {}
    return m.CommissioningRun(
        id=row["id"],
        created_at=row["created_at"],
        capture_id=row.get("capture_id"),
        method=row["method"],
        confidence=row["confidence"],
        reasons=row.get("reasons") or [],
        positions=[m.CommissionedPosition(**p) for p in row.get("positions") or []],
        coverage=m.CommissioningCoverage(covered=cov.get("covered", []), uncovered=cov.get("uncovered", [])),
    )
