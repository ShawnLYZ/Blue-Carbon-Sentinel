// Sensor Ranges, Bands and Level (PRD decision 8). Boundary values belong to the healthier Band.

export type Band = 'healthy' | 'warning' | 'danger'

export type SensorId =
  | 'dissolved_oxygen'
  | 'salinity'
  | 'turbidity'
  | 'ph'
  | 'wave_height'
  | 'wave_velocity'
  | 'temperature'
  | 'humidity'
  | 'soil_moisture'

export interface SensorSpec {
  id: SensorId
  name: string
  short: string
  hint: string
  unit: string
  decimals: number
  preset: number
  wobble: number
  /** Danger target and the band the danger wobble stays in; null when the Sensor does not change. */
  danger: { target: number; min: number; max: number } | null
  offsetAmp: number
  group: 'water' | 'wave' | 'air'
  /** Stress anchors: value at stress 0 (ideal), 1 (healthy edge), 2 (danger edge) and 3, per side. */
  stress: { ideal: number; low?: [number, number, number]; high?: [number, number, number] }
}

export const SENSORS: readonly SensorSpec[] = [
  {
    id: 'dissolved_oxygen', name: 'Dissolved oxygen', short: 'Oxygen', group: 'water',
    hint: 'Oxygen in the water that roots and fish need', unit: 'mg/L', decimals: 1,
    preset: 6.2, wobble: 0.2, danger: { target: 1.6, min: 1.4, max: 1.8 }, offsetAmp: 0.6,
    stress: { ideal: 6.2, low: [5.0, 2.0, 0.5] },
  },
  {
    id: 'salinity', name: 'Salinity', short: 'Salinity', group: 'water',
    hint: 'How salty the water is', unit: 'PSU', decimals: 1,
    preset: 28, wobble: 1.0, danger: { target: 48, min: 47, max: 49 }, offsetAmp: 4,
    stress: { ideal: 28, high: [35, 45, 55] },
  },
  {
    id: 'turbidity', name: 'Turbidity', short: 'Turbidity', group: 'water',
    hint: 'How muddy or cloudy the water is', unit: 'NTU', decimals: 0,
    preset: 18, wobble: 3, danger: { target: 140, min: 130, max: 150 }, offsetAmp: 3,
    stress: { ideal: 18, high: [25, 100, 180] },
  },
  {
    id: 'ph', name: 'pH', short: 'pH', group: 'water',
    hint: 'How acidic or alkaline the water is', unit: '', decimals: 2,
    preset: 7.8, wobble: 0.08, danger: { target: 6.3, min: 6.2, max: 6.4 }, offsetAmp: 0.3,
    stress: { ideal: 7.8, low: [7.0, 6.5, 6.0], high: [8.5, 9.0, 9.5] },
  },
  {
    id: 'wave_height', name: 'Wave height', short: 'Wave height', group: 'wave',
    hint: 'How high the waves reach the roots', unit: 'm', decimals: 2,
    preset: 0.3, wobble: 0.06, danger: { target: 1.4, min: 1.3, max: 1.5 }, offsetAmp: 0.08,
    stress: { ideal: 0.3, high: [0.5, 1.0, 1.6] },
  },
  {
    id: 'wave_velocity', name: 'Wave velocity', short: 'Wave velocity', group: 'wave',
    hint: 'How fast the water hits the roots', unit: 'm/s', decimals: 2,
    preset: 0.25, wobble: 0.05, danger: { target: 1.35, min: 1.25, max: 1.45 }, offsetAmp: 0.08,
    stress: { ideal: 0.25, high: [0.5, 1.0, 1.6] },
  },
  {
    id: 'temperature', name: 'Temperature', short: 'Temperature', group: 'air',
    hint: 'Air temperature around the trees', unit: '°C', decimals: 1,
    preset: 29, wobble: 0.6, danger: null, offsetAmp: 1.0,
    stress: { ideal: 29, low: [20, 15, 10], high: [32, 36, 40] },
  },
  {
    id: 'humidity', name: 'Humidity', short: 'Humidity', group: 'air',
    hint: 'Moisture in the air', unit: '%', decimals: 0,
    preset: 78, wobble: 3, danger: null, offsetAmp: 5,
    stress: { ideal: 78, low: [50, 40, 30] },
  },
  {
    id: 'soil_moisture', name: 'Soil moisture', short: 'Soil moisture', group: 'air',
    hint: 'How wet the mud is', unit: '%', decimals: 0,
    preset: 82, wobble: 2, danger: null, offsetAmp: 6,
    stress: { ideal: 82, low: [70, 50, 30] },
  },
]

export const SENSOR_BY_ID = Object.fromEntries(SENSORS.map((s) => [s.id, s])) as Record<SensorId, SensorSpec>
export const SENSOR_IDS = SENSORS.map((s) => s.id)

export type Reading = Record<SensorId, number>

export function roundTo(v: number, decimals: number): number {
  const f = 10 ** decimals
  return Math.round(v * f) / f
}

/** The Band of one value, judged on the value as displayed so the number and the chip always agree. */
export function bandOf(id: SensorId, raw: number): Band {
  const v = roundTo(raw, SENSOR_BY_ID[id].decimals)
  switch (id) {
    case 'dissolved_oxygen':
      return v >= 5 ? 'healthy' : v >= 2 ? 'warning' : 'danger'
    case 'salinity':
      return v <= 35 ? 'healthy' : v <= 45 ? 'warning' : 'danger'
    case 'turbidity':
      return v <= 25 ? 'healthy' : v <= 100 ? 'warning' : 'danger'
    case 'ph':
      return v >= 7 && v <= 8.5 ? 'healthy' : v >= 6.5 && v <= 9 ? 'warning' : 'danger'
    case 'wave_height':
      return v <= 0.5 ? 'healthy' : v <= 1.0 ? 'warning' : 'danger'
    case 'wave_velocity':
      return v <= 0.5 ? 'healthy' : v <= 1.0 ? 'warning' : 'danger'
    case 'temperature':
      return v >= 20 && v <= 32 ? 'healthy' : v >= 15 && v <= 36 ? 'warning' : 'danger'
    case 'humidity':
      return v >= 50 ? 'healthy' : v >= 40 ? 'warning' : 'danger'
    case 'soil_moisture':
      return v >= 70 ? 'healthy' : v >= 50 ? 'warning' : 'danger'
  }
}

const RANK: Record<Band, number> = { healthy: 0, warning: 1, danger: 2 }

/** The Level is the Floor: the worst Band across the nine Sensors. */
export function levelOf(r: Reading): Band {
  let worst: Band = 'healthy'
  for (const id of SENSOR_IDS) {
    const b = bandOf(id, r[id])
    if (RANK[b] > RANK[worst]) worst = b
  }
  return worst
}

export function sensorsIn(r: Reading, band: Band): SensorId[] {
  return SENSOR_IDS.filter((id) => bandOf(id, r[id]) === band)
}

/** Continuous stress: 0 ideal, 1 at the healthy edge, 2 at the danger edge, up to 3. */
export function stressOf(id: SensorId, v: number): number {
  const s = SENSOR_BY_ID[id].stress
  const side = (a: [number, number, number]) => {
    const pts = [s.ideal, a[0], a[1], a[2]]
    const dir = Math.sign(a[0] - s.ideal)
    const d = (v - s.ideal) * dir
    if (d <= 0) return 0
    for (let i = 0; i < 3; i++) {
      const lo = (pts[i] - s.ideal) * dir
      const hi = (pts[i + 1] - s.ideal) * dir
      if (d <= hi) return i + (d - lo) / (hi - lo)
    }
    return 3
  }
  let out = 0
  if (s.low && v < s.ideal) out = side(s.low)
  if (s.high && v > s.ideal) out = side(s.high)
  return Math.min(3, out)
}

export function formatReading(id: SensorId, v: number): string {
  const spec = SENSOR_BY_ID[id]
  if (!Number.isFinite(v)) return '—'
  return roundTo(v, spec.decimals).toLocaleString('en-MY', {
    minimumFractionDigits: spec.decimals,
    maximumFractionDigits: spec.decimals,
  })
}

export function listSensors(ids: SensorId[]): string {
  const names = ids.map((id, i) => (i === 0 || id === 'ph' ? SENSOR_BY_ID[id].name : SENSOR_BY_ID[id].name.toLowerCase()))
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}
