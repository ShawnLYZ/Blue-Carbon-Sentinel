import { fromUrl } from 'geotiff'
import proj4 from 'proj4'

export interface Asset {
  href: string
  'raster:bands'?: { scale?: number; offset?: number; nodata?: number }[]
}
export interface Scene {
  id: string
  properties: { datetime: string; 'eo:cloud_cover': number; 'proj:epsg': number }
  assets: Record<string, Asset>
}
export interface Region { name: string; lat: number; lng: number; size: number }
export interface Raster {
  width: number; height: number; rgb: Uint8ClampedArray; ndvi: Float32Array; valid: Uint8Array
  clearPct: number; vegetationPct: number; meanNdvi: number | null
  /** Original Sentinel-2 SCL codes: vegetation=4, bare ground=5, water=6. */
  classes?: Uint8Array
}
export const KSL: Region = { name: 'Kuala Selangor Nature Park', lat: 3.33656, lng: 101.23674, size: 500 }

export function bounds(r: Region): [number, number, number, number] {
  const dy = r.size / 2 / 111320
  const dx = dy / Math.cos(r.lat * Math.PI / 180)
  return [r.lng - dx, r.lat - dy, r.lng + dx, r.lat + dy]
}

export async function searchScenes(r: Region, signal?: AbortSignal): Promise<Scene[]> {
  const url = new URL('https://earth-search.aws.element84.com/v1/search')
  url.searchParams.set('collections', 'sentinel-2-l2a')
  url.searchParams.set('bbox', bounds(r).join(','))
  url.searchParams.set('limit', '20')
  url.searchParams.set('sortby', '-properties.datetime')
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`Satellite catalogue returned HTTP ${response.status}`)
  const json = await response.json() as { features?: Scene[] }
  return (json.features ?? []).filter(s => ['visual', 'red', 'nir', 'scl'].every(k => s.assets[k]))
}

export function reflectance(raw: number, asset: Asset): number | null {
  const band = asset['raster:bands']?.[0]
  if (!Number.isFinite(raw) || raw === (band?.nodata ?? 0)) return null
  return raw * (band?.scale ?? 0.0001) + (band?.offset ?? 0)
}

export function vegetationIndex(red: number | null, nir: number | null, scl: number): number | null {
  // Only vegetation and bare soil: exclude cloud, shadow, water, snow, unclassified and no-data.
  if ((scl !== 4 && scl !== 5) || red === null || nir === null || red < 0 || nir < 0 || red + nir <= 0) return null
  return Math.max(-1, Math.min(1, (nir - red) / (nir + red)))
}

export async function loadRaster(scene: Scene, region: Region, signal: AbortSignal): Promise<Raster> {
  const epsg = scene.properties['proj:epsg']
  const north = epsg >= 32601 && epsg <= 32660
  const south = epsg >= 32701 && epsg <= 32760
  if (!north && !south) throw new Error('This preview currently supports Sentinel-2 UTM scenes.')
  const crs = `+proj=utm +zone=${epsg % 100} ${south ? '+south' : ''} +datum=WGS84 +units=m +no_defs`
  const b = bounds(region)
  const corners = [[b[0], b[1]], [b[0], b[3]], [b[2], b[1]], [b[2], b[3]]].map(p => proj4('EPSG:4326', crs, p))
  const box = [Math.min(...corners.map(p => p[0]!)), Math.min(...corners.map(p => p[1]!)), Math.max(...corners.map(p => p[0]!)), Math.max(...corners.map(p => p[1]!))]
  const width = Math.round(region.size / 10)
  const height = width
  const read = async (key: string, samples: number[]) => {
    const tiff = await fromUrl(scene.assets[key]!.href, { allowFullFile: false }, signal)
    return await tiff.readRasters({ bbox: box, width, height, samples, interleave: true, resampleMethod: 'nearest', signal })
  }
  const [visual, red, nir, scl] = await Promise.all([read('visual', [0, 1, 2]), read('red', [0]), read('nir', [0]), read('scl', [0])])
  const rgb = new Uint8ClampedArray(width * height * 4)
  const ndvi = new Float32Array(width * height).fill(NaN)
  const valid = new Uint8Array(width * height)
  const classes = new Uint8Array(width * height)
  let clear = 0, vegetation = 0, sum = 0
  for (let i = 0; i < ndvi.length; i++) {
    classes[i] = Number(scl[i])
    rgb.set([Number(visual[i * 3]), Number(visual[i * 3 + 1]), Number(visual[i * 3 + 2]), 255], i * 4)
    const v = vegetationIndex(reflectance(Number(red[i]), scene.assets.red!), reflectance(Number(nir[i]), scene.assets.nir!), Number(scl[i]))
    if (v === null) continue
    ndvi[i] = v; valid[i] = 1; clear++; sum += v
    if (v >= 0.35) vegetation++
  }
  return { width, height, rgb, ndvi, valid, classes, clearPct: 100 * clear / ndvi.length, vegetationPct: 100 * vegetation / ndvi.length, meanNdvi: clear ? sum / clear : null }
}
