"""Response and request models of the Ground Station HTTP API (addendum I3).

These Pydantic classes are the source of truth; the TypeScript types are generated from them.
Names match the TypeScript sketch in the addendum.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bcs_gs.core.config import DemoTimeValues as DemoTimeValues  # noqa: PLC0414
from bcs_gs.core.config import Point2 as Point2  # noqa: PLC0414
from bcs_gs.site.registry import PlannedSite as PlannedSite  # noqa: PLC0414
from bcs_gs.site.registry import Site as Site  # noqa: PLC0414
from bcs_gs.site.registry import Zone as Zone  # noqa: PLC0414

Iso = str
ZoneId = str
NodeId = str
RiskClass = Literal["low", "medium", "high", "critical"]
Tier = Literal["robotics_er", "gemini_primary", "gemini_secondary", "gemma_local", "rules"]
Json = dict[str, Any]


class _M(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), populate_by_name=True)


class Band(_M):
    low: float
    central: float
    high: float


class SourceChip(_M):
    tier: Tier
    model: str | None = None
    cached: bool
    ai_call_id: str | None = None


# ---- system -----------------------------------------------------------------------------------
class PublicConfig(_M):
    version: str
    mapbox_token: str
    sim_url: str
    demo_time_scale: bool
    demo_time: DemoTimeValues
    site: Site


class BandView(_M):
    unit: str | None = None
    breakpoints: list[tuple[float, float]]  # (value, stress 0-1), piecewise-linear (addendum N1)
    evidence: str | None = None


class BandsView(_M):
    status: str
    class_limits: dict[str, float]  # config/risk.yaml: low/medium/high upper limits on the 0-100 scale
    parameters: dict[str, BandView]


ComponentId = Literal[
    "camera", "ground_station", "broker", "cloud", "sync", "ai", "image_service", "gpu", "ollama", "simulator"
]


class ComponentStatus(_M):
    id: ComponentId
    status: Literal["ok", "warn", "fail", "off"]
    summary: str
    since: Iso
    details: Json = Field(default_factory=dict)


class SyncState(_M):
    state: Literal["online", "buffering", "offline"]
    queue: int
    media_queue: int
    lag_s: float | None = None
    last_success_at: Iso | None = None


class CloudUsage(_M):
    db_bytes: int | None = None
    storage_bytes: int
    storage_budget_bytes: int
    paused: bool | None = None
    dashboard_url: str


class DepthStatus(_M):
    provider: str | None = None
    mode: Literal["depth", "fallback", "off"]
    fps: float


class SystemStatus(_M):
    version: str
    started_at: Iso
    now: Iso
    demo_time_scale: bool
    components: list[ComponentStatus]
    sync: SyncState
    cloud: CloudUsage
    depth: DepthStatus


PreflightId = Literal[
    "camera", "broker", "broker_port", "supabase", "cloud_usage", "gemini_keys", "nvidia_key",
    "mapbox_token", "depth_model", "ollama", "disk",
]  # fmt: skip


class PreflightCheck(_M):
    id: PreflightId
    label: str
    status: Literal["pass", "warn", "fail"]
    detail: str
    fix_hint: str | None = None


class PreflightReport(_M):
    ran_at: Iso
    checks: list[PreflightCheck]


class CameraSettings(_M):
    frame_size: Literal["VGA", "SVGA", "XGA", "HD", "SXGA"] = "SVGA"
    jpeg_quality: int = Field(12, ge=4, le=63)
    vflip: bool = False
    hmirror: bool = False
    flash: bool = False
    gain_ceiling: int = Field(2, ge=0, le=6)


class CameraSettingsPatch(_M):
    frame_size: Literal["VGA", "SVGA", "XGA", "HD", "SXGA"] | None = None
    jpeg_quality: int | None = Field(None, ge=4, le=63)
    vflip: bool | None = None
    hmirror: bool | None = None
    flash: bool | None = None
    gain_ceiling: int | None = Field(None, ge=0, le=6)


class Settings(_M):
    vertical_exaggeration: float = Field(1.0, ge=0.25, le=3)
    live_max_fps: int = Field(10, ge=1, le=30)
    camera_desired: CameraSettings = Field(default_factory=CameraSettings)


class SettingsPatch(_M):
    vertical_exaggeration: float | None = Field(None, ge=0.25, le=3)
    live_max_fps: int | None = Field(None, ge=1, le=30)
    camera_desired: CameraSettingsPatch | None = None


class CameraStatus(_M):
    online: bool
    since: Iso  # ruling R2: never null (last frame, else the link's start time)
    host: str
    resolved_ip: str | None = None
    last_frame_at: Iso | None = None
    fps_in: float
    locked: bool
    desired: CameraSettings
    device: Json | None = None


class LockRequest(_M):
    locked: bool


class Calibration(_M):
    id: str
    created_at: Iso
    mode: Literal["default", "four_corner"]
    frame_w: int
    frame_h: int
    corners_px: list[tuple[float, float]] | None = None
    north_edge: int | None = None
    homography: list[float]
    active: bool


class FourCornerRequest(_M):
    corners_px: list[tuple[float, float]]
    north_edge: int


class CalibrationRecommend(_M):
    reset_baseline: bool = True
    recommission: bool = True


class CalibrationResult(_M):
    calibration: Calibration
    recommend: CalibrationRecommend


class BaselineRequest(_M):
    capture_id: str | None = None


# ---- zones and captures -----------------------------------------------------------------------
class ZoneFlag(_M):
    kind: Literal["canopy_loss", "dieback", "index_drop", "discolouration", "new_growth"]
    value: float
    threshold: float


class ZoneMetrics(_M):
    zone_id: ZoneId
    canopy_pct: float
    water_pct: float
    mud_pct: float
    other_pct: float
    vari_mean: float | None = None
    vari_p10: float | None = None
    vari_p90: float | None = None
    canopy_loss_pp: float | None = None
    vari_drop: float | None = None
    dieback_pct: float
    new_growth_pct: float
    discolouration: float | None = None
    flags: list[ZoneFlag] = Field(default_factory=list)


class ZoneMetricsAt(ZoneMetrics):
    taken_at: Iso


class Confidence(_M):
    camera: float
    sensor: float
    prediction: float
    overall: float


class RootCause(_M):
    driver: str
    rank: int
    why: str


class VisionObservationView(_M):
    kind: Literal["dieback", "clearing", "new_growth", "discolouration", "none"]
    confidence: float
    text: str


class Assessment(_M):
    id: str
    zone_id: ZoneId
    at: Iso
    capture_id: str | None = None
    stressors: dict[str, float | None]
    multipliers: dict[str, float]
    weights: dict[str, float]
    risk_score: float
    risk_class: RiskClass
    confidence: Confidence
    early_warning: bool
    narrative: str
    root_causes: list[RootCause]
    actions: list[str]
    source: SourceChip
    # The zone's latest VisionAnalyst observations (empty until a camera analysis ran) and, when it answered
    # on a different tier than `source`, its own chip.
    observations: list[VisionObservationView] = Field(default_factory=list)
    observations_source: SourceChip | None = None


class ZoneCoverage(_M):
    water: list[NodeId] = Field(default_factory=list)
    soil: list[NodeId] = Field(default_factory=list)


class ZoneSummary(_M):
    zone: Zone
    metrics: ZoneMetrics | None = None
    assessment: Assessment | None = None
    coverage: ZoneCoverage = Field(default_factory=ZoneCoverage)
    carbon_stock_tco2e: float | None = None
    tree_count: int | None = None


class CaptureQuality(_M):
    sharpness: float
    mean: float
    clipped_pct: float
    motion: bool
    exposure_locked: bool


class CaptureSummary(_M):
    id: str
    taken_at: Iso
    trigger: Literal["interval", "change", "manual"]
    evidence_grade: bool
    is_baseline: bool
    flagged: bool
    change_score: float | None = None
    quality: CaptureQuality
    thumb_url: str


class CaptureMediaUrls(_M):
    image: str
    height: str
    classes: str
    ndvi: str


class Capture(CaptureSummary):
    calibration_id: str
    imagery_source: str
    bands: list[str]
    media_urls: CaptureMediaUrls
    media_state: Literal["local", "uploaded", "pruned"]
    zone_metrics: list[ZoneMetrics]


class ComparisonZone(_M):
    zone_id: ZoneId
    canopy_pp: float
    vari: float | None = None
    dieback_pp: float
    new_growth_pp: float


class CaptureComparison(_M):
    a: str
    b: str
    change_url: str
    zones: list[ComparisonZone]


class TreePoint(_M):
    e_m: float
    s_m: float
    u_px: float
    v_px: float
    zone_id: ZoneId
    label: str


class TreePoints(_M):
    capture_id: str
    created_at: Iso
    source: SourceChip
    points: list[TreePoint]


# ---- nodes ------------------------------------------------------------------------------------
class EdgeFlag(_M):
    parameter: str
    kind: Literal["spike", "threshold", "stuck", "battery"]
    score: float


class Health(_M):
    battery_pct: float
    rssi_dbm: float
    uptime_s: float
    fw_version: str


class NodePosition(_M):
    e_m: float
    s_m: float
    lat: float
    lng: float
    u_px: float
    v_px: float


class NodeCovers(_M):
    water: list[ZoneId] = Field(default_factory=list)
    soil: list[ZoneId] = Field(default_factory=list)


class NodeLatest(_M):
    sampled_at: Iso
    readings: dict[str, float]
    health: Health
    flags: list[EdgeFlag]
    late: bool


class Node(_M):
    id: NodeId
    node_type: Literal["water_quality", "soil_probe", "tide_gauge"]
    source: Literal["simulated", "hardware"]
    position: NodePosition
    zone_id: ZoneId
    status: Literal["online", "offline", "unknown", "decommissioned"]
    mode: Literal["baseline", "investigation"] | None = None
    interval_s: float | None = None
    fw_version: str | None = None
    last_seen_at: Iso | None = None
    covers: NodeCovers
    latest: NodeLatest | None = None


class TelemetryPoint(_M):
    t: Iso
    mode: str
    late: bool
    readings: dict[str, float]


class NodeEvent(_M):
    id: str
    node_id: NodeId
    at: Iso
    origin: Literal["node", "ground_station"]
    kind: str
    parameter: str | None = None
    value: float | None = None
    score: float | None = None
    details: Json = Field(default_factory=dict)


class Command(_M):
    id: str
    node_id: NodeId
    type: str
    params: Json
    issued_at: Iso
    expires_at: Iso | None = None
    ack_status: str
    ack_at: Iso | None = None
    retries: int


class TaskTimelineEntry(_M):
    at: Iso
    event: str
    node_id: NodeId | None = None
    details: Json | None = None


class Task(_M):
    id: str
    created_at: Iso
    updated_at: Iso
    expires_at: Iso
    trigger: str
    zone_id: ZoneId | None = None
    node_ids: list[NodeId]
    duration_s: float
    status: str
    reason: str
    cancelled_by: str | None = None
    timeline: list[TaskTimelineEntry]
    commands: list[Command]


class NodeDetail(Node):
    recent_telemetry: list[TelemetryPoint]
    recent_events: list[NodeEvent]
    tasks: list[Task]


class TelemetrySeries(_M):
    node_id: NodeId
    from_: Iso = Field(alias="from")
    to: Iso
    downsampled: bool
    points: list[TelemetryPoint]


class ZoneDetail(ZoneSummary):
    last_capture_at: Iso | None = None
    metrics_history: list[ZoneMetricsAt]
    covering_nodes: list[Node]
    stressors: dict[str, float | None] | None = None


class CommissionedPosition(_M):
    node_id: NodeId
    node_type: str
    e_m: float
    s_m: float
    lat: float
    lng: float
    u_px: float
    v_px: float
    zone_id: ZoneId


class CommissioningCoverage(_M):
    covered: list[ZoneId]
    uncovered: list[ZoneId]


class CommissioningRun(_M):
    id: str
    created_at: Iso
    capture_id: str | None = None
    method: Literal["class_map", "fallback_spread"]
    confidence: Literal["high", "low"]
    reasons: list[str]
    positions: list[CommissionedPosition]
    coverage: CommissioningCoverage


class CoverageZone(_M):
    zone_id: ZoneId
    covered: bool
    water: list[NodeId]
    soil: list[NodeId]


class CoverageGap(_M):
    id: str
    zone_id: ZoneId
    node_type: Literal["water_quality", "soil_probe"]
    e_m: float
    s_m: float
    lat: float
    lng: float
    u_px: float
    v_px: float
    newly_covered: list[ZoneId]
    reason: str


class Coverage(_M):
    zones: list[CoverageZone]
    gaps: list[CoverageGap]


class SitePosition(_M):
    e_m: float
    s_m: float


class NodeCreate(_M):
    node_type: Literal["water_quality", "soil_probe", "tide_gauge"]
    source: Literal["simulated", "hardware"]
    position: SitePosition | None = None
    suggestion_id: str | None = None


class NodeCreated(_M):
    node: Node
    key: str | None = None


class NodeMove(_M):
    position: SitePosition
    confirm: bool = False


class Confirm(_M):
    confirm: bool = False


class KeyResult(_M):
    key: str | None = None
    reprovision: Literal["simulator"] | None = None


class TaskCreate(_M):
    zone_id: ZoneId | None = None
    node_ids: list[NodeId] | None = None
    duration_s: float | None = None
    reason: str | None = None


class TaskRelease(_M):
    node_id: NodeId


# ---- AI, history ------------------------------------------------------------------------------
class AICall(_M):
    id: str
    request_id: str
    at: Iso
    role: str
    tier: Tier
    provider: str
    model: str | None = None
    key_slot: int | None = None
    prompt_version: str
    status: str
    latency_ms: float | None = None
    cache_hit: bool
    valid: bool | None = None
    error: str | None = None
    fallback_from: str | None = None


class AIRoleStatus(_M):
    last_tier: Tier | None = None
    last_status: str | None = None
    last_at: Iso | None = None
    degraded: bool


class AIKeyStatus(_M):
    slot: int
    model: str
    state: Literal["ok", "cooldown"]
    cooldown_until: Iso | None = None
    tokens: int


class OllamaStatus(_M):
    model: str | None = None
    vision: bool
    reachable: bool


class AIStatus(_M):
    roles: dict[str, AIRoleStatus]
    keys: list[AIKeyStatus]
    daily: dict[str, int]
    ollama: OllamaStatus


class HistoryYear(_M):
    year: int
    canopy_pct: float
    vari_equiv: float
    note: str | None = None


class HistoryReal(_M):
    t: Iso
    zone_id: ZoneId
    canopy_pct: float
    vari_mean: float | None = None


class History(_M):
    generation_id: str | None = None
    label: str
    source: SourceChip | None = None
    series: dict[ZoneId, list[HistoryYear]]
    real: list[HistoryReal]


class RequestAccepted(_M):
    request_id: str


# ---- plans and forecasts ----------------------------------------------------------------------
class Intervention(_M):
    kind: Literal["plant_rhizophora", "plant_avicennia", "silt_fence", "reopen_channel", "stop_pollution"]
    sapling_count: int | None = None
    planted_area_ha: float | None = None


class ExpectedUplift(_M):
    canopy_pp_2035: float
    tco2e_2035: float


class PlanItem(_M):
    zone_id: ZoneId
    interventions: list[Intervention]
    priority: Literal[1, 2, 3, 4, 5]
    rationale: str
    expected_uplift: ExpectedUplift


class PlanVersion(_M):
    id: str
    plan_id: str
    version: int
    created_at: Iso
    source: Literal["ai", "operator", "mixed"]
    status: Literal["draft", "applied", "superseded"]
    items: list[PlanItem]
    applied_at: Iso | None = None
    capture_at_application_id: str | None = None
    forecast_id: str | None = None
    ai: SourceChip | None = None
    # Catalogue warnings from when this version was made (species switched, AI planting dropped).
    warnings: list[str] = Field(default_factory=list)


class PlanSummary(_M):
    plan_id: str
    version: int
    status: Literal["draft", "applied", "superseded"]
    source: Literal["ai", "operator", "mixed"]
    created_at: Iso
    applied_at: Iso | None = None
    zones: list[ZoneId]


class PlanProposeRequest(_M):
    zone_ids: list[ZoneId] | None = None


class PlanUpdateRequest(_M):
    items: list[PlanItem]


class PlanApplyRequest(_M):
    version: int | None = None


class PlanApplied(_M):
    plan: PlanVersion
    forecast_id: str


class ForecastRequest(_M):
    plan_id: str | None = None


class ForecastAccepted(_M):
    forecast_id: str


class YearPoint(_M):
    year: int
    canopy: Band
    health: Band
    land: Band
    risk_class: RiskClass
    stock_tco2e: Band
    seq_tco2e: Band
    additional_tco2e: Band


class ScenarioSeries(_M):
    site: list[YearPoint]
    zones: dict[ZoneId, list[YearPoint]]


class ForecastScenarios(_M):
    without: ScenarioSeries
    with_: ScenarioSeries = Field(alias="with")


class Forecast(_M):
    id: str
    created_at: Iso
    status: Literal["pending", "ready", "failed"]
    plan_id: str | None = None
    plan_version: int | None = None
    base_capture_id: str
    years: list[int]
    scenarios: ForecastScenarios
    parameter_sources: dict[ZoneId, SourceChip]
    confidence_prediction: float
    summary: Json = Field(default_factory=dict)  # ruling R7: elapsed_ms and run totals


class Illustration(_M):
    id: str
    forecast_id: str
    year: Literal[2030, 2035]
    scenario: Literal["without", "with"]
    status: Literal["pending", "ready", "failed", "skipped"]
    url: str | None = None
    provider: str
    model: str
    error: str | None = None


# ---- carbon and ledger ------------------------------------------------------------------------
class CarbonConstant(_M):
    name: str
    value: float
    unit: str
    citation: str


class CarbonSummary(_M):
    stock_tco2e: float
    per_zone: dict[ZoneId, float]
    projected_tco2e: float
    verified_tco2e: float
    constants: list[CarbonConstant]


class LedgerRecord(_M):
    chain_index: int
    record_id: str
    type: Literal["projected", "verified"]
    created_at: Iso
    quantity_tco2e: str
    content: Json
    canonical: str
    previous_hash: str
    hash: str
    link_ok: bool | None = None


class EvidenceChecklist(_M):
    plan_id: str
    satellite: bool
    sensor: bool
    ai: bool
    restoration: bool
    missing: list[str]


class CameraEligibility(_M):
    have: int
    need: Literal[3] = 3
    ok: bool


class SensorEligibility(_M):
    healthy_s: float
    need_s: float
    ok: bool
    reason: str | None = None


class ConfidenceEligibility(_M):
    value: float
    need: float = 0.8
    ok: bool


class ChainEligibility(_M):
    ok: bool


class ZoneEligibility(_M):
    zone_id: ZoneId
    plan_id: str
    camera: CameraEligibility
    sensors: SensorEligibility
    confidence: ConfidenceEligibility
    chain: ChainEligibility
    eligible: bool
    # blocking reasons the per-rule fields do not cover ("expected recovery unavailable", already verified)
    reason: str | None = None


class ChainVerification(_M):
    intact: bool
    checked: int
    first_broken_index: int | None = None
    at: Iso


class ProjectedRequest(_M):
    plan_id: str


# ---- alerts and director ----------------------------------------------------------------------
class Alert(_M):
    id: str
    at: Iso
    last_seen_at: Iso
    occurrences: int
    type: str
    severity: Literal["info", "warning", "critical"]
    zone_id: ZoneId | None = None
    node_id: NodeId | None = None
    message: str
    acknowledged_at: Iso | None = None
    details: Json = Field(default_factory=dict)


StepKey = Literal["early_warning", "detect", "task", "measure", "fuse", "predict", "restore", "verify"]


class DirectorDetected(_M):
    type: str
    at: Iso
    summary: str


class DirectorStep(_M):
    key: StepKey
    n: int
    caption: str
    action: str | None = None
    status: Literal["pending", "waiting", "blocked", "done", "skipped"]
    blocked_reason: str | None = None
    detected: DirectorDetected | None = None


class DirectorState(_M):
    active: bool
    branch: Literal["main", "early_warning"]
    current: StepKey | None = None
    started_at: Iso | None = None
    steps: list[DirectorStep]


class DirectorStart(_M):
    branch: Literal["main", "early_warning"]


# ---- error envelope and events ----------------------------------------------------------------
class ErrorBody(_M):
    code: str
    message: str
    details: Json | None = None


class ErrorEnvelope(_M):
    error: ErrorBody


class EventEnvelope(_M):
    v: Literal[1] = 1
    type: str
    id: str
    at: Iso
    data: Json


class HelloData(_M):
    server_time: Iso
    version: str
    demo_time_scale: bool
