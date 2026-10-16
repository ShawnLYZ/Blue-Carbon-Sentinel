import type { Node } from '@bcs/api-types'
import { idwGrid, maskFromClasses } from '../lib/idw'
import { fieldPoints } from '../twin/FieldOverlay'
import type { CaptureRasters } from '../twin/captureRasters'
import type { FieldKey } from '../twin/layers'
import type { Raster } from './satellite'
import { ATTRIBUTE_META, type Attribute, type RiskZone } from './scenarioRisk'

export type SurfacePaint = 'none' | 'ndvi' | 'classes' | 'cameraNdvi' | 'cameraClasses' | Exclude<Attribute, 'ndvi'>
export const FIELD_KEYS: Record<Exclude<Attribute, 'ndvi'>, FieldKey> = {
  salinity: 'water:salinity_psu', oxygen: 'water:do_mg_l', turbidity: 'water:turbidity_ntu', temperature: 'water:temp_c', ph: 'water:ph', soilSalinity: 'soil:porewater_salinity_psu', soilMoisture: 'soil:soil_moisture_pct',
}
export const CLASS_COLOURS = { 0: [55, 65, 77], 1: [34, 139, 34], 2: [30, 100, 200], 3: [139, 101, 60], 4: [170, 170, 170] } as const
export function satelliteClass(scl: number): 0 | 1 | 2 | 3 { return scl === 4 ? 1 : scl === 6 ? 2 : scl === 5 ? 3 : 0 }

/** The returned RGB is used for the floor only; analysis always uses the original satellite raster. */
export function paintSurface(raster: Raster | null, zones: RiskZone[], mode: SurfacePaint, captures: CaptureRasters | null, nodes: Node[], liveFields: boolean): Raster | null {
  if (!raster || mode === 'none') return raster
  if (mode === 'cameraNdvi' && !captures?.ndvi || mode === 'cameraClasses' && !captures?.classes) return raster
  const rgb = new Uint8ClampedArray(raster.rgb.length)
  const field = !['ndvi', 'classes', 'cameraNdvi', 'cameraClasses'].includes(mode) ? mode as Exclude<Attribute, 'ndvi'> : null
  let fieldGrid: Float32Array | null = null
  const soil = field === 'soilSalinity' || field === 'soilMoisture'
  const classes = captures?.classes ?? (raster.classes ? Uint8Array.from(raster.classes, satelliteClass) : null)
  const classSize = captures?.classes ? 256 : raster.width
  const mask = classes ? maskFromClasses(classes, classSize, soil ? 'land' : 'water', raster.width) : new Uint8Array(raster.width * raster.height).fill(1)
  if (field && liveFields) fieldGrid = idwGrid(fieldPoints(nodes, FIELD_KEYS[field]), mask, raster.width)
  for (let y = 0; y < raster.height; y++) for (let x = 0; x < raster.width; x++) {
    const i = y * raster.width + x
    let colour: readonly number[] = [55, 65, 77]
    const ci = Math.min(255, Math.floor(y / raster.height * 256)) * 256 + Math.min(255, Math.floor(x / raster.width * 256))
    if (mode === 'classes') colour = CLASS_COLOURS[satelliteClass(raster.classes?.[i] ?? 0)]
    else if (mode === 'cameraClasses') colour = CLASS_COLOURS[(captures!.classes![ci] ?? 0) as keyof typeof CLASS_COLOURS] ?? CLASS_COLOURS[0]
    else if (mode === 'ndvi' || mode === 'cameraNdvi') {
      const v = mode === 'ndvi' ? raster.valid[i] ? raster.ndvi[i]! : NaN : captures!.ndvi![ci]! / 255 * 2 - 1
      if (Number.isFinite(v)) colour = [Math.round(185 - Math.max(0, v) * 140), Math.round(110 + Math.max(0, v) * 80), 60]
    } else if (field) {
      const zone = zones[Math.min(4, Math.floor(y / raster.height * 5)) * 5 + Math.min(4, Math.floor(x / raster.width * 5))]!
      const v = liveFields ? fieldGrid?.[i] ?? NaN : zone.inputs[field]
      // Live fields use water/land masks. Scenario fields remain spatial assumptions, marked in the UI.
      if (Number.isFinite(v) && (liveFields ? !!mask[i] : !!raster.valid[i])) {
        const meta = ATTRIBUTE_META[field]
        const t = Math.max(0, Math.min(1, (v - meta.min) / (meta.max - meta.min)))
        colour = [Math.round(35 + 210 * t), Math.round(80 + 110 * t), Math.round(190 - 140 * t)]
      }
    }
    rgb.set([colour[0]!, colour[1]!, colour[2]!, 255], i * 4)
  }
  return { ...raster, rgb }
}
