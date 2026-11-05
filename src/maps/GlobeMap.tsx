import { useEffect, useRef, useState, type ReactNode } from 'react'
import mapboxgl from 'mapbox-gl'
import { MAPBOX_TOKEN, MAP_STYLES, MapUnavailable, watchMapFailure } from './mapbox'
import { MALAYSIA_VIEW } from '../site/catalogue'

export function GlobeMap({ onReady, padding, children }: {
  onReady(map: mapboxgl.Map | null): void
  padding: mapboxgl.PaddingOptions
  children?: ReactNode
}) {
  const host = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(!MAPBOX_TOKEN)

  useEffect(() => {
    if (!host.current || !MAPBOX_TOKEN) return
    let map: mapboxgl.Map
    try {
      map = new mapboxgl.Map({
        container: host.current,
        style: MAP_STYLES.globe,
        projection: 'globe',
        center: MALAYSIA_VIEW.center,
        // Frame all of Malaysia in the space beside the Sites panel, whatever the screen width.
        zoom: MALAYSIA_VIEW.zoom + Math.log2(Math.min(1.15, Math.max(0.45, (host.current.clientWidth - 420) / 1020))),
        attributionControl: false,
        logoPosition: 'bottom-right',
        preserveDrawingBuffer: true,
        dragRotate: false,
        pitchWithRotate: false,
        maxPitch: 0,
        cooperativeGestures: false,
      })
    } catch {
      setFailed(true)
      return
    }
    map.setPadding(padding)
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), 'bottom-right')
    map.touchZoomRotate.disableRotation()
    map.on('style.load', () => {
      // Our pins sit on top of city names; hide settlement labels so none are half covered.
      for (const layer of map.getStyle().layers ?? []) {
        if (layer.type === 'symbol' && /settlement|place-label|poi|state-label/.test(layer.id)) map.setLayoutProperty(layer.id, 'visibility', 'none')
        // Only Malaysia is named: other country names would sit under the tiles or the pins.
        if (layer.type === 'symbol' && /country-label/.test(layer.id)) {
          const onlyMalaysia = ['==', ['get', 'name_en'], 'Malaysia']
          const f = map.getFilter(layer.id)
          map.setFilter(layer.id, (f ? ['all', f, onlyMalaysia] : onlyMalaysia) as mapboxgl.FilterSpecification)
        }
      }
      map.setFog({
        range: [0.8, 8],
        color: '#F4F8F6',
        'high-color': '#BFD7E3',
        'horizon-blend': 0.06,
        'space-color': '#EAF0ED',
        'star-intensity': 0,
      })
    })
    watchMapFailure(map, () => setFailed(true))
    map.once('load', () => onReady(map))
    return () => {
      onReady(null)
      map.remove()
    }
    // The map is created once; padding changes are applied by the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="globe" data-testid="globe-map">
      <div ref={host} style={{ position: 'absolute', inset: 0 }} />
      {failed && <MapUnavailable />}
      {children}
    </div>
  )
}
