"""Site registry: zones and coordinate transforms (addendum F1, F4, I3)."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel

from bcs_gs.core.config import Point2, SiteConfig


class BoundsM(BaseModel):
    e0: float
    s0: float
    e1: float
    s1: float


class Zone(BaseModel):
    id: str
    label: str
    coordinate_id: str
    col: int
    row: int
    bounds: dict[str, Any]  # GeoJSON Polygon, ring NW -> NE -> SE -> SW -> NW in (lng, lat)
    bounds_site_m: BoundsM
    centre: Point2
    area_ha: float


class PlannedSite(BaseModel):
    id: str
    name: str
    region: str
    centre: Point2
    status: Literal["planned"] = "planned"
    rationale: str


class Site(BaseModel):
    id: str
    name: str
    region: str
    anchor_nw: Point2
    size_m: float
    scale_label: str
    bounds: dict[str, Any]
    centre: Point2
    zones: list[Zone]
    planned_sites: list[PlannedSite]


def _metres_per_degree(phi_deg: float) -> tuple[float, float]:
    """(M_lat, M_lng) in metres per degree at latitude phi (addendum F4)."""
    p = math.radians(phi_deg)
    m_lat = 111132.954 - 559.822 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
    m_lng = 111412.84 * math.cos(p) - 93.5 * math.cos(3 * p) + 0.118 * math.cos(5 * p)
    return m_lat, m_lng


class SiteRegistry:
    def __init__(self, site_cfg: SiteConfig) -> None:
        self._cfg = site_cfg
        self._lat_nw = site_cfg.anchor_nw.lat
        self._lng_nw = site_cfg.anchor_nw.lng
        self._size = float(site_cfg.size_m)
        self._raster_px = int(site_cfg.model_extra.get("raster_px", 512)) if site_cfg.model_extra else 512
        grid = site_cfg.zone_grid or {}
        self._cols = int(grid.get("cols", 5))
        self._rows = int(grid.get("rows", 5))
        self._zone_m = float(grid.get("zone_size_m", 100))
        self._letters: list[str] = list(grid.get("col_letters", "ABCDE"))
        # phi: site-centre latitude. One refinement of the centre estimate is ample.
        phi = self._lat_nw - (self._size / 2) / 111000.0
        m_lat, _ = _metres_per_degree(phi)
        phi = self._lat_nw - (self._size / 2) / m_lat
        self._m_lat, self._m_lng = _metres_per_degree(phi)
        self._zones = [self._build_zone(c, r) for r in range(self._rows) for c in range(self._cols)]
        # Order: column letters west to east, rows north to south -> A1..A5, B1.. (F1, F4)
        self._zones.sort(key=lambda z: (z.col, z.row))
        self._by_id = {z.id: z for z in self._zones}

    # ---- transforms (F4) ----
    def raster_to_metres(self, u: float, v: float) -> tuple[float, float]:
        k = self._size / self._raster_px
        return (u * k, v * k)

    def metres_to_raster(self, e: float, s: float) -> tuple[float, float]:
        k = self._raster_px / self._size
        return (e * k, s * k)

    def metres_to_lnglat(self, e: float, s: float) -> tuple[float, float]:
        return (self._lng_nw + e / self._m_lng, self._lat_nw - s / self._m_lat)

    def lnglat_to_metres(self, lng: float, lat: float) -> tuple[float, float]:
        return ((lng - self._lng_nw) * self._m_lng, (self._lat_nw - lat) * self._m_lat)

    # ---- identifiers (F1) ----
    def zone_label(self, col: int, row: int) -> str:
        return f"{self._letters[col]}{row + 1}"

    def coordinate_id(self, lat: float, lng: float) -> str:
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lng >= 0 else "W"
        return f"{self._cfg.id}-{ns}{abs(lat):.4f}-{ew}{abs(lng):.4f}"

    def zone_at(self, e: float, s: float) -> str:
        if not (0 <= e <= self._size and 0 <= s <= self._size):
            raise ValueError(f"position ({e}, {s}) is outside the site")
        col = min(int(e // self._zone_m), self._cols - 1)
        row = min(int(s // self._zone_m), self._rows - 1)
        return f"{self._cfg.id}-{self.zone_label(col, row)}"

    # ---- models (I3) ----
    def _build_zone(self, col: int, row: int) -> Zone:
        z = self._zone_m
        e0, s0, e1, s1 = col * z, row * z, col * z + z, row * z + z
        ring = [
            list(self.metres_to_lnglat(e, s)) for e, s in ((e0, s0), (e1, s0), (e1, s1), (e0, s1), (e0, s0))
        ]
        clng, clat = self.metres_to_lnglat(e0 + z / 2, s0 + z / 2)
        label = self.zone_label(col, row)
        return Zone(
            id=f"{self._cfg.id}-{label}",
            label=label,
            coordinate_id=self.coordinate_id(clat, clng),
            col=col,
            row=row,
            bounds={"type": "Polygon", "coordinates": [ring]},
            bounds_site_m=BoundsM(e0=e0, s0=s0, e1=e1, s1=s1),
            centre=Point2(lat=clat, lng=clng),
            area_ha=z * z / 10000.0,
        )

    def zones(self) -> list[Zone]:
        return list(self._zones)

    def zone(self, zone_id: str) -> Zone:
        try:
            return self._by_id[zone_id]
        except KeyError:
            raise KeyError(f"unknown zone {zone_id!r}") from None

    def site(self) -> Site:
        s = self._size
        ring = [list(self.metres_to_lnglat(e, v)) for e, v in ((0, 0), (s, 0), (s, s), (0, s), (0, 0))]
        clng, clat = self.metres_to_lnglat(s / 2, s / 2)
        return Site(
            id=self._cfg.id,
            name=self._cfg.name,
            region=self._cfg.region,
            anchor_nw=Point2(lat=self._lat_nw, lng=self._lng_nw),
            size_m=s,
            scale_label=self._cfg.scale_label,
            bounds={"type": "Polygon", "coordinates": [ring]},
            centre=Point2(lat=clat, lng=clng),
            zones=self.zones(),
            planned_sites=[PlannedSite(**p.model_dump()) for p in self._cfg.planned_sites],
        )
