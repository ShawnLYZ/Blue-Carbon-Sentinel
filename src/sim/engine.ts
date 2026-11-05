// The Sensor Engine (PRD decision 8): a Reading every 2 seconds, the danger and restore ramps, and the Level.
// Everything is a pure function of time and the ramp state, so the same moment always gives the same values.

import { noise1, hash1 } from './noise'
import { SENSORS, SENSOR_IDS, type Reading, type SensorId } from './ranges'

export const TICK_MS = 2000
export const RAMP_MS = 10_000
export const HISTORY_POINTS = 150

export type EngineMode = 'healthy' | 'dropping' | 'danger' | 'restoring'

export interface RampState {
  mode: EngineMode
  startedAt: number
  from: Reading
}

const SEED: Record<SensorId, number> = {
  dissolved_oxygen: 11, salinity: 23, turbidity: 37, ph: 41, wave_height: 83, wave_velocity: 97,
  temperature: 53, humidity: 67, soil_moisture: 79,
}

/** Smooth wobble in [-1, 1]: a slow drift, a faster ripple and a small per-tick jitter. */
function wobble(id: SensorId, t: number): number {
  const s = SEED[id]
  const slow = noise1(t / 26_000, s)
  const mid = noise1(t / 7_400, s + 5)
  const jitter = hash1(Math.floor(t / TICK_MS) * 31 + s) * 2 - 1
  return 0.62 * slow + 0.26 * mid + 0.12 * jitter
}

export function healthyReading(t: number): Reading {
  const r = {} as Reading
  for (const s of SENSORS) r[s.id] = s.preset + s.wobble * wobble(s.id, t)
  return r
}

export function dangerReading(t: number): Reading {
  const r = healthyReading(t)
  for (const s of SENSORS) {
    if (!s.danger) continue
    const half = (s.danger.max - s.danger.min) / 2
    r[s.id] = s.danger.target + half * 0.9 * wobble(s.id, t + 99_000)
  }
  return r
}

const easeInOut = (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2)

export function rampProgress(state: RampState, t: number): number {
  return Math.min(1, Math.max(0, (t - state.startedAt) / RAMP_MS))
}

export function readingAt(state: RampState, t: number): Reading {
  switch (state.mode) {
    case 'healthy':
      return healthyReading(t)
    case 'danger':
      return dangerReading(t)
    case 'dropping': {
      const e = easeInOut(rampProgress(state, t))
      const target = dangerReading(t)
      const out = healthyReading(t)
      for (const s of SENSORS) {
        if (!s.danger) continue
        out[s.id] = state.from[s.id] + (target[s.id] - state.from[s.id]) * e
      }
      return out
    }
    case 'restoring': {
      const e = easeInOut(rampProgress(state, t))
      const target = healthyReading(t)
      const out = { ...target }
      for (const s of SENSORS) {
        if (!s.danger) continue
        out[s.id] = state.from[s.id] + (target[s.id] - state.from[s.id]) * e
      }
      return out
    }
  }
}

/** The last five minutes of Readings, so trend lines have a history from the first frame. */
export function backfill(state: RampState, now: number): Record<SensorId, number[]> {
  const h = Object.fromEntries(SENSOR_IDS.map((id) => [id, [] as number[]])) as Record<SensorId, number[]>
  const steady: RampState = { ...state, mode: state.mode === 'danger' ? 'danger' : 'healthy' }
  for (let k = HISTORY_POINTS - 1; k >= 0; k--) {
    const r = readingAt(steady, now - k * TICK_MS)
    for (const id of SENSOR_IDS) h[id].push(r[id])
  }
  return h
}
