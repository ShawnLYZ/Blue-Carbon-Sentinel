// Local mirror of the Sentinel Simulator control API (addendum K1/K2). Kept by hand: the simulator is not
// part of the Ground Station OpenAPI document.

export type NodeType = 'water_quality' | 'soil_probe' | 'tide_gauge' | (string & {})
export type Behaviour = 'hold' | 'drift'

export interface SimPosition {
  e_m: number
  s_m: number
}

export interface SimNode {
  node_id: string
  node_type: NodeType
  position: SimPosition
  zone_label: string
  connected: boolean
  mode: string
  interval_s: number
  /** Live, noise-free values (plus the fault preview). */
  readings: Record<string, number>
  natural: Record<string, number>
  overrides: Record<string, { value: number; behaviour: Behaviour }>
  battery_pct: number
  rssi_dbm: number
  /** Active faults: kind -> params. */
  faults: Record<string, Record<string, unknown>>
  last_command: { id: string; type: string; at: string } | null
  last_ack: { status: string; at: string } | null
  source: 'simulated'
}

export interface SimTide {
  enabled: boolean
  mean_cm: number
  amplitude_cm: number
  spring_neap: boolean
}

export interface SimNature {
  tide: SimTide
  diurnal: boolean
  noise: boolean
}

export interface SimRecording {
  id: string
  name: string
  started_at: string
  messages: number
}

export interface SimReplay {
  path: string
  sent: number
  total: number
  session_id?: string | null
}

export interface ZoneScenario {
  scenario: string
  started_at: string
  ramp_s: number
}

/** GET /api/v1/state */
export interface SimState {
  broker_connected: boolean
  demo_time_scale?: boolean
  fast_forward?: number
  /** `{}` until the runtime has started. */
  nature?: Partial<SimNature> | null
  nodes?: SimNode[]
  zone_scenarios?: Record<string, ZoneScenario>
  recording?: SimRecording | null
  replay?: SimReplay | null
}

export interface ScenarioApply { scenario: string; ramp_s?: number }
export interface ScenarioApplied {
  zone_label: string
  scenario: string
  ramp_s: number
  nodes: { node_id: string; factor: number }[]
  warning: string | null
}
export interface OverrideBody { parameter: string; value: number; behaviour: Behaviour }
export interface HealthBody { battery_pct?: number; rssi_dbm?: number }
export interface FaultBody { kind: string; params?: Record<string, unknown> }
export interface NaturePatch {
  tide?: Partial<SimTide>
  diurnal?: boolean
  noise?: boolean
  fast_forward?: number
}
export type InstallBody = { node_type: NodeType; position: SimPosition } | { suggestion_id: string }
export interface MoveBody { position: SimPosition; confirm: boolean }
export interface ConfirmBody { confirm: boolean }
export interface RecordingStartBody { name: string }
export interface ScenarioRunBody { script?: string; name?: string; seed?: number }

export interface ScenarioInfo {
  id: string
  offsets: Record<string, number>
  default_ramp_s: number
  node_types: string[]
}
/** GET /api/v1/scenarios */
export type ScenarioCatalogue = ScenarioInfo[]

export interface Session {
  id: string
  name: string
  created_at: string
  seed: number
  duration_s: number
  message_count: number
  nodes: string[]
  kind: string
  uploaded: boolean
  upload_error: string | null
  local: boolean
  file: string
}
/** GET /api/v1/sessions (newest first) */
export type SessionList = Session[]

/** /ws messages (K2). */
export interface InspectorPacket {
  at: string
  direction: 'up' | 'down'
  node_id: string
  channel: string
  topic: string
  payload: unknown
  valid: boolean
  errors: string[]
}
export interface SimWsStatus {
  runtime: 'running' | 'starting'
  last_error: string | null
  broker_connected: boolean
  demo_time_scale: boolean
  fast_forward: number
  recording: SimRecording | null
  replay: SimReplay | null
  scenario_run: unknown
}
export type SimWsMessage = (
  | { type: 'inspector.packet'; data: InspectorPacket }
  | { type: 'nodes.state'; data: SimNode[] }
  | { type: 'sim.status'; data: SimWsStatus }
) & { dropped?: number }
