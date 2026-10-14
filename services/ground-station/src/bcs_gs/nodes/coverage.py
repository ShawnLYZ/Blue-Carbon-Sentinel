"""Coverage model (addendum N9) and coverage-gap advice (spec §15).

A WQ node covers a zone when the distance to the zone centre is <= 150 m, an SP node when it is
<= 100 m; the TG gives site-wide tide context only. A zone is covered when at least one WQ or SP
covers it. Pure functions: nodes are any objects with ``id`` (or ``node_id``), ``node_type``,
``e_m`` and ``s_m`` (and optionally ``status``; decommissioned nodes cover nothing).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from bcs_gs.api import models as m

WATER, SOIL, TIDE = "water_quality", "soil_probe", "tide_gauge"
RADIUS_M = {WATER: 150.0, SOIL: 100.0}
CHANNEL = {WATER: "water", SOIL: "soil"}
CANOPY_CODE, WATER_CODE, MUD_CODE, OTHER_CODE = 1, 2, 3, 4  # F5 class-map values


@dataclass(frozen=True)
class ZoneGrid:
    """The F4 zone grid: ``cols`` x ``rows`` zones of ``zone_m`` over a ``size_m`` square site, IDs
    ``<site>-<letter><digit>`` (letter = east column, digit = south row), on a ``raster_px`` raster."""

    site_id: str = "KSL"
    size_m: float = 500.0
    zone_m: float = 100.0
    cols: int = 5
    rows: int = 5
    letters: str = "ABCDE"
    raster_px: int = 512

    @classmethod
    def from_site(cls, site: Any) -> ZoneGrid:
        s = site.site()
        zones = site.zones()
        return cls(
            site_id=s.id,
            size_m=float(s.size_m),
            zone_m=float(zones[0].bounds_site_m.e1 - zones[0].bounds_site_m.e0),
            cols=1 + max(z.col for z in zones),
            rows=1 + max(z.row for z in zones),
            letters="".join(sorted({z.label[0] for z in zones})),
            raster_px=round(site.metres_to_raster(s.size_m, 0)[0]),
        )

    @property
    def m_per_px(self) -> float:
        return self.size_m / self.raster_px

    def zone_ids(self) -> list[str]:
        """Column-major, as the SiteRegistry lists them: A1..A5, B1..."""
        return [self.zone_id(c, r) for c in range(self.cols) for r in range(self.rows)]

    def zone_id(self, col: int, row: int) -> str:
        return f"{self.site_id}-{self.letters[col]}{row + 1}"

    def col_row(self, zone_id: str) -> tuple[int, int]:
        label = zone_id.rsplit("-", 1)[-1]
        return self.letters.index(label[0]), int(label[1:]) - 1

    def centre(self, zone_id: str) -> tuple[float, float]:
        c, r = self.col_row(zone_id)
        return (c + 0.5) * self.zone_m, (r + 0.5) * self.zone_m

    def centres(self) -> np.ndarray:
        """Zone centres (e, s) in metres, in ``zone_ids()`` order."""
        return np.array([self.centre(z) for z in self.zone_ids()], float)

    def zone_at(self, e: float, s: float) -> str:
        c = min(max(int(e // self.zone_m), 0), self.cols - 1)
        r = min(max(int(s // self.zone_m), 0), self.rows - 1)
        return self.zone_id(c, r)

    def neighbourhood(self, zone_id: str) -> list[str]:
        """The zone and its (up to 8) adjacent zones."""
        c0, r0 = self.col_row(zone_id)
        return [
            self.zone_id(c, r)
            for c in range(max(c0 - 1, 0), min(c0 + 2, self.cols))
            for r in range(max(r0 - 1, 0), min(r0 + 2, self.rows))
        ]

    def zone_pixels(self, zone_id: str) -> tuple[slice, slice]:
        """(rows, cols) slices of the zone on the site raster."""
        c, r = self.col_row(zone_id)
        k = self.raster_px / self.size_m
        return (
            slice(round(r * self.zone_m * k), round((r + 1) * self.zone_m * k)),
            slice(round(c * self.zone_m * k), round((c + 1) * self.zone_m * k)),
        )


DEFAULT_GRID = ZoneGrid()


def node_id(node: Any) -> str:
    return getattr(node, "id", None) or node.node_id


def _active(nodes: Iterable[Any]) -> list[Any]:
    return [n for n in nodes if getattr(n, "status", None) != "decommissioned" and n.e_m is not None]


def covered_zones(node_type: str, e_m: float, s_m: float, grid: ZoneGrid = DEFAULT_GRID) -> list[str]:
    """Zones a node of ``node_type`` at (e, s) covers (N9); none for a TG."""
    radius = RADIUS_M.get(node_type)
    if radius is None:
        return []
    d = np.hypot(grid.centres()[:, 0] - e_m, grid.centres()[:, 1] - s_m)
    return [z for z, di in zip(grid.zone_ids(), d, strict=True) if di <= radius + 1e-9]


def node_covers(node: Any, grid: ZoneGrid = DEFAULT_GRID) -> dict[str, list[str]]:
    """I3 ``Node.covers``: ``{"water": [zone], "soil": [zone]}``."""
    out: dict[str, list[str]] = {"water": [], "soil": []}
    if getattr(node, "status", None) == "decommissioned" or node.e_m is None:
        return out
    ch = CHANNEL.get(node.node_type)
    if ch:
        out[ch] = covered_zones(node.node_type, node.e_m, node.s_m, grid)
    return out


def by_zone(nodes: Iterable[Any], grid: ZoneGrid = DEFAULT_GRID) -> dict[str, dict[str, list[str]]]:
    """``{zone: {"water": [node], "soil": [node]}}`` for every zone, node IDs sorted."""
    out = {z: {"water": [], "soil": []} for z in grid.zone_ids()}
    for n in sorted(_active(nodes), key=node_id):
        ch = CHANNEL.get(n.node_type)
        if ch:
            for z in covered_zones(n.node_type, n.e_m, n.s_m, grid):
                out[z][ch].append(node_id(n))
    return out


def covered_set(nodes: Iterable[Any], grid: ZoneGrid = DEFAULT_GRID) -> set[str]:
    return {z for z, c in by_zone(nodes, grid).items() if c["water"] or c["soil"]}


@dataclass(frozen=True)
class GapSuggestion:
    zone_id: str
    node_type: str
    e_m: float
    s_m: float
    u_px: float
    v_px: float
    newly_covered: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def id(self) -> str:
        """Stable per zone, so ``POST /nodes {suggestion_id}`` can find it again."""
        return f"gap-{self.zone_id}"


def coverage(
    nodes: Iterable[Any],
    gaps: Sequence[GapSuggestion] = (),
    *,
    site: Any = None,
    grid: ZoneGrid | None = None,
) -> m.Coverage:
    """I3 ``Coverage``. ``site`` (a SiteRegistry) gives the gaps' lat/lng and the zone grid."""
    grid = grid or (ZoneGrid.from_site(site) if site is not None else DEFAULT_GRID)
    bz = by_zone(nodes, grid)
    zones = [
        m.CoverageZone(zone_id=z, covered=bool(c["water"] or c["soil"]), water=c["water"], soil=c["soil"])
        for z, c in bz.items()
    ]
    if gaps and site is None:
        raise ValueError("coverage gaps need the site for lat/lng")
    out_gaps = []
    for g in gaps:
        lng, lat = site.metres_to_lnglat(g.e_m, g.s_m)
        out_gaps.append(
            m.CoverageGap(
                id=g.id,
                zone_id=g.zone_id,
                node_type=g.node_type,
                e_m=g.e_m,
                s_m=g.s_m,
                lat=lat,
                lng=lng,
                u_px=g.u_px,
                v_px=g.v_px,
                newly_covered=g.newly_covered,
                reason=g.reason,
            )
        )
    return m.Coverage(zones=zones, gaps=out_gaps)


def gap_suggestions(
    zone_ids_needing: Iterable[str],
    classes: np.ndarray | None,
    nodes: Iterable[Any],
    *,
    grid: ZoneGrid = DEFAULT_GRID,
) -> list[GapSuggestion]:
    """Coverage-gap advice (§15) for the zones the caller says need it (flagged or High/Critical).

    Zones that already have WQ/SP coverage are skipped. For each remaining zone: WQ if the zone or a
    neighbour has water, else SP; the best commissioning candidate of that type inside or adjacent
    to the zone that covers it, by most newly covered zones, then the smaller maximum distance to
    them, then the distance to the zone centre. Without a fitting candidate, the zone centre (SP)."""
    from bcs_gs.nodes.commissioning import candidates  # local: commissioning imports this module

    nodes = _active(nodes)
    covered = covered_set(nodes, grid)
    cand = candidates(classes) if classes is not None else None
    zone_ids = grid.zone_ids()
    centres = grid.centres()
    k = grid.m_per_px
    out: list[GapSuggestion] = []
    for zone in dict.fromkeys(zone_ids_needing):
        if zone in covered:
            continue
        hood = grid.neighbourhood(zone)
        has_water = False
        if classes is not None:
            has_water = any(bool((classes[grid.zone_pixels(z)] == WATER_CODE).any()) for z in hood)
        order = [WATER, SOIL] if has_water else [SOIL]
        pick = None
        for node_type in order if cand is not None else []:
            pts = np.array(cand.wq if node_type == WATER else cand.sp, float).reshape(-1, 2)
            if not len(pts):
                continue
            em = (pts + 0.5) * k
            in_hood = np.array([grid.zone_at(e, s) in hood for e, s in em], bool)
            d = np.hypot(em[:, None, 0] - centres[None, :, 0], em[:, None, 1] - centres[None, :, 1])
            cov = d <= RADIUS_M[node_type] + 1e-9
            zi = zone_ids.index(zone)
            ok = in_hood & cov[:, zi]
            if not ok.any():
                continue
            uncovered = np.array([z not in covered for z in zone_ids], bool)
            new = cov & uncovered[None, :]
            best = None
            for i in np.flatnonzero(ok):
                n_new = int(new[i].sum())
                maxd = float(d[i][new[i]].max())
                key = (-n_new, round(maxd, 6), round(float(d[i, zi]), 6), i)
                if best is None or key < best[0]:
                    best = (key, i)
            i = best[1]
            pick = (node_type, em[i], pts[i] + 0.5, [z for z, f in zip(zone_ids, new[i], strict=True) if f])
            break
        if pick is not None:
            node_type, (e, s), (u, v), newly = pick
            why = "water in or next to the zone" if node_type == WATER else "no water in or next to the zone"
            reason = f"{zone} has no WQ/SP coverage; {why}"
        else:
            e, s = grid.centre(zone)
            node_type, u, v = SOIL, e / k, s / k
            newly = [z for z in covered_zones(SOIL, e, s, grid) if z not in covered]
            reason = f"{zone} has no WQ/SP coverage; no candidate position visible, zone centre"
        out.append(
            GapSuggestion(
                zone_id=zone,
                node_type=node_type,
                e_m=float(e),
                s_m=float(s),
                u_px=float(u),
                v_px=float(v),
                newly_covered=newly,
                reason=reason,
            )
        )
    return out
