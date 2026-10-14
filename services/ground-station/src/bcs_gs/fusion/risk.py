"""Effective weights and the risk score / class (N3)."""

from __future__ import annotations

from bcs_gs.api.models import RiskClass
from bcs_gs.core.config import Settings
from bcs_gs.fusion.bands import default_settings


def effective_weights(
    base: dict[str, float],
    multipliers: dict[str, float],
    measured: set[str],
    cfg: Settings | None = None,
) -> dict[str, float]:
    """w' = w * clamp(m) for measured stressors only, renormalised to sum to 1 ({} if none)."""
    lo, hi = (cfg or default_settings()).risk.multiplier_bounds
    raw = {k: w * max(lo, min(hi, multipliers.get(k, 1.0))) for k, w in base.items() if k in measured}
    total = sum(raw.values())
    return {k: w / total for k, w in raw.items()} if total > 0 else {}


def risk_class(score: float, cfg: Settings | None = None) -> RiskClass:
    """Class of the unrounded score: first limit it is below, else critical."""
    limits = (cfg or default_settings()).risk.class_limits
    if score < limits["low"]:
        return "low"
    if score < limits["medium"]:
        return "medium"
    if score < limits["high"]:
        return "high"
    return "critical"


def risk(
    stressors: dict[str, float | None],
    weights_eff: dict[str, float],
    cfg: Settings | None = None,
) -> tuple[float, RiskClass]:
    """100 * sum(w' s) over measured stressors. Raises ValueError when none is measured (no assessment)."""
    if not weights_eff:
        raise ValueError("no measured stressor")
    missing = [k for k in weights_eff if stressors.get(k) is None]
    if missing:
        raise ValueError(f"weights given for unmeasured stressors {missing}; renormalise over the measured set")
    score = 100.0 * sum(w * stressors[k] for k, w in weights_eff.items())  # type: ignore[operator]
    return score, risk_class(score, cfg)
