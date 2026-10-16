import type { Raster } from './satellite'

export const ATTRIBUTES = ['ndvi', 'salinity', 'oxygen', 'turbidity', 'temperature', 'ph', 'soilSalinity', 'soilMoisture'] as const
export type Attribute = typeof ATTRIBUTES[number]
export type Inputs = { salinity: number; oxygen: number; turbidity: number; temperature: number; ph: number; soilSalinity: number; soilMoisture: number }
export const INPUT_KEYS = ['salinity', 'oxygen', 'turbidity', 'temperature', 'ph', 'soilSalinity', 'soilMoisture'] as const
export const BASE_INPUTS: Inputs = { salinity: 30, oxygen: 5.5, turbidity: 25, temperature: 30, ph: 7.8, soilSalinity: 35, soilMoisture: 60 }
export const ATTRIBUTE_META = {
  ndvi: { label: 'Vegetation (NDVI)', unit: '', min: -1, max: 1, step: 0.01 },
  salinity: { label: 'Water salinity', unit: 'PSU', min: 0, max: 60, step: 1 },
  oxygen: { label: 'Dissolved oxygen', unit: 'mg/L', min: 0.5, max: 10, step: 0.1 },
  turbidity: { label: 'Turbidity', unit: 'NTU', min: 0, max: 300, step: 5 },
  temperature: { label: 'Water temperature', unit: '°C', min: 24, max: 40, step: 0.5 },
  ph: { label: 'pH', unit: 'pH', min: 6, max: 9.5, step: 0.1 },
  soilSalinity: { label: 'Soil salinity', unit: 'PSU', min: 0, max: 90, step: 1 },
  soilMoisture: { label: 'Soil moisture', unit: '%', min: 0, max: 100, step: 1 },
}
export type RiskClass = 'low' | 'medium' | 'high' | 'critical' | 'unknown'
export const RISK_PALETTE: Record<RiskClass, string> = { low: '#37ce8a', medium: '#f0c64c', high: '#f48a38', critical: '#ef4759', unknown: '#647581' }
export interface RiskZone { id: string; col: number; row: number; ndvi: number | null; usable: number; inputs: Inputs; stress: Partial<Record<Attribute, number>>; score: number | null; risk: RiskClass; driver: Attribute | null }

const clamp = (v: number) => Math.max(0, Math.min(1, v))
// Sensor breakpoints mirror config/bands.yaml. These scenario inputs are NOT observations.
function ramp(value: number, points: [number, number][]): number {
  if (value <= points[0]![0]) return points[0]![1]
  for (let i = 1; i < points.length; i++) {
    const [x, y] = points[i]!, [px, py] = points[i - 1]!
    if (value === x) return y
    if (value <= x) return py + (y - py) * (value - px) / (x - px)
  }
  return points[points.length - 1]![1]
}
export function attributeStress(key: Attribute, value: number): number {
  if (key === 'salinity') return ramp(value, [[35, 0], [45, 0.6], [60, 1]])
  if (key === 'oxygen') return ramp(value, [[0.5, 1], [2, 0.6], [5, 0]])
  if (key === 'turbidity') return ramp(value, [[25, 0], [100, 0.6], [300, 1]])
  if (key === 'temperature') return ramp(value, [[32, 0], [36, 0.6], [40, 1]])
  if (key === 'ph') return ramp(value, [[6, 1], [6.5, 0.6], [7, 0], [8.5, 0], [9, 0.6], [9.5, 1]])
  if (key === 'soilSalinity') return ramp(value, [[40, 0], [60, 0.6], [90, 1]])
  // No configured soil-moisture risk band exists: this is explicitly an illustrative scenario rule.
  if (key === 'soilMoisture') return ramp(value, [[0, 1], [20, 0.6], [40, 0], [80, 0], [100, 0.6]])
  // Absolute NDVI is a visual screening heuristic, not the backend's baseline-change metric.
  return clamp((0.65 - value) / 0.5)
}
export function classify(score: number | null): RiskClass { return score === null ? 'unknown' : score < 30 ? 'low' : score < 60 ? 'medium' : score < 80 ? 'high' : 'critical' }

export function zoneRisks(raster: Raster | null, base: Inputs, overrides: Record<string, Inputs>, active: Attribute[], floor: Attribute | 'combined' = 'combined'): RiskZone[] {
  return Array.from({ length: 25 }, (_, index) => {
    const row = Math.floor(index / 5), col = index % 5, id = `${'ABCDE'[col]}${row + 1}`
    let sum = 0, valid = 0, total = 0
    if (raster) for (let y = Math.floor(row * raster.height / 5); y < Math.floor((row + 1) * raster.height / 5); y++) {
      for (let x = Math.floor(col * raster.width / 5); x < Math.floor((col + 1) * raster.width / 5); x++) {
        const i = y * raster.width + x; total++
        if (raster.valid[i] && Number.isFinite(raster.ndvi[i])) { sum += raster.ndvi[i]!; valid++ }
      }
    }
    const usable = total ? valid / total : 0
    const ndvi = usable >= 0.2 && valid ? sum / valid : null
    const inputs = overrides[id] ?? base
    const stress: Partial<Record<Attribute, number>> = {}
    let score: number | null = null, driver: Attribute | null = null
    // No data stays grey, even when a user increases a hypothetical input.
    if (ndvi !== null) {
      for (const key of active) stress[key] = attributeStress(key, key === 'ndvi' ? ndvi : inputs[key])
      for (const key of floor === 'combined' ? active : active.includes(floor) ? [floor] : []) {
        const s = stress[key]! * 100
        if (score === null || s > score) { score = s; driver = key }
      }
    }
    return { id, row, col, ndvi, usable, inputs, stress, score, risk: classify(score), driver }
  })
}
