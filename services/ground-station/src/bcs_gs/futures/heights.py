"""Future height maps and the per-zone changes behind both repaints (pure)."""

from __future__ import annotations

from typing import Any

import numpy as np

from bcs_gs.futures.repaint import CANOPY, WATER, ZoneChange, ZoneGrid, eroded_mask, strip_px

TURBIDITY_KEY = "turbidity"
START_YEAR = 2026
WATER_HEIGHT_PERCENTILE = 5


def future_heights(
    height_u16: np.ndarray, classes: np.ndarray, zone_changes: dict[str, ZoneChange], *, grid: ZoneGrid
) -> np.ndarray:
    """A new uint16 height map: canopy heights fall by ``canopy_loss_frac``; eroded strips are set to the
    water height (the 5th percentile of the capture's water pixels)."""
    if height_u16.shape != classes.shape or classes.shape != grid.labels.shape:
        raise ValueError("heights, class map and zone grid must have the same shape")
    out = height_u16.astype(np.float64)
    water_px = height_u16[classes == WATER]
    water_h = float(np.percentile(water_px, WATER_HEIGHT_PERCENTILE)) if water_px.size else 0.0
    for zone_id, ch in sorted(zone_changes.items()):
        if ch.is_zero() or zone_id not in grid.ids:
            continue
        zone = grid.mask(zone_id)
        loss = _clip01(ch.canopy_loss_frac)
        if loss:
            out[zone & (classes == CANOPY)] *= 1.0 - loss
        out[eroded_mask(classes, zone, strip_px(ch, grid))] = water_h
    return np.clip(np.rint(out), 0, 65535).astype(np.uint16)


def _clip01(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def _val(b: Any) -> float:
    return float(b["central"] if isinstance(b, dict) else b.central)


def zone_changes_for(
    forecast: dict[str, Any], scenario: str, year: int, base_state: dict[str, Any]
) -> dict[str, ZoneChange]:
    """Changes from 2026 to ``year`` per zone. ``forecast`` is the stored forecast row (its ``keyframes``
    carry sigma and the cohort fraction, ruling R6); ``base_state`` maps zone ID to its ZoneState (the
    stressors of the base capture's assessment). The central run is used throughout.

    canopy loss = max(0, C0 - Cy) / C0; dieback = 1 - Hy / H0; eroded strip = (L0 - Ly) x 100 m;
    turbidity stress = clamp(s0 x sigma_y / max(sigma_0, 1e-6), 0, 1) (ruling R10); sapling fill = the
    cohort fraction."""
    zones = (forecast["keyframes"].get(scenario) or {}).get("zones") or {}
    out: dict[str, ZoneChange] = {}
    for zone_id, points in zones.items():
        by_year = {int(p["year"]): p for p in points}
        p0, py = by_year.get(START_YEAR), by_year.get(year)
        if p0 is None or py is None:
            continue
        if year == START_YEAR:
            out[zone_id] = ZoneChange()  # 2026 is the real capture: zero change
            continue
        c0, cy = _val(p0["canopy"]), _val(py["canopy"])
        h0, hy = _val(p0["health"]), _val(py["health"])
        l0, ly = _val(p0["land"]), _val(py["land"])
        st = base_state.get(zone_id)
        s0 = float((getattr(st, "stressors", None) or {}).get(TURBIDITY_KEY) or 0.0)
        sigma0, sigma_y = _val(p0["sigma"]), _val(py["sigma"])
        out[zone_id] = ZoneChange(
            dieback_frac=_clip01(1 - hy / h0) if h0 > 1e-9 else 0.0,
            canopy_loss_frac=_clip01(max(0.0, c0 - cy) / c0) if c0 > 1e-9 else 0.0,
            eroded_strip_m=max(0.0, (l0 - ly) * 100.0),
            turbidity_stress=_clip01(s0 * sigma_y / max(sigma0, 1e-6)) if s0 > 0 else 0.0,
            sapling_fill=_clip01(float(py.get("cohort_fraction") or 0.0)),
        )
    return out
