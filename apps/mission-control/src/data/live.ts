// Wires the events client and HTTP snapshots into the store (addendum J3).
import type { Assessment, CameraStatus, Coverage, DirectorState, EventEnvelope, EventMap, Task, TreePoints } from '@bcs/api-types'
import { api } from './client'
import { connectEvents, type Snapshot } from './events'
import { useAppStore } from './store'

/** Fetches every snapshot the store holds. `at` is the Ground Station's own clock (SystemStatus.now). */
export async function fetchSnapshots(): Promise<Snapshot> {
  const st = useAppStore.getState()
  // Status first: its server time is the cutoff, so anything that changes while the other
  // snapshots load is re-applied from the event buffer.
  const status = await api.GET('/api/v1/system/status')
  if (!status.data) throw new Error('system status snapshot failed')
  // The network snapshots load alongside but never hold up the shell's own (site, alerts, ...).
  const network = fetchNetworkSnapshots().then(
    () => null,
    (e: unknown) => e, // held until the shell snapshots are applied; never an unhandled rejection
  )
  const [site, alerts, config, camera, settings, bands, director] = await Promise.all([
    api.GET('/api/v1/site'),
    api.GET('/api/v1/alerts'),
    api.GET('/api/v1/system/config'),
    api.GET('/api/v1/camera/status'),
    api.GET('/api/v1/system/settings'),
    api.GET('/api/v1/system/bands'),
    api.GET('/api/v1/director'),
  ])
  st.setStatus(status.data)
  if (site.data) st.setSite(site.data)
  if (alerts.data) st.setAlerts(alerts.data)
  if (config.data) st.setConfig(config.data)
  if (camera.data) st.setCameraStatus(camera.data)
  if (bands.data) st.setBands(bands.data)
  if (director.data) st.setDirector(director.data)
  if (settings.data) st.setExaggeration(settings.data.vertical_exaggeration)
  // Intelligence snapshots (assessments, trees, zone metrics) never fail the resync: the previous
  // slices stay and the next resync or event retries.
  await fetchIntelSnapshots((site.data ?? st.site.site)?.zones.map((z) => z.id) ?? []).catch(() => undefined)
  // Pages holding HTTP-fetched captures or calibration refetch after every (re)sync.
  st.bumpRev('captures')
  st.bumpRev('calibration')
  const networkError = await network
  if (networkError) throw networkError
  return { at: status.data.now }
}

/**
 * Sentinel Network snapshots: nodes, open and recent tasks, coverage and the latest commissioning run.
 * Failures leave the previous slice in place (the next resync or registry event retries).
 */
export async function fetchNetworkSnapshots(): Promise<void> {
  const st = useAppStore.getState()
  const [nodes, tasks, coverage, run] = await Promise.all([
    api.GET('/api/v1/nodes'),
    api.GET('/api/v1/tasks', { params: { query: { status: 'active' } } }),
    api.GET('/api/v1/coverage'),
    api.GET('/api/v1/commissioning'),
  ])
  if (nodes.data) st.setNodes(nodes.data)
  if (tasks.data) st.setTasks(tasks.data)
  if (coverage.data) st.setCoverage(coverage.data)
  if (run.data) st.setCommissioning(run.data)
  else if (run.response.status === 404) st.setCommissioning(null)
}

/**
 * Digital Twin snapshots: the latest assessment of every zone, the latest tree points (404 before any
 * were located means "no trees yet") and the latest zone metrics.
 */
export async function fetchIntelSnapshots(zoneIds: string[]): Promise<void> {
  const st = useAppStore.getState()
  const [assessments, trees] = await Promise.all([
    Promise.all(
      zoneIds.map((zone_id) =>
        api.GET('/api/v1/zones/{zone_id}/assessments', { params: { path: { zone_id }, query: { limit: 1 } } }),
      ),
    ),
    api.GET('/api/v1/trees'),
    refreshZoneSummaries(),
  ])
  if (assessments.every((r) => r.data)) st.setAssessments(assessments.flatMap((r) => r.data ?? []))
  if (trees.data) st.setTrees(trees.data)
  else if (trees.response.status === 404) st.setTrees(null)
}

/** The latest metrics of every zone (GET /zones); called on resync and after capture events settle. */
export async function refreshZoneSummaries(): Promise<void> {
  const r = await api.GET('/api/v1/zones')
  if (r.data) useAppStore.getState().setZoneSummaries(r.data)
}

/** Registry changes move, add or remove nodes: refetch the registry, coverage and commissioning. */
export async function refreshRegistry(): Promise<void> {
  const st = useAppStore.getState()
  const [nodes, coverage, run] = await Promise.all([
    api.GET('/api/v1/nodes'),
    api.GET('/api/v1/coverage'),
    api.GET('/api/v1/commissioning'),
  ])
  if (nodes.data) st.setNodes(nodes.data)
  if (coverage.data) st.setCoverage(coverage.data)
  if (run.data) st.setCommissioning(run.data)
}

function isType<K extends keyof EventMap>(e: EventEnvelope, type: K): e is EventEnvelope<EventMap[K]> {
  return e.type === type
}

const CAPTURE_EVENTS = new Set(['capture.created', 'zone.metrics', 'zone.flagged', 'baseline.updated'])

const eventListeners = new Set<(e: EventEnvelope) => void>()

/**
 * Subscribes to every applied live event (after the store saw it); returns an unsubscribe function.
 * For page-local data that has no store slice (Time Travel's forecasts, plans and illustrations).
 */
export function onLiveEvent(fn: (e: EventEnvelope) => void): () => void {
  eventListeners.add(fn)
  return () => {
    eventListeners.delete(fn)
  }
}

/** Applies one live event to the store; unknown types are ignored (later milestones add slices). */
export function applyEvent(e: EventEnvelope): void {
  applyToStore(e)
  for (const fn of eventListeners) {
    try {
      fn(e)
    } catch (err) {
      console.warn('live event listener failed:', err)
    }
  }
}

function applyToStore(e: EventEnvelope): void {
  const st = useAppStore.getState()
  if (isType(e, 'hello')) st.setHello(e.data.server_time)
  else if (isType(e, 'system.status')) st.setStatus(e.data)
  else if (isType(e, 'director.state')) st.setDirector(e.data as DirectorState)
  else if (isType(e, 'camera.status')) st.setCameraStatus(e.data as CameraStatus)
  else if (isType(e, 'alert.created')) st.upsertAlert(e.data)
  else if (isType(e, 'alert.acknowledged')) {
    const d = e.data as { id: string; acknowledged_at: string }
    st.acknowledgeAlert(d.id, d.acknowledged_at)
  } else if (CAPTURE_EVENTS.has(e.type)) st.bumpRev('captures')
  else if (e.type === 'calibration.updated') st.bumpRev('calibration')
  else if (isType(e, 'node.telemetry')) st.applyTelemetry(e.data, e.at)
  else if (isType(e, 'node.status')) st.applyNodeStatus(e.data)
  else if (isType(e, 'node.event')) st.bumpNode(e.data.node_id)
  else if (isType(e, 'task.updated')) st.upsertTask(e.data as Task)
  else if (isType(e, 'coverage.updated')) st.setCoverage(e.data as Coverage)
  else if (isType(e, 'zone.assessed')) {
    st.upsertAssessment(e.data as Assessment)
    st.bumpRev('ai')
  } else if (e.type === 'ai.call') st.bumpRev('ai')
  else if (e.type === 'history.updated') st.bumpRev('history')
  else if (isType(e, 'trees.updated')) st.setTrees(e.data as TreePoints)
  else if (e.type === 'node.registry') refreshRegistry().catch(() => undefined)
}

/** Starts the live connection; returns a stop function. */
export function startLive(): () => void {
  const st = useAppStore.getState()
  return connectEvents(applyEvent, st.setConnection, { fetchSnapshot: fetchSnapshots })
}
