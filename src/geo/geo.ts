// Local metres <-> latitude/longitude for the Kuala Selangor Footprint (PRD decision 5).
// x runs east and z runs south, in metres from the Footprint centre.

export interface LatLng {
  lat: number
  lng: number
}

export const CENTRE: LatLng = { lat: 3.33656, lng: 101.23674 }
export const M_PER_DEG_LAT = 111_320
const M_PER_DEG_LNG = M_PER_DEG_LAT * Math.cos((CENTRE.lat * Math.PI) / 180)
export const HALF = 250

export function toLatLng(x: number, z: number): LatLng {
  return { lat: CENTRE.lat - z / M_PER_DEG_LAT, lng: CENTRE.lng + x / M_PER_DEG_LNG }
}

export function toLocal(p: LatLng): { x: number; z: number } {
  return { x: (p.lng - CENTRE.lng) * M_PER_DEG_LNG, z: (CENTRE.lat - p.lat) * M_PER_DEG_LAT }
}

export function formatLat(lat: number): string {
  return `${Math.abs(lat).toFixed(6)}° ${lat >= 0 ? 'N' : 'S'}`
}

export function formatLng(lng: number): string {
  return `${Math.abs(lng).toFixed(6)}° ${lng >= 0 ? 'E' : 'W'}`
}

export function formatLatLng(p: LatLng): string {
  return `${formatLat(p.lat)}, ${formatLng(p.lng)}`
}

const sw = toLatLng(-HALF, HALF)
const ne = toLatLng(HALF, -HALF)

/** The Footprint's bounding box as [west, south, east, north]. */
export const FOOTPRINT_BOUNDS: [number, number, number, number] = [sw.lng, sw.lat, ne.lng, ne.lat]

/** The Footprint outline as a closed GeoJSON ring of [lng, lat]. */
export const FOOTPRINT_RING: [number, number][] = [
  [sw.lng, ne.lat],
  [ne.lng, ne.lat],
  [ne.lng, sw.lat],
  [sw.lng, sw.lat],
  [sw.lng, ne.lat],
]

/** Converts a flat local ring [x0, z0, x1, z1, ...] into a closed GeoJSON ring. */
export function ringToLngLat(ring: readonly number[]): [number, number][] {
  const out: [number, number][] = []
  for (let i = 0; i < ring.length; i += 2) {
    const p = toLatLng(ring[i], ring[i + 1])
    out.push([p.lng, p.lat])
  }
  if (out.length) out.push(out[0])
  return out
}
