// The Field Model (PRD decision 9): a value for every Sensor at any point, computed analytically.

import { SENSOR_POSTS, STATION } from '../site/catalogue'
import { fbm2 } from './noise'
import { SENSORS, type Reading } from './ranges'

const OFFSET_SCALE = 60
const INFLUENCE_M = 120

// One seed per Sensor, in SENSORS order.
const SEEDS = [101, 202, 303, 404, 808, 909, 505, 606, 707]
const stationNoise = SENSORS.map((_, i) => fbm2(STATION.x / OFFSET_SCALE, STATION.z / OFFSET_SCALE, SEEDS[i], 2))

/**
 * Sensor values at local point (x, z).
 * value = healthy base (station healthy Reading plus a smooth spatial offset that is zero at the station)
 *       + w(p) x (station Reading - station healthy Reading), with w = exp(-(d / 120 m)^2).
 */
export function sensorsAt(x: number, z: number, station: Reading, stationHealthy: Reading, out?: Reading): Reading {
  const r = (out ?? {}) as Reading
  const dx = x - STATION.x
  const dz = z - STATION.z
  const d2 = dx * dx + dz * dz
  const w = Math.exp(-d2 / (INFLUENCE_M * INFLUENCE_M))
  const fade = 1 - Math.exp(-d2 / (40 * 40))
  for (let i = 0; i < SENSORS.length; i++) {
    const s = SENSORS[i]
    const n = fbm2(x / OFFSET_SCALE, z / OFFSET_SCALE, SEEDS[i], 2) - stationNoise[i] * (1 - fade)
    const offset = s.offsetAmp * Math.max(-1, Math.min(1, n * 1.25)) * fade
    r[s.id] = stationHealthy[s.id] + offset + w * (station[s.id] - stationHealthy[s.id])
  }
  return r
}

/** One Reading per sensor post, in SENSOR_POSTS order. At the station this is exactly the live Reading. */
export function postReadings(station: Reading, stationHealthy: Reading): Reading[] {
  return SENSOR_POSTS.map((p) => sensorsAt(p.x, p.z, station, stationHealthy))
}
