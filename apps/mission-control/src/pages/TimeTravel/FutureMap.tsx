// One of Time Travel's two dedicated Mapbox maps (design §21) with that scenario's 3D twin: the future
// surface, the procedural trees and, on the "with restoration" map, the zone hit targets that open the
// zone plan panel. Loaded on demand with three.js (its own chunk), like the Digital Twin's scene.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Map, Source, type MapRef } from 'react-map-gl/mapbox'
import 'mapbox-gl/dist/mapbox-gl.css'
import { useThree } from '@react-three/fiber'
import { Canvas, useMap } from 'react-three-map'
import type { Forecast, Site, TreePoint } from '@bcs/api-types'
import { useAppStore } from '../../data/store'
import type { FrameSources, Scenario } from '../../lib/interp'
import { MapBoundary, TwinBoundary, UnavailablePanel, fatalMapError } from '../../stage/MapStage'
import { presetCamera } from '../../stage/presets'
import { FutureSurface } from '../../twin/FutureSurface'
import { FutureTrees, type Planting } from '../../twin/FutureTrees'
import { ZoneHits } from '../../twin/ZoneHits'
import { SurfaceStateContext } from '../../twin/surfaceContext'
import { createSurfaceState, type SurfaceState } from '../../twin/surfaceMaterial'
import { siteBounds, terrainBaseMetres } from '../../twin/terrainBase'
import type { PreloadState } from './futuresMedia'

export interface FutureMapProps {
  scenario: Scenario
  site: Site
  token: string
  forecast: Forecast | null
  preload: PreloadState
  frame: FrameSources
  year: number
  trees: TreePoint[]
  plantings: Planting[]
  selectedZone: string | null
  onSelectZone: (zoneId: string) => void
  /** The map once loaded (null when it goes away), for the camera sync. */
  onMap: (scenario: Scenario, map: MapRef | null) => void
}

/** Keeps the surface on top of the terrain and follows the shared vertical exaggeration. */
function SceneSync({ site, state }: { site: Site; state: SurfaceState }) {
  const map = useMap()
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => {
    const apply = (v: number) => {
      if (state.exaggeration === v) return
      state.exaggeration = v
      invalidate()
    }
    apply(useAppStore.getState().twin.exaggeration)
    return useAppStore.subscribe((s) => apply(s.twin.exaggeration))
  }, [state, invalidate])
  useEffect(() => {
    if (!map) return
    const bounds = siteBounds(site)
    const update = () => {
      const base = terrainBaseMetres(map, bounds)
      if (Math.abs(base - state.base) < 0.01) return
      state.base = base
      invalidate()
    }
    update()
    map.on('idle', update)
    return () => {
      map.off('idle', update)
    }
  }, [map, site, state, invalidate])
  return null
}

function FutureScene(props: FutureMapProps & { forecast: Forecast }) {
  const { scenario, site, forecast, preload, frame, year, trees, plantings, selectedZone, onSelectZone } = props
  const state = useMemo(createSurfaceState, [])
  return (
    <>
      <SceneSync site={site} state={state} />
      <FutureSurface state={state} media={preload.media} version={preload.version} scenario={scenario} frame={frame} />
      <FutureTrees
        state={state}
        trees={trees}
        forecast={forecast}
        scenario={scenario}
        year={year}
        plantings={scenario === 'with' ? plantings : []}
        classes={preload.media?.classes ?? null}
        heightsRev={preload.version}
      />
      {scenario === 'with' && (
        <SurfaceStateContext.Provider value={state}>
          <ZoneHits zones={site.zones} selected={selectedZone} onSelect={onSelectZone} namePrefix="zone-hit-with-" />
        </SurfaceStateContext.Provider>
      )}
    </>
  )
}

export default function FutureMap(props: FutureMapProps) {
  const { scenario, site, token, forecast, onMap } = props
  const ref = useRef<MapRef>(null)
  const loadedRef = useRef(false)
  const [loaded, setLoaded] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const cam = presetCamera('site-orbit', [site.centre.lng, site.centre.lat])

  const onLoad = useCallback(() => {
    loadedRef.current = true
    setLoaded(true)
    onMap(scenario, ref.current)
  }, [onMap, scenario])
  useEffect(() => () => onMap(scenario, null), [onMap, scenario])
  const onError = useCallback((e: { error?: { status?: number; message?: string } }) => {
    const reason = fatalMapError(e.error, loadedRef.current)
    if (reason) setFailure(reason)
  }, [])

  if (failure) return <UnavailablePanel reason={failure} />
  return (
    <MapBoundary>
      <Map
        ref={ref}
        mapboxAccessToken={token}
        mapStyle="mapbox://styles/mapbox/standard-satellite"
        initialViewState={{ longitude: cam.center[0], latitude: cam.center[1], zoom: cam.zoom, pitch: cam.pitch, bearing: cam.bearing }}
        terrain={{ source: 'mapbox-dem', exaggeration: 1 }}
        onLoad={onLoad}
        onError={onError}
        attributionControl={false}
        style={{ position: 'absolute', inset: 0 }}
      >
        <Source id="mapbox-dem" type="raster-dem" url="mapbox://mapbox.mapbox-terrain-dem-v1" tileSize={514} maxzoom={14} />
        {loaded && forecast && (
          <TwinBoundary>
            <Canvas id={`bcs-future-${scenario}`} latitude={site.anchor_nw.lat} longitude={site.anchor_nw.lng} frameloop="demand">
              <FutureScene {...props} forecast={forecast} />
            </Canvas>
          </TwinBoundary>
        )}
      </Map>
    </MapBoundary>
  )
}
