// Simulated AI text for the demo. Written from the live readings so the numbers always match the screen.

import { SENSOR_BY_ID, SENSORS, bandOf, formatReading, sensorsIn, type Reading, type SensorId } from './ranges'
import type { PatchId, ReplantPatch } from '../site/catalogue'

/** Why a reading is off and what most likely caused it, per Sensor and side. */
const CAUSES: Record<SensorId, { low?: string; high?: string }> = {
  dissolved_oxygen: { low: 'it is likely caused by rotting leaves and stagnant water at low tide using up the oxygen, which suffocates the roots' },
  salinity: { high: 'it is likely caused by strong evaporation and little rain or river inflow, so salt builds up around the roots' },
  turbidity: { high: 'it is likely caused by storm waves stirring up mud and runoff from upstream, which blocks light and buries seedlings' },
  ph: {
    low: 'it is likely caused by acid sulfate soil being exposed and washed out after the mud dried and was disturbed',
    high: 'it is likely caused by an algae bloom or alkaline runoff from nearby land',
  },
  wave_height: { high: 'it is likely caused by a passing storm or monsoon swell pushing high waves against the forest edge, which can uproot young trees' },
  wave_velocity: { high: 'it is likely caused by strong storm currents scouring the mud around the roots and loosening the trees' },
  temperature: {
    low: 'it is likely caused by unusually cold weather, which slows the trees’ growth',
    high: 'it is likely caused by a heatwave and strong midday sun on shallow water, which stresses the leaves and dries the mud',
  },
  humidity: { low: 'it is likely caused by dry, hot winds, making the trees lose water through their leaves faster than they can replace it' },
  soil_moisture: { low: 'it is likely caused by a long dry spell or very low tides, leaving the mud dry and cracked around the roots' },
}

function sentence(id: SensorId, v: number) {
  const spec = SENSOR_BY_ID[id]
  const high = v > spec.stress.ideal
  const cause = (high ? CAUSES[id].high : CAUSES[id].low) ?? CAUSES[id].high ?? CAUSES[id].low
  const unit = spec.unit ? (spec.unit === '°C' || spec.unit === '%' ? spec.unit : ` ${spec.unit}`) : ''
  const name = id === 'ph' ? 'The pH' : `The ${spec.name.toLowerCase()}`
  return `${name} is too ${high ? 'high' : 'low'} (${formatReading(id, v)}${unit}); ${cause}.`
}

/** Null when nothing is in Danger or Warning. */
export function dangerSummary(r: Reading): { band: 'danger' | 'warning'; lines: string[]; advice: string } | null {
  const danger = sensorsIn(r, 'danger')
  const ids = danger.length ? danger : sensorsIn(r, 'warning')
  if (!ids.length) return null
  const groups = new Set(ids.map((id) => SENSOR_BY_ID[id].group))
  const advice = groups.has('wave')
    ? 'Together these point to a storm surge hitting the station. Check the young trees for broken roots once the water calms.'
    : groups.has('water')
      ? 'Together these point to poor water flow around the station. Check the creek for blockages and watch the next readings.'
      : 'Keep an eye on the next readings; the trees recover if conditions return to normal within a few days.'
  return { band: danger.length ? 'danger' : 'warning', lines: ids.map((id) => sentence(id, r[id])), advice }
}

/** Past-year growth per patch, as if learned from last year's satellite and sensor history. */
const GROWTH: Record<PatchId, { rate: number; survival: number }> = {
  'patch-1': { rate: 38, survival: 91 },
  'patch-2': { rate: 33, survival: 87 },
  'patch-3': { rate: 35, survival: 89 },
}

export function replantSuggestion(patch: ReplantPatch, values: Reading): string {
  const g = GROWTH[patch.id]
  const healthy = SENSORS.filter((s) => bandOf(s.id, values[s.id]) === 'healthy').length
  return `This area is suitable for replanting mangroves. Looking at the past year’s data, mangroves around here grew about ${g.rate} cm in height, `
    + `with ${g.survival}% of seedlings surviving. ${healthy} of ${SENSORS.length} readings at this spot are healthy, and the soil moisture `
    + `(${formatReading('soil_moisture', values.soil_moisture)}%) and salinity (${formatReading('salinity', values.salinity)} PSU) suit young Rhizophora seedlings.`
}
