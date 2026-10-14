import { Component, Suspense, createRef, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Map, Source, type MapRef, type ViewStateChangeEvent } from 'react-map-gl/mapbox'
import 'mapbox-gl/dist/mapbox-gl.css'
import { useAppStore } from '../data/store'
import { DEFAULT_FLIGHT_MS, PAGE_FLIGHT_MS, PAGE_PRESETS, presetCamera, type PresetKey } from './presets'
import { PlannedSiteMarkers } from './PlannedSiteMarkers'
import { SiteLayers } from './siteLayers'
import { setLiveFeedSuspended } from '../twin/liveFeed'

/** The one persistent map; later milestones mount their layers through this ref. */
export const stageRef = createRef<MapRef>()

function siteCentre(): [number, number] | null {
  const c = useAppStore.getState().site.site?.centre
  return c ? [c.lng, c.lat] : null
}

export function flyToPreset(key: PresetKey, durationMs = 2000): void {
  const map = stageRef.current
  if (!map) return
  const cam = presetCamera(key, siteCentre())
  if (durationMs <= 0) map.jumpTo(cam)
  else map.flyTo({ ...cam, duration: durationMs, essential: true })
}

export function UnavailablePanel({ reason }: { reason: string }) {
  return (
    <div className="stage-unavailable" role="status">
      <div className="bcs-panel stage-unavailable__card">
        <div className="stage-unavailable__glyph" aria-hidden="true" />
        <strong>Map unavailable: {reason}</strong>
        <span>Every page, status chip and alert still works without the map.</span>
      </div>
    </div>
  )
}

export class MapBoundary extends Component<{ children: ReactNode }, { reason: string | null }> {
  state = { reason: null as string | null }
  static getDerivedStateFromError(e: unknown) {
    return { reason: e instanceof Error ? e.message : 'the map failed to start' }
  }
  render() {
    return this.state.reason ? <UnavailablePanel reason={this.state.reason} /> : this.props.children
  }
}

/** Map error events that mean the map cannot be used: rejected token or no network. */
export function mapFailureReason(err: { status?: number; message?: string } | undefined): string | null {
  if (!err) return null
  if (err.status === 401 || err.status === 403) return `Mapbox rejected the access token (HTTP ${err.status})`
  if (err.status === undefined && /failed to fetch|networkerror|network request failed|load failed/i.test(err.message ?? ''))
    return 'cannot reach Mapbox (no network)'
  return null
}

/**
 * Whether a map error should replace the map with the unavailable panel. Token, style and network
 * failures are fatal only before the map's first `load`; afterwards a failed tile or fetch (a blip in
 * the venue Wi-Fi, one rejected tile) is ignored so one transient error never kills the map.
 */
export function fatalMapError(
  err: { status?: number; message?: string } | undefined,
  loaded: boolean,
): string | null {
  if (loaded) return null
  return mapFailureReason(err)
}

/** The 3D twin (three.js + react-three-map) loads on first use, not with the shell. */
const TwinScene = lazy(() => import('../twin/TwinScene'))

/** Zoom thresholds: the live twin mounts at >= 12, zone labels show at >= 15 (US 34). */
export const TWIN_MIN_ZOOM = 12
export const LABELS_MIN_ZOOM = 15

export function zoomBand(zoom: number): 0 | 1 | 2 {
  return zoom >= LABELS_MIN_ZOOM ? 2 : zoom >= TWIN_MIN_ZOOM ? 1 : 0
}

/** A failing 3D scene (no WebGL2, a shader error) must never take the map down with it. */
export class TwinBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch(e: unknown) {
    console.warn('live 3D surface disabled:', e instanceof Error ? e.message : e)
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

/** Pages that show the Sentinel Network layers (node pins, coverage rings, tasking pulses). */
export const NETWORK_PAGES: ReadonlySet<string> = new Set(['network', 'twin'])

export const MISSING_TOKEN_REASON = 'no Mapbox token is configured (set BCS_MAPBOX_PUBLIC_TOKEN in .env)'

export interface MapStageProps {
  /**
   * Time Travel shows its own two maps (design §21/§26): the persistent map stays mounted (its camera,
   * tiles and 3D scene survive) but its container is `display: none`, its 3D scene renders on demand
   * only, and the shared live feed is paused.
   */
  hidden?: boolean
}

/** Keeps the stage container mounted; hides it while another page owns the screen. */
function StageFrame({ hidden, children }: { hidden: boolean; children: ReactNode }) {
  return (
    <div className="map-stage" data-testid="map-stage" data-hidden={hidden ? 'true' : 'false'} style={hidden ? { display: 'none' } : undefined}>
      {children}
    </div>
  )
}

export function MapStage({ hidden = false }: MapStageProps) {
  const config = useAppStore((s) => s.system.config)
  const site = useAppStore((s) => s.site.site)
  const page = useAppStore((s) => s.ui.page)
  const [failure, setFailure] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [band, setBand] = useState<0 | 1 | 2>(0)
  const loadedRef = useRef(false)
  const ignoredErrors = useRef(0)

  const token = config?.mapbox_token ?? ''

  useEffect(() => {
    if (!loaded) return
    const key = PAGE_PRESETS[page]
    if (key) flyToPreset(key, PAGE_FLIGHT_MS[page] ?? DEFAULT_FLIGHT_MS)
  }, [page, loaded, site])

  const onLoad = useCallback(() => {
    loadedRef.current = true
    setLoaded(true)
  }, [])

  // Re-renders only when a threshold is crossed (React bails out on an unchanged band).
  const onZoom = useCallback((e: ViewStateChangeEvent) => setBand(zoomBand(e.viewState.zoom)), [])

  useEffect(() => {
    setLiveFeedSuspended(hidden)
    // Mapbox measured a 0 x 0 container while hidden; re-measure when shown again.
    if (!hidden) stageRef.current?.resize()
  }, [hidden])
  useEffect(() => () => setLiveFeedSuspended(false), [])

  const onError = useCallback((e: { error?: { status?: number; message?: string } }) => {
    const reason = fatalMapError(e.error, loadedRef.current)
    if (reason) setFailure(reason)
    else if (loadedRef.current && mapFailureReason(e.error)) ignoredErrors.current += 1
  }, [])

  if (!config) return <StageFrame hidden={hidden}><div className="stage-loading" aria-busy="true" /></StageFrame>
  if (!token) return <StageFrame hidden={hidden}><UnavailablePanel reason={MISSING_TOKEN_REASON} /></StageFrame>
  if (failure) return <StageFrame hidden={hidden}><UnavailablePanel reason={failure} /></StageFrame>

  const globe = presetCamera('globe', null)
  return (
    <StageFrame hidden={hidden}>
    <MapBoundary>
      <Map
        ref={stageRef}
        mapboxAccessToken={token}
        mapStyle="mapbox://styles/mapbox/standard-satellite"
        projection="globe"
        initialViewState={{ longitude: globe.center[0], latitude: globe.center[1], zoom: globe.zoom, pitch: 0, bearing: 0 }}
        terrain={{ source: 'mapbox-dem', exaggeration: 1 }}
        onLoad={onLoad}
        onError={onError}
        onZoom={onZoom}
        attributionControl={false}
        style={{ position: 'absolute', inset: 0 }}
      >
        <Source id="mapbox-dem" type="raster-dem" url="mapbox://mapbox.mapbox-terrain-dem-v1" tileSize={514} maxzoom={14} />
        {site && <SiteLayers site={site} />}
        <PlannedSiteMarkers />
        {site && loaded && band >= 1 && (
          <TwinBoundary>
            <Suspense fallback={null}>
              <TwinScene
                site={site}
                showLabels={band >= 2}
                network={NETWORK_PAGES.has(page)}
                twin={page === 'twin'}
                frameloop="demand"
              />
            </Suspense>
          </TwinBoundary>
        )}
      </Map>
    </MapBoundary>
    </StageFrame>
  )
}
