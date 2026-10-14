"""Simulated node identity and the readings pipeline.

Pipeline per sample: natural (Environment) -> scenario offsets -> overrides -> clamp to G4 -> noise.
Low oxygen blends its saturation-fraction target into the DO saturation fraction (A1), and DO is then
computed from saturation(temperature, salinity incl. offsets) x fraction, so heat stress lowers DO
through solubility; additive DO offsets (e.g. sediment runoff) are applied after.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ..environment import RANGES, Environment, apply_noise
from ..overrides import Overrides
from ..oxygen import do_saturation_mg_l
from ..scenarios import ScenarioBook
from .battery import Battery

FW_VERSION = "sim-1.0.0"


@dataclass
class SimNode:
    node_id: str
    node_type: str
    e_m: float
    s_m: float
    elevation_cm: float
    seed: int = 0
    site_id: str = "SIT"
    boot_id: str = ""
    seq: int = 0  # next telemetry sequence number
    event_seq: int = 0  # next event sequence number (own counter per boot, G3 dedupe key)
    boot_at: datetime | None = None
    battery: Battery = field(default_factory=Battery)
    rssi_dbm: float = -70.0
    rng: np.random.Generator = field(init=False)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.boot()

    def boot(self, at: datetime | None = None) -> str:
        """New random boot_id; telemetry and event sequence numbers back to 0."""
        self.boot_id = secrets.token_hex(6)
        self.seq = 0
        self.event_seq = 0
        self.boot_at = at
        return self.boot_id

    def health(self, now: datetime) -> dict:
        up = (now - self.boot_at).total_seconds() if self.boot_at else 0.0
        return {
            "battery_pct": round(self.battery.pct, 2),
            "rssi_dbm": self.rssi_dbm,
            "uptime_s": max(up, 0.0),
            "fw_version": FW_VERSION,
        }


def produce_readings(
    node: SimNode,
    env: Environment,
    book: ScenarioBook,
    overrides: Overrides,
    zone_bounds: dict[str, tuple[float, float, float, float]],
    at: datetime,
    rng: np.random.Generator | None,
    *,
    noise_scale: float | None = None,
) -> dict[str, float]:
    """``noise_scale`` None: the environment's noise setting; 0 gives the noise-free value (no rng draw)."""
    nat = env.natural(node.node_type, node.e_m, node.s_m, node.elevation_cm, at, node.node_id)
    offs = book.offsets_for(node.node_type, node.e_m, node.s_m, at, zone_bounds)
    vals = dict(nat)
    if node.node_type == "water_quality":
        sat_nat = do_saturation_mg_l(nat["temp_c"], nat["salinity_psu"])
        frac_nat = nat["do_mg_l"] / sat_nat if sat_nat else 0.0
        for k in ("salinity_psu", "turbidity_ntu", "temp_c", "ph"):
            vals[k] = nat[k] + offs.get(k, 0.0)
        frac = offs.blend_fraction(frac_nat)
        vals["do_mg_l"] = do_saturation_mg_l(vals["temp_c"], vals["salinity_psu"]) * frac + offs.get(
            "do_mg_l", 0.0
        )
    else:
        for k in nat:
            vals[k] = nat[k] + offs.get(k, 0.0)
    vals = overrides.apply(node.node_id, vals, at)
    vals = {k: min(max(v, RANGES[k][0]), RANGES[k][1]) for k, v in vals.items()}
    scale = (1.0 if env.noise_enabled else 0.0) if noise_scale is None else noise_scale
    return apply_noise(vals, rng, env.cfg, scale)  # type: ignore[arg-type]  # rng unused at scale 0
