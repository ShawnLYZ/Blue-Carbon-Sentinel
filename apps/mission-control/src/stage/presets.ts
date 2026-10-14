export type PresetKey = 'globe' | 'site-nadir' | 'site-oblique' | 'site-orbit'

export interface CameraPreset {
  center: [number, number] // [lng, lat]
  zoom: number
  pitch: number
  bearing: number
}

export const GLOBE_CENTER: [number, number] = [109.5, 4.0]

/** Camera for a preset; site presets need the site centre (lng, lat). */
export function presetCamera(key: PresetKey, siteCentre: [number, number] | null): CameraPreset {
  const c = siteCentre ?? GLOBE_CENTER
  switch (key) {
    case 'globe':
      return { center: GLOBE_CENTER, zoom: 4.2, pitch: 0, bearing: 0 }
    case 'site-nadir':
      return { center: c, zoom: 16.4, pitch: 0, bearing: 0 }
    case 'site-oblique':
      return { center: c, zoom: 16.0, pitch: 55, bearing: -20 }
    case 'site-orbit':
      return { center: c, zoom: 16.2, pitch: 60, bearing: 30 }
  }
}

/** Which camera each page uses; pages not listed leave the camera where it is. */
export const PAGE_PRESETS: Partial<Record<string, PresetKey>> = {
  command: 'globe',
  satellite: 'site-nadir',
  network: 'site-oblique',
  ledger: 'site-oblique',
  twin: 'site-orbit',
}

/** Cinematic flight length (ms) per page's preset; design §26 allows 1.5-3 s. */
export const PAGE_FLIGHT_MS: Partial<Record<string, number>> = {
  command: 2800, // the long way back out to the globe
  satellite: 2200,
  network: 2000,
  ledger: 1800,
  twin: 2600, // the orbit view is the showpiece
}
export const DEFAULT_FLIGHT_MS = 2000
