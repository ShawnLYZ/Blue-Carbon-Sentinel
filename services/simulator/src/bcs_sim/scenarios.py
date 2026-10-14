"""Ramped zone scenarios with distance reach (addendum A1, N6; design spec 13).

Offsets use the G4 keys. Results are clamped to the G4 ranges by the caller (readings pipeline).

"Night" for the low-oxygen scenario is defined from the same MYT diurnal model as the environment:
the dissolved-oxygen diurnal term ``cos(2*pi*(hour_myt - do_peak_hour_myt)/24)`` is negative, i.e.
night is the half-day opposite the DO peak (peak 14:00 MYT -> day 08:00-20:00, night 20:00-08:00).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .clock import Clock
from .config import load_sim_config
from .environment import _diurnal

DEFAULT_RAMP_S = 60.0
RECOVERY_TAU_S = 120.0
REACH_M = {"water_quality": 150.0, "soil_probe": 100.0, "tide_gauge": 500.0}
NODE_KEYS = {
    "water_quality": ("salinity_psu", "turbidity_ntu", "do_mg_l", "temp_c", "ph"),
    "soil_probe": ("porewater_salinity_psu", "soil_moisture_pct"),
    "tide_gauge": ("water_level_cm",),
}
SITE_SIZE_M = 500.0
ZONE_SIZE_M = 100.0
_DO_PEAK_HOUR_MYT = load_sim_config().water.do_peak_hour_myt


@dataclass(frozen=True)
class ScenarioDef:
    offsets: dict[str, float] = field(default_factory=dict)
    key_tau_s: dict[str, float] = field(default_factory=dict)  # per-key ramp tau override
    night_offsets: dict[str, float] = field(default_factory=dict)  # added only at night
    fraction_day: float | None = None  # low oxygen: DO saturation-fraction target
    fraction_night: float | None = None


SCENARIOS: dict[str, ScenarioDef] = {
    "sediment_runoff": ScenarioDef({"turbidity_ntu": 150, "do_mg_l": -1.0, "ph": -0.2, "salinity_psu": -2}),
    "salt_intrusion": ScenarioDef(
        {"salinity_psu": 8, "porewater_salinity_psu": 20, "soil_moisture_pct": -15},
        key_tau_s={"porewater_salinity_psu": 180.0},
    ),
    "low_oxygen": ScenarioDef(
        {"turbidity_ntu": 20}, night_offsets={"ph": -0.4}, fraction_day=0.6, fraction_night=0.3
    ),
    "heat_stress": ScenarioDef({"temp_c": 4, "porewater_salinity_psu": 5}),
    "heavy_rain": ScenarioDef(
        {"salinity_psu": -12, "turbidity_ntu": 80, "water_level_cm": 40, "soil_moisture_pct": 15}
    ),
    "healthy": ScenarioDef(),
    "recovery": ScenarioDef(),
}


class Offsets(dict):
    """Additive offsets by G4 key (empty when nothing reaches the node).

    ``fraction_target`` (low oxygen) is not additive: with ``fraction_strength`` s the caller blends
    ``natural - s * (natural - target)`` (A1). ``fraction_target`` is None when absent.
    """

    fraction_target: float | None = None
    fraction_strength: float = 0.0

    def blend_fraction(self, natural: float) -> float:
        if self.fraction_target is None:
            return natural
        return natural - self.fraction_strength * (natural - self.fraction_target)


@dataclass
class ActiveScenario:
    zone: str
    scenario: str
    started: datetime
    ramp_s: float
    # recovery only: frozen per-key offsets and fraction at the moment recovery began
    frozen: dict[str, float] = field(default_factory=dict)
    frozen_fraction: tuple[float, float] | None = None  # (target, magnitude)


def is_night(at: datetime) -> bool:
    return _diurnal(at, _DO_PEAK_HOUR_MYT) < 0


def reach_factor(
    node_type: str, e_m: float, s_m: float, zone_bounds: tuple[float, float, float, float]
) -> float:
    e0, s0, e1, s1 = zone_bounds
    d = math.hypot(max(e0 - e_m, 0.0, e_m - e1), max(s0 - s_m, 0.0, s_m - s1))
    if d == 0:
        return 1.0
    return max(0.0, 1 - d / REACH_M[node_type])


def grid_zone_bounds() -> dict[str, tuple[float, float, float, float]]:
    """Label -> (e0, s0, e1, s1) for the 5x5 grid of 100 m zones (letter = east column, digit = south row)."""
    n = int(SITE_SIZE_M / ZONE_SIZE_M)
    return {
        f"{chr(65 + c)}{r + 1}": (
            c * ZONE_SIZE_M,
            r * ZONE_SIZE_M,
            (c + 1) * ZONE_SIZE_M,
            (r + 1) * ZONE_SIZE_M,
        )
        for c in range(n)
        for r in range(n)
    }


class ScenarioBook:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._active: dict[str, ActiveScenario] = {}

    def active(self) -> dict[str, ActiveScenario]:
        return dict(self._active)

    def clear(self, zone_label: str) -> None:
        self._active.pop(zone_label, None)

    def apply(self, zone_label: str, scenario: str, ramp_s: float | None = None) -> None:
        """Start ``scenario`` in a zone (replacing any active one; the new ramp starts from zero)."""
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario}")
        now = self.clock.now()
        if scenario == "healthy":
            self.clear(zone_label)
            return
        if scenario == "recovery":
            cur = self._active.get(zone_label)
            if cur is None:
                return  # nothing to recover from
            frozen, frac = self._raw_current(cur, now)
            self._active[zone_label] = ActiveScenario(
                zone_label, "recovery", now, RECOVERY_TAU_S, frozen, frac
            )
            return
        tau = DEFAULT_RAMP_S if ramp_s is None else float(ramp_s)
        self._active[zone_label] = ActiveScenario(zone_label, scenario, now, tau)

    # -- evaluation -------------------------------------------------------------------------
    @staticmethod
    def _mag(elapsed_s: float, tau: float) -> float:
        if elapsed_s <= 0:
            return 0.0
        return 1.0 if tau <= 0 else 1 - math.exp(-elapsed_s / tau)

    def _raw_current(
        self, a: ActiveScenario, at: datetime
    ) -> tuple[dict[str, float], tuple[float, float] | None]:
        """Per-key offsets (reach 1) and (fraction target, magnitude) of one zone at ``at``."""
        el = (at - a.started).total_seconds()
        if a.scenario == "recovery":
            k = math.exp(-max(el, 0.0) / a.ramp_s)
            frac = (a.frozen_fraction[0], a.frozen_fraction[1] * k) if a.frozen_fraction else None
            return {key: v * k for key, v in a.frozen.items()}, frac
        d = SCENARIOS[a.scenario]
        offs = dict(d.offsets)
        night = is_night(at)
        if d.night_offsets and night:
            for k, v in d.night_offsets.items():
                offs[k] = offs.get(k, 0.0) + v
        out = {k: v * self._mag(el, d.key_tau_s.get(k, a.ramp_s)) for k, v in offs.items()}
        frac = None
        if d.fraction_day is not None:
            frac = (d.fraction_night if night else d.fraction_day, self._mag(el, a.ramp_s))
        return out, frac

    def offsets_for(
        self,
        node_type: str,
        e_m: float,
        s_m: float,
        at: datetime,
        registry_zone_bounds: dict[str, tuple[float, float, float, float]],
    ) -> Offsets:
        keys = NODE_KEYS[node_type]
        total = Offsets()
        best = 0.0
        for label, a in self._active.items():
            bounds = registry_zone_bounds.get(label)
            if bounds is None:
                continue
            f = reach_factor(node_type, e_m, s_m, bounds)
            if f <= 0:
                continue
            raw, frac = self._raw_current(a, at)
            for k, v in raw.items():
                if k in keys:
                    total[k] = total.get(k, 0.0) + v * f
            # Fraction blending applies to the water-quality DO only; the strongest zone wins.
            if frac is not None and node_type == "water_quality" and frac[1] * f > best:
                best = frac[1] * f
                total.fraction_target = frac[0]
                total.fraction_strength = best
        return total
