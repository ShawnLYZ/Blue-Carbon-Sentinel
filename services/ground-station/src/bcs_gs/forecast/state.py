"""Forecast value types: zone state, parameter set and bands."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


@dataclass(frozen=True)
class Band:
    low: float
    central: float
    high: float


@dataclass(frozen=True)
class ZoneState:
    C: float
    H: float
    L: float
    sigma: float
    stressors: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    water_adjacent: bool = False  # ruling R2


@dataclass(frozen=True)
class ParamSet:
    g: float = 0.06
    m: float = 0.20
    h_rec: float = 0.25
    h_dec: float = 0.25
    e: float = 0.02
    trend: float = 0.03
    survival_rhizophora: float = 0.60
    survival_avicennia: float = 0.65
    tau_rhizophora: float = 6.0
    tau_avicennia: float = 5.0
    factor_silt_fence: float = 0.4
    factor_reopen_channel: float = 0.5
    factor_stop_pollution: float = 0.3

    @classmethod
    def from_bands(cls, bands: dict[str, Any], which: str) -> ParamSet:
        """One run's parameters: ``which`` is low, central or high (outcome-ordered, ruling R1)."""
        vals = {}
        for f in fields(cls):
            if f.name in bands:
                b = bands[f.name]
                vals[f.name] = float(b[which] if isinstance(b, dict) else getattr(b, which))
        return cls(**vals)

    def factors(self) -> dict[str, float]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name.startswith("factor_")}


ParamBands = dict[str, Any]  # parameter name -> object or dict with low / central / high


def initial_state(
    metrics: Any, baseline_vari: float | None, assessment: Any | None, water_adjacent: bool = False
) -> ZoneState:
    """Starting state from a zone's latest metrics, its baseline VARI and its latest assessment."""
    dieback = metrics.dieback_pct / 100
    if baseline_vari and metrics.vari_mean is not None:
        h = max(0.0, min(1.0, metrics.vari_mean / baseline_vari)) * (1 - dieback)
    else:
        h = 1 - dieback
    stressors = {k: v for k, v in assessment.stressors.items() if v is not None} if assessment else {}
    weights = dict(assessment.weights) if assessment else {}
    return ZoneState(
        C=metrics.canopy_pct / 100,
        H=h,
        L=1 - metrics.water_pct / 100,
        sigma=assessment.risk_score / 100 if assessment else 0.0,
        stressors=stressors,
        weights=weights,
        water_adjacent=water_adjacent,
    )
