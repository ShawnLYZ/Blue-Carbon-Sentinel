import { create } from 'zustand'
import type {
  Alert,
  BandsView,
  Assessment,
  CameraStatus,
  CommissioningRun,
  DirectorState,
  Coverage,
  EventMap,
  Node,
  PublicConfig,
  Site,
  SystemStatus,
  Task,
  TelemetryPoint,
  TreePoints,
  ZoneMetrics,
  ZoneSummary,
} from '@bcs/api-types'
import type { ConnState } from './events'
import type { BandsConfig, ClassLimits } from '../pages/CommandCenter/kpis'

/** How long the live per-node telemetry buffer reaches back (the Sentinel Network charts' window). */
export const TELEMETRY_WINDOW_MS = 15 * 60 * 1000
/** Hard cap per node so a fast-forwarded simulator cannot grow the buffer without bound. */
export const TELEMETRY_MAX_POINTS = 2000

type NodeTelemetryData = EventMap['node.telemetry']
type NodeStatusData = EventMap['node.status']

/** Newest first by creation time (ties by id, like GET /tasks). */
export function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => (a.created_at === b.created_at ? b.id.localeCompare(a.id) : b.created_at.localeCompare(a.created_at)))
}

/** A live sample in the per-node buffer; `replay` marks samples a simulator replay re-sent. */
export type LivePoint = TelemetryPoint & { replay?: boolean }

/** Whether a sample at `sampledAt` is at least as new as the current latest (none counts as older). */
export function isNewerSample(sampledAt: string, current: string | null | undefined): boolean {
  if (!current) return true
  const a = Date.parse(sampledAt)
  const b = Date.parse(current)
  return Number.isNaN(b) || (!Number.isNaN(a) && a >= b)
}

/** Appends one point to a node's buffer, keeping time order and the window. Returns a new array. */
export function appendPoint(buf: LivePoint[] | undefined, p: LivePoint): LivePoint[] {
  const out = buf ? buf.slice() : []
  if (out.some((x) => x.t === p.t)) return buf ?? out // duplicate delivery
  let i = out.length
  while (i > 0 && out[i - 1]!.t > p.t) i -= 1
  out.splice(i, 0, p)
  const cutoff = Date.parse(out[out.length - 1]!.t) - TELEMETRY_WINDOW_MS
  let drop = 0
  while (drop < out.length && Date.parse(out[drop]!.t) < cutoff) drop += 1
  if (out.length - drop > TELEMETRY_MAX_POINTS) drop = out.length - TELEMETRY_MAX_POINTS
  return drop ? out.slice(drop) : out
}

/** Whether assessment `a` should replace `current` (newer `at` wins; equal `at` takes the later arrival). */
export function isNewerAssessment(a: Pick<Assessment, 'at'>, current: Pick<Assessment, 'at'> | undefined): boolean {
  if (!current) return true
  const x = Date.parse(a.at)
  const y = Date.parse(current.at)
  if (Number.isNaN(x) || Number.isNaN(y)) return a.at >= current.at
  return x >= y
}

export type Page = 'command' | 'satellite' | 'network' | 'twin' | 'time-travel' | 'ledger' | 'system' | 'about'

export interface AppState {
  system: {
    status: SystemStatus | null
    config: PublicConfig | null
    connection: ConnState
    helloAt: string | null
  }
  site: { site: Site | null }
  ui: {
    page: Page
    layers: Record<string, boolean>
    selectedZoneId: string | null
    /** The node open in the Sentinel Network drawer and highlighted on the map. */
    selectedNodeId: string | null
    director: boolean
  }
  /** The Demo Director run (GET /director, kept live by `director.state`). */
  director: { state: DirectorState | null }
  /** `loaded` turns true with the first alert snapshot, so alerts that already existed are never toasted. */
  alerts: { items: Alert[]; loaded: boolean }
  camera: { status: CameraStatus | null }
  /** Live twin view settings; `exaggeration` mirrors Settings.vertical_exaggeration (US 42). */
  twin: { exaggeration: number }
  /**
   * Change counters for data the pages fetch over HTTP: `captures` moves on capture, zone-metric,
   * flag and baseline events; `calibration` on calibration events. Pages refetch when they move.
   */
  rev: { captures: number; calibration: number; history: number; ai: number }
  /**
   * Sentinel Nodes (registry snapshot kept live by node.* events). `items` is in GET /nodes order;
   * positions change only with a fresh registry snapshot (node.registry), never per sample.
   * `telemetry` buffers live samples per node (last 15 minutes); `rev` moves per node on any of its
   * events so detail views can refetch.
   */
  nodes: { items: Node[]; telemetry: Record<string, LivePoint[]>; rev: Record<string, number> }
  /** Open and recent tasks, newest first. */
  tasks: { items: Task[] }
  /** Zone coverage with gap suggestions, and the latest commissioning run. */
  coverage: { coverage: Coverage | null; commissioning: CommissioningRun | null }
  /**
   * The latest assessment per zone (zone id -> assessment), from GET /zones/{id}/assessments on every
   * resync and kept live by `zone.assessed` (the code-only and the AI result of one zone both arrive).
   */
  assessments: { byZone: Record<string, Assessment> }
  /** The latest tree points (`null` before any were located: GET /trees answers 404). */
  trees: { points: TreePoints | null }
  /** The latest zone metrics per zone (GET /zones), refetched after capture events. */
  zones: { metrics: Record<string, ZoneMetrics> }
  /** Parameter stress breakpoints (GET /system/bands) for classifying live readings; `null` until loaded. */
  bands: { parameters: BandsConfig | null; classLimits: ClassLimits | null }

  setStatus: (s: SystemStatus) => void
  setConfig: (c: PublicConfig) => void
  setConnection: (c: ConnState) => void
  setHello: (at: string) => void
  setSite: (s: Site) => void
  setPage: (p: Page) => void
  toggleLayer: (name: string, on?: boolean) => void
  selectZone: (id: string | null) => void
  selectNode: (id: string | null) => void
  toggleDirector: (on?: boolean) => void
  setDirector: (state: DirectorState) => void
  setAlerts: (items: Alert[]) => void
  upsertAlert: (a: Alert) => void
  acknowledgeAlert: (id: string, acknowledgedAt: string) => void
  setCameraStatus: (c: CameraStatus) => void
  setExaggeration: (v: number) => void
  bumpRev: (kind: 'captures' | 'calibration' | 'history' | 'ai') => void
  setNodes: (items: Node[]) => void
  applyTelemetry: (d: NodeTelemetryData, receivedAt: string) => void
  applyNodeStatus: (d: NodeStatusData) => void
  bumpNode: (id: string) => void
  setTasks: (items: Task[]) => void
  upsertTask: (t: Task) => void
  setCoverage: (c: Coverage) => void
  setCommissioning: (r: CommissioningRun | null) => void
  setAssessments: (items: Assessment[]) => void
  upsertAssessment: (a: Assessment) => void
  setTrees: (t: TreePoints | null) => void
  setZoneSummaries: (items: ZoneSummary[]) => void
  setBands: (b: BandsView) => void
}

export const useAppStore = create<AppState>()((set) => ({
  system: { status: null, config: null, connection: 'closed', helloAt: null },
  site: { site: null },
  ui: { page: 'command', layers: {}, selectedZoneId: null, selectedNodeId: null, director: false },
  director: { state: null },
  alerts: { items: [], loaded: false },
  camera: { status: null },
  twin: { exaggeration: 1 },
  rev: { captures: 0, calibration: 0, history: 0, ai: 0 },
  nodes: { items: [], telemetry: {}, rev: {} },
  tasks: { items: [] },
  coverage: { coverage: null, commissioning: null },
  assessments: { byZone: {} },
  trees: { points: null },
  zones: { metrics: {} },
  bands: { parameters: null, classLimits: null },

  setStatus: (status) => set((s) => ({ system: { ...s.system, status } })),
  setConfig: (config) => set((s) => ({ system: { ...s.system, config } })),
  setConnection: (connection) => set((s) => ({ system: { ...s.system, connection } })),
  setHello: (helloAt) => set((s) => ({ system: { ...s.system, helloAt } })),
  setSite: (site) => set({ site: { site } }),
  setPage: (page) => set((s) => ({ ui: { ...s.ui, page } })),
  toggleLayer: (name, on) =>
    set((s) => ({ ui: { ...s.ui, layers: { ...s.ui.layers, [name]: on ?? !s.ui.layers[name] } } })),
  toggleDirector: (on) => set((s) => ({ ui: { ...s.ui, director: on ?? !s.ui.director } })),
  setDirector: (state) => set({ director: { state } }),
  selectZone: (selectedZoneId) => set((s) => ({ ui: { ...s.ui, selectedZoneId } })),
  selectNode: (selectedNodeId) => set((s) => ({ ui: { ...s.ui, selectedNodeId } })),
  setAlerts: (items) => set({ alerts: { items, loaded: true } }),
  upsertAlert: (a) =>
    set((s) => {
      const rest = s.alerts.items.filter((x) => x.id !== a.id)
      return { alerts: { ...s.alerts, items: [a, ...rest] } }
    }),
  acknowledgeAlert: (id, acknowledged_at) =>
    set((s) => ({
      alerts: { ...s.alerts, items: s.alerts.items.map((x) => (x.id === id ? { ...x, acknowledged_at } : x)) },
    })),
  setCameraStatus: (status) => set({ camera: { status } }),
  setExaggeration: (exaggeration) => set({ twin: { exaggeration } }),
  bumpRev: (kind) => set((s) => ({ rev: { ...s.rev, [kind]: s.rev[kind] + 1 } })),
  setNodes: (items) => set((s) => ({ nodes: { ...s.nodes, items } })),
  applyTelemetry: (d, receivedAt) =>
    set((s) => {
      const id = d.node_id
      // Addendum G5: latest views use the newest sampled_at. A late, out-of-order or replayed sample
      // older than the node's current latest goes to the buffer only; it never rolls `latest`, `mode`
      // or `last_seen_at` back.
      const items = s.nodes.items.map((n) =>
        n.id === id && isNewerSample(d.sampled_at, n.latest?.sampled_at)
          ? {
              ...n,
              mode: (d.mode as Node['mode']) ?? n.mode,
              fw_version: d.health.fw_version || n.fw_version,
              last_seen_at: receivedAt,
              latest: { sampled_at: d.sampled_at, readings: d.readings, health: d.health, flags: d.flags, late: d.late },
            }
          : n,
      )
      const point: LivePoint = { t: d.sampled_at, mode: d.mode, late: d.late, readings: d.readings, replay: d.replay }
      return {
        nodes: {
          items,
          telemetry: { ...s.nodes.telemetry, [id]: appendPoint(s.nodes.telemetry[id], point) },
          rev: { ...s.nodes.rev, [id]: (s.nodes.rev[id] ?? 0) + 1 },
        },
      }
    }),
  applyNodeStatus: (d) =>
    set((s) => ({
      nodes: {
        ...s.nodes,
        items: s.nodes.items.map((n) =>
          n.id === d.node_id
            ? {
                ...n,
                status: (['online', 'offline', 'unknown', 'decommissioned'].includes(d.state) ? d.state : n.status) as Node['status'],
                mode: (d.mode as Node['mode']) ?? n.mode,
                interval_s: d.interval_s ?? n.interval_s,
              }
            : n,
        ),
        rev: { ...s.nodes.rev, [d.node_id]: (s.nodes.rev[d.node_id] ?? 0) + 1 },
      },
    })),
  bumpNode: (id) => set((s) => ({ nodes: { ...s.nodes, rev: { ...s.nodes.rev, [id]: (s.nodes.rev[id] ?? 0) + 1 } } })),
  setTasks: (items) => set({ tasks: { items: sortTasks(items) } }),
  upsertTask: (t) =>
    set((s) => {
      const old = s.tasks.items.find((x) => x.id === t.id)
      // Events can arrive out of order with HTTP replies: never go back to an older version.
      if (old && old.updated_at > t.updated_at) return {}
      return { tasks: { items: sortTasks([t, ...s.tasks.items.filter((x) => x.id !== t.id)]) } }
    }),
  setCoverage: (coverage) => set((s) => ({ coverage: { ...s.coverage, coverage } })),
  setCommissioning: (commissioning) => set((s) => ({ coverage: { ...s.coverage, commissioning } })),
  setAssessments: (items) =>
    set(() => {
      // A snapshot replaces the slice (events after its cutoff are re-applied from the event buffer).
      const byZone: Record<string, Assessment> = {}
      for (const a of items) if (isNewerAssessment(a, byZone[a.zone_id])) byZone[a.zone_id] = a
      return { assessments: { byZone } }
    }),
  upsertAssessment: (a) =>
    set((s) => {
      // Events can arrive out of order with the HTTP snapshot: never go back to an older assessment.
      if (!isNewerAssessment(a, s.assessments.byZone[a.zone_id])) return {}
      return { assessments: { byZone: { ...s.assessments.byZone, [a.zone_id]: a } } }
    }),
  setBands: (b) => set({ bands: { parameters: b.parameters as BandsConfig, classLimits: b.class_limits as unknown as ClassLimits } }),
  setTrees: (points) => set({ trees: { points } }),
  setZoneSummaries: (items) =>
    set(() => {
      const metrics: Record<string, ZoneMetrics> = {}
      for (const z of items) if (z.metrics) metrics[z.zone.id] = z.metrics
      return { zones: { metrics } }
    }),
}))
