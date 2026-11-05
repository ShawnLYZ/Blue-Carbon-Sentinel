import { useEffect, useRef, useState, type ReactNode } from 'react'
import mapboxgl from 'mapbox-gl'
import { Camera } from 'lucide-react'
import { MAPBOX_TOKEN, MAP_STYLES, MapMarker, MapUnavailable, watchMapFailure } from './mapbox'
import { FOOTPRINT_BOUNDS, FOOTPRINT_RING, ringToLngLat } from '../geo/geo'
import { REPLANT_PATCHES, STATION_LATLNG, type PatchId } from '../site/catalogue'
import type { Handover } from '../app/handover'
import { prefersReducedMotion } from '../ui/hooks'

const MARGIN = 0.004

export interface FootprintMapProps {
  padding?: number
  interactive?: boolean
  handover?: Handover | null
  showStation?: boolean
  stationDanger?: boolean
  planted?: PatchId[]
  highlight?: PatchId | null
  onReady?(map: mapboxgl.Map): void
  children?: ReactNode
}

function patchFeatures(ids: PatchId[]) {
  return {
    type: 'FeatureCollection' as const,
    features: REPLANT_PATCHES.filter((p) => ids.includes(p.id)).map((p) => ({
      type: 'Feature' as const,
      properties: { id: p.id },
      geometry: { type: 'Polygon' as const, coordinates: [ringToLngLat(p.ring)] },
    })),
  }
}

/** The real satellite image of the 500 x 500 m Footprint: north-up, no tilt, thin white outline. */
export function FootprintMap({
  padding = 24, interactive = true, handover, showStation, stationDanger, planted = [], highlight = null, onReady, children,
}: FootprintMapProps) {
  const host = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<mapboxgl.Map | null>(null)
  const [failed, setFailed] = useState(!MAPBOX_TOKEN)
  const [imgGone, setImgGone] = useState(false)
  const [image] = useState(handover?.image ?? null)

  useEffect(() => {
    if (!host.current || !MAPBOX_TOKEN) return
    const el = host.current
    const [w, s, e, n] = FOOTPRINT_BOUNDS
    let start: Partial<mapboxgl.MapOptions> = { bounds: [w, s, e, n], fitBoundsOptions: { padding } }
    if (handover) {
      const scale = Math.max(el.clientWidth / handover.width, el.clientHeight / handover.height)
      start = { center: handover.center, zoom: handover.zoom + Math.log2(scale) }
    }
    let m: mapboxgl.Map
    try {
      m = new mapboxgl.Map({
        container: el,
        style: MAP_STYLES.satellite,
        ...start,
        attributionControl: false,
        dragRotate: false,
        pitchWithRotate: false,
        maxPitch: 0,
        bearing: 0,
        interactive,
        ...(interactive ? { maxBounds: [w - MARGIN, s - MARGIN, e + MARGIN, n + MARGIN] as [number, number, number, number] } : {}),
      })
    } catch {
      setFailed(true)
      return
    }
    m.addControl(new mapboxgl.AttributionControl({ compact: true }), 'bottom-right')
    m.addControl(new mapboxgl.ScaleControl({ unit: 'metric', maxWidth: 120 }), 'bottom-left')
    m.touchZoomRotate.disableRotation()
    m.keyboard.disableRotation()
    watchMapFailure(m, () => setFailed(true))
    m.on('load', () => {
      m.addSource('footprint', {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: FOOTPRINT_RING } },
      })
      m.addLayer({ id: 'footprint', type: 'line', source: 'footprint', paint: { 'line-color': '#ffffff', 'line-width': 2, 'line-opacity': 0.95 } })
      m.addSource('patches', { type: 'geojson', data: patchFeatures([]) })
      m.addLayer({ id: 'patches-fill', type: 'fill', source: 'patches', paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.12 } })
      m.addLayer({ id: 'patches-line', type: 'line', source: 'patches', paint: { 'line-color': '#ffffff', 'line-width': 2.5, 'line-dasharray': [2, 1.5] } })
      m.addSource('target', { type: 'geojson', data: patchFeatures([]) })
      m.addLayer({ id: 'target-fill', type: 'fill', source: 'target', paint: { 'fill-color': '#7CF2D8', 'fill-opacity': 0.28 } })
      m.addLayer({ id: 'target-line', type: 'line', source: 'target', paint: { 'line-color': '#7CF2D8', 'line-width': 3 } })
      setMap(m)
      onReady?.(m)
      if (handover) {
        const reveal = () => {
          setImgGone(true)
          m.fitBounds([w, s, e, n], { padding, duration: prefersReducedMotion() ? 0 : 1400, essential: true })
        }
        const t = setTimeout(reveal, 2500)
        m.once('idle', () => { clearTimeout(t); reveal() })
      }
    })
    // Keep the Footprint framed when the panel changes size, until the visitor moves the map.
    let moved = false
    m.on('dragstart', () => { moved = true })
    m.on('zoomstart', (ev) => { if ((ev as { originalEvent?: Event }).originalEvent) moved = true })
    const ro = new ResizeObserver(() => {
      m.resize()
      if (!moved && !handover) m.fitBounds([w, s, e, n], { padding, duration: 0 })
    })
    ro.observe(el)
    return () => {
      ro.disconnect()
      m.remove()
      setMap(null)
    }
    // Created once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Planted patches: dashed white outlines.
  const plantedKey = planted.join(',')
  useEffect(() => {
    const src = map?.getSource('patches') as mapboxgl.GeoJSONSource | undefined
    src?.setData(patchFeatures(planted))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, plantedKey])

  // The scan target pulses.
  useEffect(() => {
    if (!map) return
    const src = map.getSource('target') as mapboxgl.GeoJSONSource | undefined
    src?.setData(patchFeatures(highlight ? [highlight] : []))
    if (!highlight) return
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = (Math.sin(((now - t0) / 1000) * Math.PI * 1.6) + 1) / 2
      if (map.getLayer('target-line')) {
        map.setPaintProperty('target-line', 'line-width', 2.5 + p * 3.5)
        map.setPaintProperty('target-fill', 'fill-opacity', 0.18 + p * 0.22)
      }
      raf = requestAnimationFrame(tick)
    }
    if (!prefersReducedMotion()) raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [map, highlight])

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <div ref={host} style={{ position: 'absolute', inset: 0 }} />
      {image && <img className={`handover-img ${imgGone ? 'gone' : ''}`} src={image} alt="" />}
      {failed && <MapUnavailable />}
      {map && showStation && (
        <MapMarker map={map} lngLat={[STATION_LATLNG.lng, STATION_LATLNG.lat]}>
          <div className={`marker-station ${stationDanger ? 'danger' : ''}`} title="Sentinel Station">
            <Camera size={16} strokeWidth={2.4} />
          </div>
        </MapMarker>
      )}
      {map && children}
    </div>
  )
}
