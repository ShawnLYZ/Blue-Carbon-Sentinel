// Lifts the reality surface just above Mapbox terrain: react-three-map places the scene at
// altitude 0, and the DEM under a coastal site is a few metres above sea level.
import type { Site } from '@bcs/api-types'

export interface TerrainQuery {
  queryTerrainElevation(lngLat: [number, number], options?: { exaggerated: boolean }): number | null | undefined
}

export interface SiteBounds {
  west: number
  east: number
  north: number
  south: number
}

export const TERRAIN_CLEARANCE_M = 0.5

/** Max terrain elevation over the four corners and the centre, plus 0.5 m. No terrain -> 0.5. */
export function terrainBaseMetres(map: TerrainQuery, siteBounds: SiteBounds): number {
  const { west, east, north, south } = siteBounds
  const points: [number, number][] = [
    [west, north],
    [east, north],
    [east, south],
    [west, south],
    [(west + east) / 2, (north + south) / 2],
  ]
  let best: number | null = null
  for (const p of points) {
    let h: number | null | undefined
    try {
      h = map.queryTerrainElevation(p, { exaggerated: false })
    } catch {
      h = null
    }
    if (typeof h === 'number' && Number.isFinite(h)) best = best === null ? h : Math.max(best, h)
  }
  return (best ?? 0) + TERRAIN_CLEARANCE_M
}

/** Bounding box of the site polygon (GeoJSON, lng/lat). */
export function siteBounds(site: Pick<Site, 'bounds'>): SiteBounds {
  const ring = ((site.bounds as { coordinates?: number[][][] }).coordinates?.[0] ?? []) as number[][]
  let west = Infinity
  let east = -Infinity
  let north = -Infinity
  let south = Infinity
  for (const [lng, lat] of ring) {
    west = Math.min(west, lng!)
    east = Math.max(east, lng!)
    north = Math.max(north, lat!)
    south = Math.min(south, lat!)
  }
  return { west, east, north, south }
}
