"""Site-wide environment: tide, diurnal cycles and noise-free natural readings (G4 keys).

Per-node first-order state (porewater, soil moisture) is cached by ``(node_type, e_m, s_m)`` unless
the caller passes ``node_id``, which then takes precedence. State advances only forward in time.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np

from .clock import Clock
from .config import SimConfig
from .oxygen import do_saturation_mg_l

MYT = timedelta(hours=8)
# G4: key -> (min, max, resolution)
RANGES: dict[str, tuple[float, float, float]] = {
    "salinity_psu": (0, 60, 0.1),
    "turbidity_ntu": (0, 4000, 0.1),
    "do_mg_l": (0, 20, 0.01),
    "temp_c": (0, 45, 0.01),
    "ph": (0, 14, 0.01),
    "porewater_salinity_psu": (0, 120, 0.1),
    "soil_moisture_pct": (0, 100, 0.1),
    "water_level_cm": (-500, 500, 1),
}
_SUBSTEP_S = 60.0
_MAX_SUBSTEPS = 720


def _myt_hour(at: datetime) -> float:
    local = at.astimezone(UTC) + MYT
    return local.hour + local.minute / 60 + (local.second + local.microsecond / 1e6) / 3600


def _diurnal(at: datetime, peak_hour: float) -> float:
    return math.cos(2 * math.pi * (_myt_hour(at) - peak_hour) / 24)


class Environment:
    def __init__(self, cfg: SimConfig, seed: int, clock: Clock) -> None:
        self.cfg = cfg
        self.clock = clock
        self._ff = 1.0
        self._anchor_t = clock.now()
        # Seeded tidal phase (seconds of model time into the cycle at the anchor).
        self._anchor_model_s = float(np.random.default_rng(seed).uniform(0, cfg.tide.period_h * 3600))
        self._tide_on = True
        self._diurnal_on = True
        self._noise_on = True
        self._state: dict[tuple, tuple[float, float, datetime]] = {}  # key -> (porewater, moisture, at)

    # -- controls ---------------------------------------------------------------------------
    def set_fast_forward(self, f: float) -> None:
        """Re-anchor so the tide phase is continuous at the current clock time."""
        now = self.clock.now()
        self._anchor_model_s = self._model_s(now)
        self._anchor_t = now
        self._ff = float(f)

    def set_nature(
        self, tide: bool | None = None, diurnal: bool | None = None, noise: bool | None = None
    ) -> None:
        if tide is not None:
            self._tide_on = tide
        if diurnal is not None:
            self._diurnal_on = diurnal
        if noise is not None:
            self._noise_on = noise

    def set_tide(
        self, mean_cm: float | None = None, amplitude_cm: float | None = None, spring_neap: bool | None = None
    ) -> None:
        """Change the tide model; the phase is kept (model time is unchanged)."""
        upd = {
            k: v
            for k, v in (("mean_cm", mean_cm), ("amplitude_cm", amplitude_cm), ("spring_neap", spring_neap))
            if v is not None
        }
        if upd:
            self.cfg = self.cfg.model_copy(update={"tide": self.cfg.tide.model_copy(update=upd)})

    @property
    def noise_enabled(self) -> bool:
        return self._noise_on

    @property
    def tide_enabled(self) -> bool:
        return self._tide_on

    @property
    def diurnal_enabled(self) -> bool:
        return self._diurnal_on

    @property
    def fast_forward(self) -> float:
        return self._ff

    def nature(self) -> dict:
        """The K1 ``nature`` view."""
        t = self.cfg.tide
        return {
            "tide": {
                "enabled": self._tide_on,
                "mean_cm": t.mean_cm,
                "amplitude_cm": t.amplitude_cm,
                "spring_neap": t.spring_neap,
            },
            "diurnal": self._diurnal_on,
            "noise": self._noise_on,
        }

    # -- tide -------------------------------------------------------------------------------
    def _model_s(self, at: datetime) -> float:
        return self._anchor_model_s + (at - self._anchor_t).total_seconds() * self._ff

    def level_cm(self, at: datetime) -> float:
        t = self.cfg.tide
        if not self._tide_on:
            return t.mean_cm
        ms = self._model_s(at)
        amp = t.amplitude_cm
        if t.spring_neap:
            amp *= 1 + t.spring_neap_depth * math.sin(2 * math.pi * ms / (t.spring_neap_period_d * 86400))
        return t.mean_cm + amp * math.sin(2 * math.pi * ms / (t.period_h * 3600))

    def _level_rate_cm_min(self, at: datetime) -> float:
        h = timedelta(seconds=30)
        return self.level_cm(at + h) - self.level_cm(at - h)  # over 60 s == per minute

    # -- natural readings -------------------------------------------------------------------
    def _d(self, at: datetime, peak: float) -> float:
        return _diurnal(at, peak) if self._diurnal_on else 0.0

    def natural(
        self,
        node_type: str,
        e_m: float,
        s_m: float,
        elevation_cm: float,
        at: datetime,
        node_id: str | None = None,
    ) -> dict[str, float]:
        if node_type == "tide_gauge":
            return {"water_level_cm": self.level_cm(at)}
        if node_type == "water_quality":
            return self._water(at)
        if node_type == "soil_probe":
            key = ("id", node_id) if node_id is not None else (node_type, e_m, s_m)
            pw, sm = self._soil(key, elevation_cm, at)
            return {"porewater_salinity_psu": pw, "soil_moisture_pct": sm}
        raise ValueError(f"unknown node type: {node_type}")

    def _water(self, at: datetime) -> dict[str, float]:
        w, t = self.cfg.water, self.cfg.tide
        norm = (self.level_cm(at) - t.mean_cm) / t.amplitude_cm if t.amplitude_cm else 0.0
        sal = w.base_salinity_psu + w.salinity_tide_gain_psu * norm
        temp = w.temp_mean_c + w.temp_amplitude_c * self._d(at, w.temp_peak_hour_myt)
        frac = w.do_saturation_fraction + w.do_saturation_amplitude * self._d(at, w.do_peak_hour_myt)
        return {
            "salinity_psu": sal,
            "turbidity_ntu": w.turbidity_base_ntu
            + w.turbidity_resuspension_ntu_per_cm_min * abs(self._level_rate_cm_min(at)),
            "do_mg_l": do_saturation_mg_l(temp, sal) * frac,
            "temp_c": temp,
            "ph": w.ph_mean + w.ph_amplitude * self._d(at, w.ph_peak_hour_myt),
        }

    def _soil(self, key: tuple, elevation_cm: float, at: datetime) -> tuple[float, float]:
        s = self.cfg.soil
        prev = self._state.get(key)
        inundated = self.level_cm(at) > elevation_cm
        if prev is None:
            pw = s.porewater_target_psu
            sm = s.moisture_inundated_pct if inundated else s.moisture_dry_pct
            self._state[key] = (pw, sm, at)
            return pw, sm
        pw, sm, last = prev
        remaining = (at - last).total_seconds()
        if remaining <= 0:
            return pw, sm  # never integrate backwards
        step = max(_SUBSTEP_S, remaining / _MAX_SUBSTEPS)
        t = last
        while remaining > 1e-9:
            dt = min(step, remaining)
            t = t + timedelta(seconds=dt)
            remaining -= dt
            pw += (s.porewater_target_psu - pw) * (1 - math.exp(-dt / s.porewater_tau_s))
            if self.level_cm(t) > elevation_cm:
                sm = s.moisture_inundated_pct
            else:
                sm += (s.moisture_dry_pct - sm) * (1 - math.exp(-dt / s.moisture_dry_tau_s))
        self._state[key] = (pw, sm, at)
        return pw, sm


def apply_noise(
    values: dict[str, float], rng: np.random.Generator, cfg: SimConfig, scale: float = 1.0
) -> dict[str, float]:
    """Gaussian noise (sigma from ``cfg.noise_sigma`` x ``scale``), clamp to G4 range, quantise to the resolution."""
    sigmas = cfg.noise_sigma.model_dump()
    out: dict[str, float] = {}
    for k, v in values.items():
        lo, hi, res = RANGES[k]
        x = v + (float(rng.normal(0.0, sigmas[k] * scale)) if scale else 0.0)
        x = min(max(x, lo), hi)
        out[k] = round(round(x / res) * res, 2)
    return out
