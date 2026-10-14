"""Vegetation decline stressor (N2) and the sensor composite (N5)."""

from __future__ import annotations

from bcs_gs.core.config import Settings
from bcs_gs.fusion.bands import SENSOR_STRESSORS, default_settings


def vegetation_decline(
    canopy_loss_pp: float | None,
    dieback_pct: float | None,
    vari_drop: float | None,
    cfg: Settings | None = None,
) -> float | None:
    """clamp(max(loss/30, dieback/50, vari_drop/0.30), 0, 1); None when nothing is measured."""
    v = (cfg or default_settings()).risk.vegetation
    terms = [
        x / full
        for x, full in (
            (canopy_loss_pp, v["canopy_loss_pp_full"]),
            (dieback_pct, v["dieback_pct_full"]),
            (vari_drop, v["vari_drop_full"]),
        )
        if x is not None
    ]
    return max(0.0, min(1.0, max(terms))) if terms else None


def sensor_composite(stressors: dict[str, float | None], base_weights: dict[str, float]) -> float | None:
    """sum(w s) / sum(w) over measured sensor stressors (no multipliers, no vegetation); None if none."""
    num = den = 0.0
    for k in SENSOR_STRESSORS:
        s = stressors.get(k)
        if s is None or k not in base_weights:
            continue
        num += base_weights[k] * s
        den += base_weights[k]
    return num / den if den > 0 else None
