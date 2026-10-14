// Typecheck-only: fails `tsc` if any generated schema loses its alias in index.ts.
import type {
  AICall,
  AIKeyStatus,
  AIRoleStatus,
  AIStatus,
  Alert,
  Assessment,
  VisionObservationView,
  Band,
  BaselineRequest,
  BoundsM,
  Calibration,
  CalibrationRecommend,
  CalibrationResult,
  CameraEligibility,
  CameraSettings,
  CameraSettingsPatch,
  CameraStatus,
  Capture,
  CaptureComparison,
  CaptureMediaUrls,
  CaptureQuality,
  CaptureSummary,
  CarbonConstant,
  CarbonSummary,
  ChainEligibility,
  ChainVerification,
  CloudUsage,
  Command,
  CommissionedPosition,
  CommissioningCoverage,
  CommissioningRun,
  ComparisonZone,
  ComponentStatus,
  Confidence,
  ConfidenceEligibility,
  Confirm,
  Coverage,
  CoverageGap,
  CoverageZone,
  CredentialsRequest,
  DemoTimeValues,
  DepthStatus,
  DirectorDetected,
  DirectorStart,
  DirectorState,
  DirectorStep,
  EdgeFlag,
  ErrorBody,
  ErrorEnvelope,
  EvidenceChecklist,
  ExpectedUplift,
  Forecast,
  ForecastAccepted,
  ForecastRequest,
  ForecastScenarios,
  FourCornerRequest,
  Health,
  History,
  HistoryReal,
  HistoryYear,
  Illustration,
  Intervention,
  KeyResult,
  LedgerRecord,
  LockRequest,
  Node,
  NodeCovers,
  NodeCreate,
  NodeCreated,
  NodeDetail,
  NodeEvent,
  NodeLatest,
  NodeMove,
  NodePosition,
  OllamaStatus,
  PlanApplied,
  PlanApplyRequest,
  PlanItem,
  PlanProposeRequest,
  PlanSummary,
  PlanUpdateRequest,
  PlanVersion,
  PlannedSite,
  Point2,
  PreflightCheck,
  PreflightReport,
  ProjectedRequest,
  PublicConfig,
  RequestAccepted,
  RootCause,
  ScenarioSeries,
  SensorEligibility,
  Settings,
  SettingsPatch,
  Site,
  SitePosition,
  SourceChip,
  SyncState,
  SystemStatus,
  Task,
  TaskCreate,
  TaskRelease,
  TaskTimelineEntry,
  TelemetryPoint,
  TelemetrySeries,
  TreePoint,
  TreePoints,
  YearPoint,
  Zone,
  ZoneCoverage,
  ZoneDetail,
  ZoneEligibility,
  ZoneFlag,
  ZoneMetrics,
  ZoneMetricsAt,
  ZoneSummary,
  Schemas,
} from './index'

type All = [
  AICall,
  AIKeyStatus,
  AIRoleStatus,
  AIStatus,
  Alert,
  Assessment,
  VisionObservationView,
  Band,
  BaselineRequest,
  BoundsM,
  Calibration,
  CalibrationRecommend,
  CalibrationResult,
  CameraEligibility,
  CameraSettings,
  CameraSettingsPatch,
  CameraStatus,
  Capture,
  CaptureComparison,
  CaptureMediaUrls,
  CaptureQuality,
  CaptureSummary,
  CarbonConstant,
  CarbonSummary,
  ChainEligibility,
  ChainVerification,
  CloudUsage,
  Command,
  CommissionedPosition,
  CommissioningCoverage,
  CommissioningRun,
  ComparisonZone,
  ComponentStatus,
  Confidence,
  ConfidenceEligibility,
  Confirm,
  Coverage,
  CoverageGap,
  CoverageZone,
  CredentialsRequest,
  DemoTimeValues,
  DepthStatus,
  DirectorDetected,
  DirectorStart,
  DirectorState,
  DirectorStep,
  EdgeFlag,
  ErrorBody,
  ErrorEnvelope,
  EvidenceChecklist,
  ExpectedUplift,
  Forecast,
  ForecastAccepted,
  ForecastRequest,
  ForecastScenarios,
  FourCornerRequest,
  Health,
  History,
  HistoryReal,
  HistoryYear,
  Illustration,
  Intervention,
  KeyResult,
  LedgerRecord,
  LockRequest,
  Node,
  NodeCovers,
  NodeCreate,
  NodeCreated,
  NodeDetail,
  NodeEvent,
  NodeLatest,
  NodeMove,
  NodePosition,
  OllamaStatus,
  PlanApplied,
  PlanApplyRequest,
  PlanItem,
  PlanProposeRequest,
  PlanSummary,
  PlanUpdateRequest,
  PlanVersion,
  PlannedSite,
  Point2,
  PreflightCheck,
  PreflightReport,
  ProjectedRequest,
  PublicConfig,
  RequestAccepted,
  RootCause,
  ScenarioSeries,
  SensorEligibility,
  Settings,
  SettingsPatch,
  Site,
  SitePosition,
  SourceChip,
  SyncState,
  SystemStatus,
  Task,
  TaskCreate,
  TaskRelease,
  TaskTimelineEntry,
  TelemetryPoint,
  TelemetrySeries,
  TreePoint,
  TreePoints,
  YearPoint,
  Zone,
  ZoneCoverage,
  ZoneDetail,
  ZoneEligibility,
  ZoneFlag,
  ZoneMetrics,
  ZoneMetricsAt,
  ZoneSummary,
]
export type Aliased = All
export type KeysCovered = keyof Schemas extends
  | 'AICall'
  | 'AIKeyStatus'
  | 'AIRoleStatus'
  | 'AIStatus'
  | 'Alert'
  | 'Assessment'
  | 'VisionObservationView'
  | 'Band'
  | 'BandView'
  | 'BandsView'
  | 'BaselineRequest'
  | 'BoundsM'
  | 'Calibration'
  | 'CalibrationRecommend'
  | 'CalibrationResult'
  | 'CameraEligibility'
  | 'CameraSettings'
  | 'CameraSettingsPatch'
  | 'CameraStatus'
  | 'Capture'
  | 'CaptureComparison'
  | 'CaptureMediaUrls'
  | 'CaptureQuality'
  | 'CaptureSummary'
  | 'CarbonConstant'
  | 'CarbonSummary'
  | 'ChainEligibility'
  | 'ChainVerification'
  | 'CloudUsage'
  | 'Command'
  | 'CommissionedPosition'
  | 'CommissioningCoverage'
  | 'CommissioningRun'
  | 'ComparisonZone'
  | 'ComponentStatus'
  | 'Confidence'
  | 'ConfidenceEligibility'
  | 'Confirm'
  | 'Coverage'
  | 'CoverageGap'
  | 'CoverageZone'
  | 'CredentialsRequest'
  | 'DemoTimeValues'
  | 'DepthStatus'
  | 'DirectorDetected'
  | 'DirectorStart'
  | 'DirectorState'
  | 'DirectorStep'
  | 'EdgeFlag'
  | 'ErrorBody'
  | 'ErrorEnvelope'
  | 'EvidenceChecklist'
  | 'ExpectedUplift'
  | 'Forecast'
  | 'ForecastAccepted'
  | 'ForecastRequest'
  | 'ForecastScenarios'
  | 'FourCornerRequest'
  | 'Health'
  | 'History'
  | 'HistoryReal'
  | 'HistoryYear'
  | 'Illustration'
  | 'Intervention'
  | 'KeyResult'
  | 'LedgerRecord'
  | 'LockRequest'
  | 'Node'
  | 'NodeCovers'
  | 'NodeCreate'
  | 'NodeCreated'
  | 'NodeDetail'
  | 'NodeEvent'
  | 'NodeLatest'
  | 'NodeMove'
  | 'NodePosition'
  | 'OllamaStatus'
  | 'PlanApplied'
  | 'PlanApplyRequest'
  | 'PlanItem'
  | 'PlanProposeRequest'
  | 'PlanSummary'
  | 'PlanUpdateRequest'
  | 'PlanVersion'
  | 'PlannedSite'
  | 'Point2'
  | 'PreflightCheck'
  | 'PreflightReport'
  | 'ProjectedRequest'
  | 'PublicConfig'
  | 'RequestAccepted'
  | 'RootCause'
  | 'ScenarioSeries'
  | 'SensorEligibility'
  | 'Settings'
  | 'SettingsPatch'
  | 'Site'
  | 'SitePosition'
  | 'SourceChip'
  | 'SyncState'
  | 'SystemStatus'
  | 'Task'
  | 'TaskCreate'
  | 'TaskRelease'
  | 'TaskTimelineEntry'
  | 'TelemetryPoint'
  | 'TelemetrySeries'
  | 'TreePoint'
  | 'TreePoints'
  | 'YearPoint'
  | 'Zone'
  | 'ZoneCoverage'
  | 'ZoneDetail'
  | 'ZoneEligibility'
  | 'ZoneFlag'
  | 'ZoneMetrics'
  | 'ZoneMetricsAt'
  | 'ZoneSummary'
  ? true
  : never
export const _covered: KeysCovered = true

