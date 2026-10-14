// The digital twin's 3D scene inside the Mapbox map: a react-three-map Canvas anchored at the site's
// NW corner (F4) holding the live reality surface. Later milestones mount their children inside it.
//
// Repaints: react-three-map's frameloop "always" calls map.triggerRepaint() after every render, which
// makes Mapbox repaint at the display refresh rate forever. "demand" is used instead: the map repaints
// once per arriving live frame (RealitySurface invalidates), when the exaggeration or terrain base
// changes, whenever a map layer changes (pins, rings) and while a tasking pulse runs (TaskingPulses
// invalidates at a capped rate only while a task is open), and whenever Mapbox itself repaints for
// camera motion. When the tab is hidden the live feed pauses and Mapbox stops rendering.
import { useEffect, useMemo, type ReactNode } from 'react'
import { useThree } from '@react-three/fiber'
import { Canvas, useMap } from 'react-three-map'
import type { Site } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { RealitySurface } from './RealitySurface'
import { ZoneLabels } from './ZoneLabels'
import { NetworkLayers } from './NetworkLayers'
import { TwinLayers } from './TwinLayers'
import { createSurfaceState, type SurfaceState } from './surfaceMaterial'
import { SurfaceStateContext } from './surfaceContext'
import { siteBounds, terrainBaseMetres } from './terrainBase'

export interface TwinSceneProps {
  site: Site
  /** Zone labels are shown at zoom >= 15 (the stage decides). */
  showLabels?: boolean
  /** Sentinel Network layers: node pins, coverage rings and tasking pulses. */
  network?: boolean
  /** Digital Twin layers (overlays, risk, trees, alerts, zone hits; the network layers behind switches). */
  twin?: boolean
  /**
   * R3F frame loop, "demand" (see above). MapStage passes it explicitly: the hidden stage (Time Travel)
   * must never render on its own.
   */
  frameloop?: 'demand' | 'always'
  children?: ReactNode
}

/** Keeps the shared surface state in step with the store and the terrain; outside React state. */
function TwinSync({ site, state }: { site: Site; state: SurfaceState }) {
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
    // Terrain tiles load after the scene mounts: recompute when the map settles, not per frame.
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

  useEffect(() => invalidate(), [invalidate])
  return null
}

export function TwinScene({
  site,
  showLabels = false,
  network = false,
  twin = false,
  frameloop = 'demand',
  children,
}: TwinSceneProps) {
  const state = useMemo(createSurfaceState, [])
  return (
    <Canvas id="bcs-twin" latitude={site.anchor_nw.lat} longitude={site.anchor_nw.lng} frameloop={frameloop}>
      <TwinSync site={site} state={state} />
      <RealitySurface state={state} />
      {showLabels && <ZoneLabels zones={site.zones} state={state} />}
      <SurfaceStateContext.Provider value={state}>
        {twin ? <TwinLayers site={site} /> : network && <NetworkLayers />}
        {children}
      </SurfaceStateContext.Provider>
    </Canvas>
  )
}

export default TwinScene
