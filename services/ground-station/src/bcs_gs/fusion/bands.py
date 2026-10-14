"""Stressor breakpoints (addendum N1) and the single stressor -> band-parameter mapping."""

from __future__ import annotations

from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from bcs_gs.core.config import Settings, load_settings

# stressor name (config/risk.yaml weights) -> parameter key in config/bands.yaml.
# Vegetation is not a sensor stressor and has no band.
BAND_KEY = {
    "salinity": "salinity_psu",
    "porewater_salinity": "porewater_salinity_psu",
    "turbidity": "turbidity_ntu",
    "do": "do_mg_l",
    "temperature": "temp_c",
    "ph": "ph",
}
SENSOR_STRESSORS = tuple(BAND_KEY)


def _repo_root() -> Path:
    for p in Path(__file__).resolve().parents:
        if (p / "config" / "risk.yaml").exists():
            return p
    raise FileNotFoundError("config/risk.yaml not found above the fusion package")


@lru_cache(maxsize=1)
def default_settings() -> Settings:
    """The committed configuration, read once (no .env, no overrides)."""
    return load_settings(_repo_root(), env_file=None)


def stress_from_breakpoints(value: float, points: list[tuple[float, float]]) -> float:
    """Piecewise-linear value -> stress, held constant beyond the end points (N1)."""
    pts = sorted(points)
    if value <= pts[0][0]:
        return float(pts[0][1])
    if value >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in pairwise(pts):
        if value == x1:
            return float(y1)  # exact at a breakpoint
        if x0 <= value < x1:
            return float(y0 + (y1 - y0) * (value - x0) / (x1 - x0))
    return float(pts[-1][1])  # pragma: no cover


def band_points(stressor: str, cfg: Settings | None = None) -> list[tuple[float, float]]:
    s = cfg or default_settings()
    return list(s.bands.parameters[BAND_KEY[stressor]].breakpoints)


def sensor_stress(stressor: str, value: float, cfg: Settings | None = None) -> float:
    """Stress (0-1) of a sensor reading for a stressor key such as ``do`` or ``porewater_salinity``."""
    return stress_from_breakpoints(value, band_points(stressor, cfg))
