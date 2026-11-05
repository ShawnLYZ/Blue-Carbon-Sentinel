// App-wide state. The Sensor Engine runs here (not inside a page), so a ramp keeps going when the visitor
// changes page (addendum A0.4). What the PRD keeps in Supabase is kept in localStorage in this demo.

import { create } from 'zustand'
import cameraLibrary from 'virtual:camera-photos'
import {
  backfill, healthyReading, HISTORY_POINTS, rampProgress, readingAt, TICK_MS, type RampState,
} from '../sim/engine'
import { levelOf, sensorsIn, SENSOR_IDS, type Band, type Reading, type SensorId } from '../sim/ranges'
import { REPLANT_PATCHES, type PatchId } from '../site/catalogue'
import { hash1 } from '../sim/noise'

export type Route = 'command' | 'satellite' | 'network' | 'twin'
export const ROUTES: Route[] = ['command', 'satellite', 'network', 'twin']

export const CAMERA_OFFLINE_SECONDS = 120
export const PHOTO_EXPIRY_MINUTES = 10

export interface DangerEvent {
  id: string
  startedAt: number
  endedAt: number | null
  endReason: 'recovered' | 'reset' | null
  triggerSensors: SensorId[]
}

export type RequestStatus = 'pending' | 'done' | 'failed' | 'expired'

export interface PhotoRequest {
  id: string
  createdAt: number
  dangerEventId: string
  kind: 'danger' | 'retry'
  status: RequestStatus
  dueAt: number
  willFail: boolean
  completedAt: number | null
  photoId: string | null
}

export interface Photo {
  id: string
  takenAt: number
  src: string
  credit: string | null
  source: 'sample' | 'own'
  requestId: string
  dangerEventId: string
}

export interface Planting {
  plantedYear: number
  scannedAt: number
}

interface Persisted {
  events: DangerEvent[]
  requests: PhotoRequest[]
  photos: Photo[]
  plantings: Partial<Record<PatchId, Planting>>
  photoCursor: number
}

export interface AppState extends Persisted {
  now: number
  /** When the current Reading was produced. */
  tickTime: number
  year: number
  ramp: RampState
  reading: Reading
  level: Band
  history: Record<SensorId, number[]>
  dangerReported: boolean
  healthyReported: boolean
  /** True only in the tab where the ramp button was pressed. */
  rampOwner: boolean
  heartbeatPhase: number

  tick(): void
  clock(): void
  simulateDanger(): void
  restoreHealthy(): void
  retryPhoto(): void
  plantPatch(id: PatchId): void
  resetDemo(): void
  /** Save Lah!: clears the camera panel and glides the readings back to Healthy like Restore healthy. */
  savePanel(): void
  syncFromStorage(): void
}

const KEY = 'bcs-demo-state-v1'

function load(): Persisted {
  const empty: Persisted = { events: [], requests: [], photos: [], plantings: {}, photoCursor: 0 }
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return empty
    const p = JSON.parse(raw) as Partial<Persisted>
    return {
      events: Array.isArray(p.events) ? p.events : [],
      requests: Array.isArray(p.requests) ? p.requests : [],
      photos: Array.isArray(p.photos) ? p.photos : [],
      plantings: p.plantings && typeof p.plantings === 'object' ? p.plantings : {},
      photoCursor: typeof p.photoCursor === 'number' ? p.photoCursor : 0,
    }
  } catch {
    return empty
  }
}

function save(s: Persisted) {
  try {
    const { events, requests, photos, plantings, photoCursor } = s
    localStorage.setItem(KEY, JSON.stringify({ events, requests, photos, plantings, photoCursor }))
  } catch {
    // Private windows or blocked storage: the demo still runs, it just forgets on reload.
  }
}

const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`)

export const openEvent = (s: Pick<AppState, 'events'>) => s.events.find((e) => e.endedAt === null) ?? null
export const pendingRequest = (s: Pick<AppState, 'requests'>) => s.requests.find((r) => r.status === 'pending') ?? null
export const latestRequest = (s: Pick<AppState, 'requests'>) => s.requests[s.requests.length - 1] ?? null

/** The camera's simulated heartbeat: once a minute, at a fixed phase. */
export function lastHeard(s: Pick<AppState, 'now' | 'heartbeatPhase' | 'photos'>): number {
  const beat = Math.floor((s.now - s.heartbeatPhase) / 60_000) * 60_000 + s.heartbeatPhase
  const lastPhoto = s.photos.length ? s.photos[s.photos.length - 1].takenAt : 0
  return Math.max(beat, lastPhoto <= s.now ? lastPhoto : 0)
}

export function cameraOnline(s: Pick<AppState, 'now' | 'heartbeatPhase' | 'photos'>): boolean {
  return s.now - lastHeard(s) < CAMERA_OFFLINE_SECONDS * 1000
}

function newRequest(s: Persisted, eventId: string, kind: 'danger' | 'retry', now: number): PhotoRequest {
  const willFail = cameraLibrary.photos.length === 0
  // The camera checks every 5 s, captures (up to 3 attempts) and uploads: a photo lands in about 6-12 s.
  const delay = willFail ? 14_000 : 6_000 + Math.round(hash1(s.requests.length * 977 + Math.floor(now / 1000)) * 6_000)
  return {
    id: uid(), createdAt: now, dangerEventId: eventId, kind, status: 'pending', dueAt: now + delay, willFail,
    completedAt: null, photoId: null,
  }
}

const initial = load()
const now0 = Date.now()
const startOpen = initial.events.some((e) => e.endedAt === null)
const ramp0: RampState = { mode: startOpen ? 'danger' : 'healthy', startedAt: now0, from: healthyReading(now0) }
const reading0 = readingAt(ramp0, now0)

export const useApp = create<AppState>((set, get) => ({
  ...initial,
  now: now0,
  tickTime: now0,
  year: 1,
  ramp: ramp0,
  reading: reading0,
  level: levelOf(reading0),
  history: backfill(ramp0, now0),
  dangerReported: startOpen,
  healthyReported: !startOpen,
  rampOwner: false,
  heartbeatPhase: now0 - 17_000 - Math.round(Math.random() * 20_000),

  tick() {
    const s = get()
    const t = Date.now()
    const reading = readingAt(s.ramp, t)
    const level = levelOf(reading)
    const history = { ...s.history }
    for (const id of SENSOR_IDS) {
      const arr = s.history[id].slice(-(HISTORY_POINTS - 1))
      arr.push(reading[id])
      history[id] = arr
    }
    let ramp = s.ramp
    let { dangerReported, healthyReported } = s
    const p = rampProgress(ramp, t)
    let next: Partial<AppState> = {}

    if (ramp.mode === 'dropping') {
      if (level === 'danger' && !dangerReported) {
        dangerReported = true
        next = { ...next, ...openDanger(get(), sensorsIn(reading, 'danger'), t) }
      }
      if (p >= 1) ramp = { ...ramp, mode: 'danger' }
    } else if (ramp.mode === 'restoring') {
      if (level === 'healthy' && !healthyReported) {
        healthyReported = true
        next = { ...next, ...closeDanger(get(), 'recovered', t) }
      }
      if (p >= 1) ramp = { ...ramp, mode: 'healthy' }
    }
    set({ ...next, now: t, tickTime: t, reading, level, history, ramp, dangerReported, healthyReported })
  },

  clock() {
    const s = get()
    const t = Date.now()
    let changed = false
    let cursor = s.photoCursor
    const photos = [...s.photos]
    const requests = s.requests.map((r) => {
      if (r.status !== 'pending') return r
      if (t - r.createdAt > PHOTO_EXPIRY_MINUTES * 60_000) {
        changed = true
        return { ...r, status: 'expired' as const, completedAt: t }
      }
      if (t < r.dueAt) return r
      changed = true
      const lib = cameraLibrary.photos
      if (r.willFail || lib.length === 0) return { ...r, status: 'failed' as const, completedAt: r.dueAt }
      const pick = lib[cursor % lib.length]
      cursor += 1
      const photo: Photo = {
        id: uid(), takenAt: r.dueAt, src: pick.src, credit: pick.credit, source: cameraLibrary.source,
        requestId: r.id, dangerEventId: r.dangerEventId,
      }
      photos.push(photo)
      return { ...r, status: 'done' as const, completedAt: r.dueAt, photoId: photo.id }
    })
    if (changed) {
      const persisted = { ...s, requests, photos: photos.slice(-40), photoCursor: cursor }
      save(persisted)
      set({ now: t, requests, photos: persisted.photos, photoCursor: cursor })
    } else {
      set({ now: t })
    }
  },

  simulateDanger() {
    const s = get()
    if (s.ramp.mode !== 'healthy') return
    const t = Date.now()
    set({
      ramp: { mode: 'dropping', startedAt: t, from: readingAt(s.ramp, t) },
      dangerReported: false, healthyReported: false, rampOwner: true,
    })
    restartTicker()
  },

  restoreHealthy() {
    const s = get()
    if (s.ramp.mode !== 'danger') return
    const t = Date.now()
    set({
      ramp: { mode: 'restoring', startedAt: t, from: readingAt(s.ramp, t) },
      healthyReported: false, rampOwner: true,
    })
    restartTicker()
  },

  retryPhoto() {
    const s = get()
    if (pendingRequest(s)) return
    const ev = s.events[s.events.length - 1]
    if (!ev) return
    const t = Date.now()
    const requests = [...s.requests, newRequest(s, ev.id, 'retry', t)]
    save({ ...s, requests })
    set({ requests, now: t })
  },

  plantPatch(id) {
    const s = get()
    if (openEvent(s) || s.plantings[id]) return
    const plantings = { ...s.plantings, [id]: { plantedYear: s.year, scannedAt: Date.now() } }
    save({ ...s, plantings })
    set({ plantings })
  },

  resetDemo() {
    const s = get()
    const t = Date.now()
    const events = s.events.map((e) => (e.endedAt === null ? { ...e, endedAt: t, endReason: 'reset' as const } : e))
    const requests = s.requests.map((r) => (r.status === 'pending' ? { ...r, status: 'expired' as const, completedAt: t } : r))
    const ramp: RampState = { mode: 'healthy', startedAt: t, from: healthyReading(t) }
    const reading = readingAt(ramp, t)
    save({ ...s, events, requests, plantings: {} })
    set({
      events, requests, plantings: {}, year: 1, ramp, reading, level: levelOf(reading),
      history: backfill(ramp, t), dangerReported: false, healthyReported: true, rampOwner: false, now: t, tickTime: t,
    })
  },

  savePanel() {
    const s = get()
    const t = Date.now()
    const restore = s.ramp.mode === 'danger' || s.ramp.mode === 'dropping'
    save({ ...s, requests: [], photos: [] })
    set({
      requests: [], photos: [], now: t,
      // Same glide back as Restore healthy; the tick closes the Danger Event once readings are Healthy.
      ...(restore ? { ramp: { mode: 'restoring' as const, startedAt: t, from: readingAt(s.ramp, t) }, healthyReported: false, rampOwner: true } : {}),
    })
    if (restore) restartTicker()
  },

  syncFromStorage() {
    const s = get()
    const p = load()
    const wasOpen = !!openEvent(s)
    const isOpen = p.events.some((e) => e.endedAt === null)
    const t = Date.now()
    let patch: Partial<AppState> = { ...p }
    // Another tab opened or closed the Danger Event: follow it, unless this tab is running its own ramp.
    if (isOpen && !wasOpen && s.ramp.mode === 'healthy') {
      patch = { ...patch, ramp: { mode: 'danger', startedAt: t, from: s.reading }, dangerReported: true }
    }
    if (!isOpen && wasOpen && (s.ramp.mode === 'danger' || (s.ramp.mode === 'dropping' && !s.rampOwner))) {
      patch = { ...patch, ramp: { mode: 'healthy', startedAt: t, from: s.reading }, healthyReported: true }
    }
    set(patch)
  },
}))

function openDanger(s: AppState, sensors: SensorId[], t: number): Partial<AppState> {
  if (openEvent(s)) return {}
  const ev: DangerEvent = { id: uid(), startedAt: t, endedAt: null, endReason: null, triggerSensors: sensors }
  const events = [...s.events, ev].slice(-30)
  const requests = pendingRequest(s) ? s.requests : [...s.requests, newRequest(s, ev.id, 'danger', t)].slice(-40)
  save({ ...s, events, requests })
  return { events, requests }
}

function closeDanger(s: AppState, reason: 'recovered' | 'reset', t: number): Partial<AppState> {
  if (!openEvent(s)) return {}
  const events = s.events.map((e) => (e.endedAt === null ? { ...e, endedAt: t, endReason: reason } : e))
  save({ ...s, events })
  return { events }
}

let ticker: ReturnType<typeof setInterval> | null = null
function restartTicker() {
  if (ticker) clearInterval(ticker)
  ticker = setInterval(() => useApp.getState().tick(), TICK_MS)
}

let started = false
/** Starts the app-wide clocks once: Readings every 2 s, camera and "time ago" labels every second. */
export function startSimulation() {
  if (started) return
  started = true
  restartTicker()
  setInterval(() => useApp.getState().clock(), 1000)
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) useApp.getState().syncFromStorage()
  })
}

export function nextPatch(plantings: Partial<Record<PatchId, Planting>>) {
  return REPLANT_PATCHES.find((p) => !plantings[p.id]) ?? null
}

export const PHOTO_SOURCE = cameraLibrary.source
export const PHOTO_COUNT = cameraLibrary.photos.length
