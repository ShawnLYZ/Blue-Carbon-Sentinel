"""Typed settings (addendum E).

Precedence, lowest to highest: defaults in code, ``config/*.yaml``, environment and ``.env``
(prefix ``BCS_``, nested keys joined by ``__``), then explicit overrides (command-line flags).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Settings field -> file under config/. The site file carries the site ID (addendum E2).
CONFIG_FILES: dict[str, str] = {
    "site": "site.ksl.yaml",
    "thresholds": "thresholds.yaml",
    "bands": "bands.yaml",
    "risk": "risk.yaml",
    "forecast": "forecast.yaml",
    "carbon": "carbon.yaml",
    "ai": "ai.yaml",
    "demo_time": "demo_time.yaml",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---- site -------------------------------------------------------------------------------------
class Point2(_Model):
    lat: float
    lng: float


class PlannedSiteConfig(_Model):
    id: str
    name: str
    region: str
    centre: Point2
    status: Literal["planned"] = "planned"
    rationale: str


class SiteConfig(_Model):
    id: str
    name: str
    region: str
    anchor_nw: Point2
    size_m: float
    bearing_deg: float = 0.0
    scale_label: str
    zone_grid: dict[str, Any] = Field(default_factory=dict)
    selection_note: str | None = None
    planned_sites: list[PlannedSiteConfig] = Field(default_factory=list)


# ---- thresholds -------------------------------------------------------------------------------
class FlagThresholds(_Model):
    canopy_loss_pp: float
    dieback_pct: float
    index_drop: float
    discolouration: float
    new_growth_pct: float
    new_growth_canopy_pp: float


class MotionThresholds(_Model):
    motion_threshold: float
    change_threshold: float
    stable_s: float
    diff_size_px: int = 128
    diff_blur_sigma: float = 1.0


class QualityLimits(_Model):
    sharpness_min: float
    brightness_min: float
    brightness_max: float
    clipped_max_pct: float


class CanopyRule(_Model):
    exg_default: float
    s_min: float


class WaterDarkRule(_Model):
    v_max: float
    s_max: float


class WaterBlueRule(_Model):
    h_min: float
    h_max: float
    s_min: float


class WaterRule(_Model):
    dark: WaterDarkRule
    blue: WaterBlueRule
    texture_max: float
    texture_window_px: int


class MudBrownRule(_Model):
    h_min: float
    h_max: float
    s_min: float
    s_max: float
    v_min: float
    v_max: float


class MudGreyRule(_Model):
    s_max: float
    v_min: float
    v_max: float


class MudRule(_Model):
    brown: MudBrownRule
    grey: MudGreyRule


class DiebackRule(_Model):
    hue_min: float
    hue_max: float
    vari_margin: float


class NewGrowthRule(_Model):
    mask_dilate_px: int
    component_min_px: int
    component_max_px: int


class Classification(_Model):
    """Addendum N11 classification and zone-metric parameters (OpenCV HSV scales)."""

    precedence: list[Literal["canopy", "water", "mud", "other"]]
    canopy: CanopyRule
    water: WaterRule
    mud: MudRule
    dieback: DiebackRule
    new_growth: NewGrowthRule


class Thresholds(_Model):
    flags: FlagThresholds
    motion: MotionThresholds
    quality: QualityLimits
    classification: Classification


# ---- bands ------------------------------------------------------------------------------------
class Band(_Model):
    unit: str | None = None
    breakpoints: list[tuple[float, float]]  # (value, stress)
    citation: str | None = None
    source_url: str | None = None
    evidence: str | None = None  # direct | context | judgement


class Bands(_Model):
    status: str = "provisional"
    parameters: dict[str, Band]


# ---- risk -------------------------------------------------------------------------------------
class Risk(_Model):
    weights: dict[str, float]
    multiplier_bounds: tuple[float, float]
    class_limits: dict[str, float]
    vegetation: dict[str, float] = Field(default_factory=dict)
    robust_window: dict[str, float] = Field(default_factory=dict)
    early_warning: dict[str, float] = Field(default_factory=dict)
    confidence: dict[str, Any] = Field(default_factory=dict)


# ---- forecast / carbon / ai -------------------------------------------------------------------
class Forecast(_Model):
    horizon: dict[str, int] = Field(default_factory=dict)
    bounds: dict[str, tuple[float, float]]
    rules_defaults: dict[str, dict[str, float]] = Field(default_factory=dict)
    intervention_effects: dict[str, Any] = Field(default_factory=dict)
    cohorts: dict[str, Any] = Field(default_factory=dict)


class CitedNumber(_Model):
    """A carbon constant with its provenance (M6 Task 1)."""

    value: float
    unit: str
    citation: str
    source_url: str


class CohortRates(_Model):
    """Planted-cohort sequestration by age band, cited (``value`` is the band list)."""

    value: list[dict[str, float]]
    unit: str
    citation: str
    source_url: str


class Carbon(_Model):
    ecosystem_density_mg_c_ha: CitedNumber
    biomass_density_mg_c_ha: CitedNumber
    co2e_per_c: CitedNumber
    cohort_rates: CohortRates
    buffer_pct: CitedNumber
    zone_area_ha: float = 1.0
    uncertainty: dict[str, float] = Field(default_factory=dict)
    crediting_period: dict[str, int] = Field(default_factory=dict)
    methodology_label: str | None = None


class AI(_Model):
    tiers: dict[str, dict[str, Any]]
    models: dict[str, str]
    chains: dict[str, list[str]]
    timeouts_s: dict[str, float] = Field(default_factory=dict)
    key_rotation: dict[str, float] = Field(default_factory=dict)
    rate: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.2
    image: dict[str, Any] = Field(default_factory=dict)


# ---- demo time --------------------------------------------------------------------------------
class DemoTimeValues(BaseModel):
    baseline_interval_s: float
    investigation_interval_s: float
    task_duration_s: float
    task_cooldown_s: float
    verified_sensor_window_s: float
    capture_interval_s: float


class DemoTime(_Model):
    on: DemoTimeValues
    off: DemoTimeValues
    common: dict[str, float] = Field(default_factory=dict)


# ---- YAML settings source ---------------------------------------------------------------------
class _YamlConfigSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], config_dir: Path) -> None:
        super().__init__(settings_cls)
        self._dir = config_dir

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:  # pragma: no cover
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, filename in CONFIG_FILES.items():
            path = self._dir / filename
            if path.is_file():
                out[name] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return out


# ---- Settings ---------------------------------------------------------------------------------
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BCS_",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
        env_file_encoding="utf-8",
    )

    site: SiteConfig
    thresholds: Thresholds
    bands: Bands
    risk: Risk
    forecast: Forecast
    carbon: Carbon
    ai: AI
    demo_time: DemoTime

    # Secrets (E1). All optional so the Ground Station starts with a partial .env;
    # preflight reports each missing value.
    gemini_api_key_1: SecretStr | None = None
    gemini_api_key_2: SecretStr | None = None
    gemini_api_key_3: SecretStr | None = None
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_db_password: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_DB_PASSWORD", "supabase_db_password")
    )
    supabase_access_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_ACCESS_TOKEN", "supabase_access_token")
    )
    nvidia_api_key: SecretStr | None = None
    mapbox_public_token: SecretStr | None = None  # public: the only key the browser sees (masked in logs)
    broker_admin_user: str = "admin"
    broker_admin_password: SecretStr | None = None
    gs_mqtt_password: SecretStr | None = None
    sim_shared_token: SecretStr | None = None
    camera_token: SecretStr | None = None
    camera_ota_password: SecretStr | None = None

    # Plain options (E1)
    camera_host: str = "sentinel-cam.local"
    camera_ip: str | None = None  # explicit camera address; wins over mDNS and zeroconf discovery
    demo_time_scale: Literal["on", "off"] = "on"
    log_level: str = "INFO"
    live_max_fps: int = 10  # default per-client cap on /ws/live (addendum J1)
    broker_port: int = 1883
    auto_commission: bool = True  # with no nodes registered, commission once at start (§12); tests turn it off
    sim_port: int = 8701  # the simulator's port; the browser is told where to find it (PublicConfig.sim_url)
    data_dir: Path | None = None  # state root; the store lives in <data_dir>/var (default: the repository)
    site_nw_lat: float | None = None
    site_nw_lng: float | None = None
    model_gemini_primary: str | None = None
    model_gemini_secondary: str | None = None
    model_gemini_tree: str | None = None
    model_ollama: str | None = None
    model_image: str | None = None

    @model_validator(mode="after")
    def _apply_overrides(self) -> Settings:
        if self.site_nw_lat is not None:
            self.site.anchor_nw.lat = self.site_nw_lat
        if self.site_nw_lng is not None:
            self.site.anchor_nw.lng = self.site_nw_lng
        for env_field, slot in (
            ("model_gemini_primary", "gemini_primary"),
            ("model_gemini_secondary", "gemini_secondary"),
            ("model_gemini_tree", "robotics_er"),
            ("model_ollama", "gemma_local"),
            ("model_image", "image"),
        ):
            value = getattr(self, env_field)
            if value:
                self.ai.models[slot] = value
        return self

    def secret_values_except_mapbox(self) -> list[str]:
        """Every non-empty secret value except the Mapbox public token (for leak tests)."""
        out: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name != "mapbox_public_token" and isinstance(value, SecretStr) and value.get_secret_value():
                out.append(value.get_secret_value())
        return out

    def demo_values(self) -> DemoTimeValues:
        return self.demo_time.on if self.demo_time_scale == "on" else self.demo_time.off


def load_settings(repo_root: Path, env_file: Path | None = None, **overrides: Any) -> Settings:
    """Load settings for the repository at ``repo_root``.

    ``env_file`` is the dotenv file to read (``None`` reads none, which keeps tests independent
    of the real ``.env``). ``overrides`` are explicit values and win over everything else.
    """
    config_dir = Path(repo_root) / "config"

    class _Loaded(Settings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                _YamlConfigSource(settings_cls, config_dir),
            )

    return _Loaded(_env_file=env_file, **overrides)
