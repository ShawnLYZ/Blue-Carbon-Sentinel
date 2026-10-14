"""Confidence components and overall (N4)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from bcs_gs.core.config import Settings
from bcs_gs.fusion.bands import default_settings, stress_from_breakpoints

# prediction tier factors, derived from config/risk.yaml (confidence.prediction.tier_factor)
TIER_FACTOR: dict[str, float] = {
    k: float(v) for k, v in default_settings().risk.confidence["prediction"]["tier_factor"].items()
}


@dataclass(frozen=True)
class NodeHealthView:
    """What sensor_confidence needs to know about one covering node."""

    online: bool
    battery_pct: float | None
    last_sample_age_s: float | None
    interval_s: float
    stuck_or_spike: bool = False


def tier_factor(tier: str, cfg: Settings | None = None) -> float:
    """Prediction factor of an AI tier, read from config/risk.yaml."""
    return float((cfg or default_settings()).risk.confidence["prediction"]["tier_factor"][tier])


def camera_confidence(
    evidence_grade: bool,
    age_s: float,
    camera_online: bool,
    locked: bool,
    four_corner: bool,
    has_capture: bool,
    cfg: Settings | None = None,
) -> float:
    c = (cfg or default_settings()).risk.confidence["camera"]
    if not has_capture:
        return float(c["no_capture"])
    q = c["q_evidence"] if evidence_grade else c["q_other"]
    r = stress_from_breakpoints(age_s, [(float(a), float(b)) for a, b in c["recency_points_s"]])
    if not camera_online:
        r = min(r, c["offline_cap"])
    lock = c["exposure_locked"] if locked else c["exposure_unlocked"]
    k = c["calibration_four_corner"] if four_corner else c["calibration_default"]
    return float(q * r * lock * k)


def sensor_confidence(
    measured_weight_sum: float,
    node_states: Sequence[NodeHealthView],
    faulted: bool,
    cfg: Settings | None = None,
) -> float:
    """max(floor, f * phi * eta * psi); ``measured_weight_sum`` = sum of base weights of measured sensors."""
    c = (cfg or default_settings()).risk.confidence["sensor"]
    if not node_states:
        return float(c["no_covering_node"])
    f = measured_weight_sum / c["sensor_weight_total"]
    n = len(node_states)
    phi = (
        sum(
            1.0
            if s.last_sample_age_s is not None and s.last_sample_age_s <= c["freshness_intervals"] * s.interval_s
            else c["stale_phi"]
            for s in node_states
        )
        / n
    )
    eta = (
        sum(
            (1.0 if s.online else 0.0)
            * (1.0 if s.battery_pct is None or s.battery_pct >= c["battery_ok_pct"] else c["low_battery_eta"])
            for s in node_states
        )
        / n
    )
    psi = c["fault_psi"] if faulted or any(s.stuck_or_spike for s in node_states) else 1.0
    return max(float(c["floor"]), f * phi * eta * psi)


def overall(camera: float, sensor: float, prediction: float, cfg: Settings | None = None) -> float:
    """Weighted geometric mean exp(0.4 ln camera + 0.4 ln sensor + 0.2 ln prediction)."""
    w = (cfg or default_settings()).risk.confidence["overall_weights"]
    if min(camera, sensor, prediction) <= 0:
        return 0.0
    return math.exp(
        w["camera"] * math.log(camera) + w["sensor"] * math.log(sensor) + w["prediction"] * math.log(prediction)
    )
