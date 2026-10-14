// Digital Twin layer keys (design §26) and the display ranges and ramps the overlays and the legend share.
import { create } from 'zustand'
import { paramMeta } from '../data/network'

export const WATER_FIELDS = ['salinity_psu', 'turbidity_ntu', 'do_mg_l', 'temp_c', 'ph'] as const
export const SOIL_FIELDS = ['porewater_salinity_psu', 'soil_moisture_pct'] as const

export type FieldKey = `water:${(typeof WATER_FIELDS)[number]}` | `soil:${(typeof SOIL_FIELDS)[number]}`
export type OverlayKey = 'ndvi' | 'classes' | FieldKey
export type LayerKey =
  | 'reality'
  | 'grid'
  | 'risk'
  | 'carbon'
  | 'nodes'
  | 'coverage'
  | 'tasking'
  | 'trees'
  | 'alerts'
  | OverlayKey

/** Every overlay texture layer; the surface blends one overlay at a time, so these are exclusive. */
export const OVERLAY_KEYS: readonly OverlayKey[] = [
  'ndvi',
  'classes',
  ...WATER_FIELDS.map((p) => `water:${p}` as const),
  ...SOIL_FIELDS.map((p) => `soil:${p}` as const),
]

/** Layers shown until the operator switches them off. Overlays start off. */
export const LAYER_DEFAULTS: Partial<Record<LayerKey, boolean>> = {
  reality: true,
  grid: true,
  risk: true,
  nodes: true,
  coverage: true,
  tasking: true,
  trees: true,
  alerts: true,
}

/** Sub-option of the risk layer: extrude the tiles into columns by risk score. */
export const RISK_COLUMNS_KEY = 'risk:columns'

export function layerOn(layers: Record<string, boolean>, key: string): boolean {
  return layers[key] ?? LAYER_DEFAULTS[key as LayerKey] ?? false
}

/** The overlay currently switched on (the first in OVERLAY_KEYS order if several are). */
export function activeOverlay(layers: Record<string, boolean>): OverlayKey | null {
  return OVERLAY_KEYS.find((k) => layerOn(layers, k)) ?? null
}

/** The `ui.layers` changes for switching `key` to `on`: an overlay switched on turns the others off. */
export function layerChanges(key: string, on: boolean): Record<string, boolean> {
  const out: Record<string, boolean> = { [key]: on }
  if (on && (OVERLAY_KEYS as readonly string[]).includes(key)) for (const k of OVERLAY_KEYS) if (k !== key) out[k] = false
  return out
}

export function isFieldKey(key: string | null): key is FieldKey {
  return key !== null && (key.startsWith('water:') || key.startsWith('soil:'))
}

/** The node reading behind a field layer, e.g. "water:turbidity_ntu" -> "turbidity_ntu". */
export function fieldParam(key: FieldKey): string {
  return key.slice(key.indexOf(':') + 1)
}

/** Fixed legend ranges per field (design §10 sensor ranges), so colours mean the same thing across frames. */
export const FIELD_RANGES: Record<string, [number, number]> = {
  salinity_psu: [0, 40],
  turbidity_ntu: [0, 200],
  do_mg_l: [0, 10],
  temp_c: [24, 36],
  ph: [6, 9],
  porewater_salinity_psu: [0, 60],
  soil_moisture_pct: [0, 100],
}

export interface FieldLegend {
  label: string
  unit: string
  min: number
  max: number
  dp: number
}

export function fieldLegend(key: FieldKey): FieldLegend {
  const p = fieldParam(key)
  const meta = paramMeta(p)
  const [min, max] = FIELD_RANGES[p] ?? [0, 1]
  return { label: meta.label, unit: meta.unit, min, max, dp: Math.min(meta.dp, 1) }
}

/** Field ramp stops (0..1 -> RGB 0..1), low = deep blue, high = hot yellow; mirrored in the shader. */
export const FIELD_RAMP: [number, number, number][] = [
  [0.13, 0.19, 0.55],
  [0.13, 0.57, 0.55],
  [0.37, 0.79, 0.38],
  [0.99, 0.91, 0.15],
]

/** NDVI-proxy (VARI) ramp: bare/brown -> yellow -> green over VARI -0.1 .. 0.4. */
export const NDVI_RAMP: [number, number, number][] = [
  [0.55, 0.35, 0.17],
  [0.93, 0.85, 0.36],
  [0.1, 0.62, 0.2],
]
export const NDVI_RANGE: [number, number] = [-0.1, 0.4]

/** Class palette (addendum F5 codes): 0 unclassified, 1 canopy, 2 water, 3 mud, 4 other. */
export const CLASS_PALETTE: { code: number; label: string; rgb: [number, number, number] }[] = [
  { code: 0, label: 'Unclassified', rgb: [0, 0, 0] },
  { code: 1, label: 'Canopy', rgb: [34, 139, 34] },
  { code: 2, label: 'Water', rgb: [30, 100, 200] },
  { code: 3, label: 'Mud', rgb: [139, 101, 60] },
  { code: 4, label: 'Other', rgb: [170, 170, 170] },
]

export function rampCss(stops: [number, number, number][]): string {
  const c = stops.map(([r, g, b], i) => `rgb(${Math.round(r * 255)} ${Math.round(g * 255)} ${Math.round(b * 255)}) ${((i / (stops.length - 1)) * 100).toFixed(0)}%`)
  return `linear-gradient(90deg, ${c.join(', ')})`
}

/** What the overlay layer drew, for the legend (outside the WebGL canvas). */
export interface OverlayStatus {
  /** The class map the fields are clipped with: from the latest capture, or none (fields unclipped). */
  classMap: 'loading' | 'ok' | 'none'
  ndvi: 'loading' | 'ok' | 'none'
  /** Node readings behind the active field. */
  points: number
}

export const useOverlayStatus = create<OverlayStatus>()(() => ({ classMap: 'loading', ndvi: 'loading', points: 0 }))
