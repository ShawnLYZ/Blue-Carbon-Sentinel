import { useEffect, useMemo, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import mapboxgl from 'mapbox-gl'
import { Satellite } from 'lucide-react'

export const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN ?? ''
mapboxgl.accessToken = MAPBOX_TOKEN

export const MAP_STYLES = {
  globe: 'mapbox://styles/mapbox/satellite-streets-v12',
  satellite: 'mapbox://styles/mapbox/satellite-v9',
} as const

export const MAP_UNAVAILABLE = 'Satellite image unavailable: check the internet connection or Mapbox token'

/** Watches a map for a missing or rejected token and calls back once. */
export function watchMapFailure(map: mapboxgl.Map, onFail: () => void) {
  let failed = false
  map.on('error', (e: { error?: { status?: number; message?: string } }) => {
    const status = e.error?.status
    const msg = e.error?.message ?? ''
    if (failed) return
    if (status === 401 || status === 403 || /access token|Unauthorized|Forbidden/i.test(msg)) {
      failed = true
      onFail()
    }
  })
}

export function MapUnavailable() {
  return (
    <div className="map-unavailable" role="alert" data-testid="map-unavailable">
      <div>
        <Satellite size={28} />
        <p>{MAP_UNAVAILABLE}</p>
      </div>
    </div>
  )
}

/** A Mapbox marker whose content is rendered by React. */
export function MapMarker({
  map, lngLat, children, anchor = 'center', offset, zIndex,
}: {
  map: mapboxgl.Map
  lngLat: [number, number]
  children: ReactNode
  anchor?: mapboxgl.Anchor
  offset?: [number, number]
  zIndex?: number
}) {
  const el = useMemo(() => document.createElement('div'), [])
  useEffect(() => {
    const marker = new mapboxgl.Marker({ element: el, anchor, offset }).setLngLat(lngLat).addTo(map)
    return () => { marker.remove() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, el, anchor, offset?.[0], offset?.[1], lngLat[0], lngLat[1]])
  useEffect(() => {
    el.style.zIndex = zIndex != null ? String(zIndex) : ''
  }, [el, zIndex])
  return createPortal(children, el)
}
