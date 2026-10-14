import { useEffect } from 'react'
import { Layer, Source, useMap } from 'react-map-gl/mapbox'
import type { Site } from '@bcs/api-types'

export const MASK_COLOR = '#05121f'
export const BOUNDARY_COLOR = '#3fe0d0'
const PULSE_MS = 2000
/**
 * The pulse repaints the whole map, which competes with DirectML depth inference on the same GPU.
 * It steps at 5 Hz (not every animation frame), only while the tab is visible and only when the
 * 500 m square is big enough to see. Measured: each setPaintProperty costs Mapbox two renders, so
 * 5 Hz is about 10 map repaints/s (was one per display frame, about 165/s on a 165 Hz panel).
 */
export const PULSE_INTERVAL_MS = 200
export const PULSE_MIN_ZOOM = 11

export function shouldPulse(zoom: number, hidden: boolean): boolean {
  return !hidden && zoom >= PULSE_MIN_ZOOM
}

/** Opacity of the boundary glow at time t: pulses between 0.5 and 1 over 2 s. */
export function pulseOpacity(tMs: number): number {
  return 0.75 + 0.25 * Math.sin((2 * Math.PI * tMs) / PULSE_MS)
}

/** The Kuala Selangor square: a dark mask over the imagery and a glowing, pulsing boundary. */
export function SiteLayers({ site }: { site: Site }) {
  const { current: ref } = useMap()

  useEffect(() => {
    const map = ref?.getMap()
    if (!map) return
    let timer: ReturnType<typeof setInterval> | undefined
    let loaded = map.loaded()
    const tick = () => {
      if (!map.getLayer('ksl-boundary') || !shouldPulse(map.getZoom(), document.visibilityState === 'hidden')) return
      map.setPaintProperty('ksl-boundary', 'line-opacity', pulseOpacity(performance.now()))
    }
    // Paint updates before the style has loaded would keep the map from ever reporting "load".
    const sync = () => {
      const run = loaded && document.visibilityState !== 'hidden'
      if (run && timer === undefined) timer = setInterval(tick, PULSE_INTERVAL_MS)
      else if (!run && timer !== undefined) {
        clearInterval(timer)
        timer = undefined
      }
    }
    const onLoad = () => {
      loaded = true
      sync()
    }
    if (loaded) sync()
    else map.once('load', onLoad)
    document.addEventListener('visibilitychange', sync)
    return () => {
      map.off('load', onLoad)
      document.removeEventListener('visibilitychange', sync)
      if (timer !== undefined) clearInterval(timer)
    }
  }, [ref])

  const data = {
    type: 'Feature' as const,
    properties: { id: site.id },
    geometry: site.bounds as never,
  }
  return (
    <Source id="ksl" type="geojson" data={data}>
      <Layer
        id="ksl-mask"
        type="fill"
        slot="top"
        paint={{ 'fill-color': MASK_COLOR, 'fill-opacity': 0.85, 'fill-emissive-strength': 1 }}
      />
      <Layer
        id="ksl-boundary"
        type="line"
        slot="top"
        layout={{ 'line-join': 'round' }}
        paint={{
          'line-color': BOUNDARY_COLOR,
          'line-width': 3,
          'line-blur': 2,
          'line-opacity': 0.75,
          // No paint transition: each step must cost one style update, not 300 ms of repaints.
          'line-opacity-transition': { duration: 0, delay: 0 },
          'line-emissive-strength': 1,
        }}
      />
    </Source>
  )
}
