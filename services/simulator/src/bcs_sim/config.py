"""Simulator settings (addendum E).

Same sources and precedence as the Ground Station loader, kept independent of ``bcs_gs``:
defaults, then the repo-root ``.env``, then ``BCS_*`` environment variables, then explicit overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
CORS_ORIGINS = [  # addendum K3
    "http://127.0.0.1:8700",
    "http://localhost:8700",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]


class SimSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BCS_",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
        env_file_encoding="utf-8",
    )

    demo_time_scale: Literal["on", "off"] = "on"
    log_level: str = "INFO"
    broker_port: int = 1883
    sim_shared_token: SecretStr | None = None
    gs_url: str = "http://127.0.0.1:8700"
    site_id: str = "KSL"  # default when the Ground Station registry names no site
    broker_host: str = "127.0.0.1"
    cors_origins: list[str] = list(CORS_ORIGINS)


def load_sim_settings(env_file: Path | None = None, **overrides: Any) -> SimSettings:
    """``env_file=None`` reads no dotenv file (keeps tests independent of the real ``.env``).

    Precedence: overrides, environment, dotenv, defaults (as in the Ground Station loader).
    """
    return SimSettings(_env_file=env_file, **overrides)


# --- environment model config (config/simulator.yaml) ---

SIM_CONFIG_PATH = REPO_ROOT / "config" / "simulator.yaml"


class TideCfg(BaseModel):
    mean_cm: float = 0.0
    amplitude_cm: float = 150.0
    period_h: float = 12.42
    spring_neap: bool = False
    spring_neap_period_d: float = 14.77
    spring_neap_depth: float = 0.3


class WaterCfg(BaseModel):
    base_salinity_psu: float = 28.0
    salinity_tide_gain_psu: float = 3.0
    temp_mean_c: float = 29.0
    temp_amplitude_c: float = 2.0
    temp_peak_hour_myt: float = 15.0
    do_saturation_fraction: float = 0.85
    do_saturation_amplitude: float = 0.15
    do_peak_hour_myt: float = 14.0
    ph_mean: float = 7.8
    ph_amplitude: float = 0.1
    ph_peak_hour_myt: float = 14.0
    turbidity_base_ntu: float = 12.0
    turbidity_resuspension_ntu_per_cm_min: float = 6.0


class SoilCfg(BaseModel):
    porewater_target_psu: float = 32.0
    porewater_tau_s: float = 3600.0
    moisture_inundated_pct: float = 55.0
    moisture_dry_pct: float = 35.0
    moisture_dry_tau_s: float = 1800.0


class NoiseSigmaCfg(BaseModel):
    salinity_psu: float = 0.05
    turbidity_ntu: float = 1.0
    do_mg_l: float = 0.05
    temp_c: float = 0.02
    ph: float = 0.01
    porewater_salinity_psu: float = 0.1
    soil_moisture_pct: float = 0.3
    water_level_cm: float = 1.0


class SimConfig(BaseModel):
    tide: TideCfg = TideCfg()
    water: WaterCfg = WaterCfg()
    soil: SoilCfg = SoilCfg()
    noise_sigma: NoiseSigmaCfg = NoiseSigmaCfg()


def load_sim_config(path: Path | None = None) -> SimConfig:
    import yaml

    data = yaml.safe_load((path or SIM_CONFIG_PATH).read_text(encoding="utf-8")) or {}
    return SimConfig.model_validate(data)
