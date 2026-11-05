import { CENTRE, toLatLng, type LatLng } from '../geo/geo'
import { PATCH_OUTLINES } from './canopyOutlines'

export const LIVE_SITE = {
  id: 'ksl',
  name: 'Kuala Selangor Nature Park',
  shortName: 'Kuala Selangor',
  region: 'Selangor',
  centre: CENTRE,
  sizeM: 500,
} as const

export interface ComingSoonSite {
  id: string
  name: string
  region: string
  centre: LatLng
}

export const COMING_SOON_SITES: readonly ComingSoonSite[] = [
  { id: 'pulau-ketam', name: 'Pulau Ketam', region: 'Selangor', centre: { lat: 3.0215, lng: 101.2565 } },
  { id: 'kukup', name: 'Kukup Island National Park', region: 'Johor', centre: { lat: 1.325, lng: 103.4245 } },
  { id: 'kuching-wetlands', name: 'Kuching Wetlands National Park', region: 'Sarawak', centre: { lat: 1.7, lng: 110.405 } },
  { id: 'semporna', name: 'Semporna marine park fringes', region: 'Sabah', centre: { lat: 4.483, lng: 118.615 } },
]

/** The globe framing on Malaysia. */
export const MALAYSIA_VIEW = { center: [109.4, 3.9] as [number, number], zoom: 4.55 }

/** The Sentinel Station: on the forest edge beside the river, picked during tracing. */
export const STATION = { x: -212, z: -148 }
export const STATION_LATLNG = toLatLng(STATION.x, STATION.z)

export interface SensorPost {
  id: string
  name: string
  x: number
  z: number
  /** Only the Sentinel Station streams live; the other posts are read from the Field Model. */
  live: boolean
}

/** How far each post's colour spreads in the Digital Twin, in metres. */
export const POST_RADIUS_M = 55

/** Sensor posts spread over the forest, all on canopy ground. The first is the Sentinel Station. */
export const SENSOR_POSTS: readonly SensorPost[] = [
  { id: 'station', name: 'Sentinel Station', x: STATION.x, z: STATION.z, live: true },
  { id: 'post-2', name: 'Sensor post 2', x: -70, z: -200, live: false },
  { id: 'post-3', name: 'Sensor post 3', x: 60, z: -180, live: false },
  { id: 'post-4', name: 'Sensor post 4', x: 200, z: -150, live: false },
  { id: 'post-5', name: 'Sensor post 5', x: -170, z: -20, live: false },
  { id: 'post-6', name: 'Sensor post 6', x: -20, z: -60, live: false },
  { id: 'post-7', name: 'Sensor post 7', x: 200, z: 60, live: false },
  { id: 'post-8', name: 'Sensor post 8', x: -140, z: 140, live: false },
  { id: 'post-9', name: 'Sensor post 9', x: 40, z: 160, live: false },
  { id: 'post-10', name: 'Sensor post 10', x: 190, z: 210, live: false },
]

export type PatchId = 'patch-1' | 'patch-2' | 'patch-3'

export interface ReplantPatch {
  id: PatchId
  ring: readonly number[]
  areaM2: number
  centroid: { x: number; z: number }
}

/** Replant Patches in catalogue order: real bare or gap areas of the image. */
export const REPLANT_PATCHES: readonly ReplantPatch[] = PATCH_OUTLINES.map((p) => ({
  id: p.id as PatchId,
  ring: p.ring,
  areaM2: p.areaM2,
  centroid: { x: p.centroid[0], z: p.centroid[1] },
}))
