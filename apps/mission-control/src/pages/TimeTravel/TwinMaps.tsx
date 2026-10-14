// Time Travel's two linked maps (design §21): "Without restoration" | "With restoration", each with its
// scenario's 3D twin (FutureMap, loaded on demand with three.js). The cameras are synchronised and one
// year slider drives both. The headers, the "AI-illustrated" badge and the "Map unavailable" panels live
// here, outside the map chunk, so they show even when Mapbox or WebGL cannot start.
import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import type { MapRef } from 'react-map-gl/mapbox'
import type { Forecast, Site, TreePoint } from '@bcs/api-types'
import type { FrameSources, Scenario } from '../../lib/interp'
import { syncCameras } from '../../lib/cameraSync'
import { MISSING_TOKEN_REASON, UnavailablePanel } from '../../stage/MapStage'
import type { Planting } from '../../twin/FutureTrees'
import type { PreloadState } from './futuresMedia'

const FutureMap = lazy(() => import('./FutureMap'))

export const SCENARIO_TITLES: Record<Scenario, string> = {
  without: 'Without restoration',
  with: 'With restoration',
}

export interface TwinMapsProps {
  site: Site | null
  token: string | null
  forecast: Forecast | null
  preload: PreloadState
  frames: Record<Scenario, FrameSources>
  year: number
  trees: TreePoint[]
  plantings: Planting[]
  selectedZone: string | null
  onSelectZone: (zoneId: string) => void
}

export function TwinMaps(props: TwinMapsProps) {
  const { site, token, frames } = props
  const [maps, setMaps] = useState<Record<Scenario, MapRef | null>>({ without: null, with: null })
  const onMap = useCallback((sc: Scenario, m: MapRef | null) => setMaps((cur) => (cur[sc] === m ? cur : { ...cur, [sc]: m })), [])

  useEffect(() => {
    if (!maps.without || !maps.with) return
    // Start aligned on the "with" map, then mirror every move.
    const w = maps.with
    const c = w.getCenter()
    maps.without.jumpTo({ center: [c.lng, c.lat], zoom: w.getZoom(), bearing: w.getBearing(), pitch: w.getPitch() })
    return syncCameras(maps.without, maps.with)
  }, [maps])

  return (
    <>
      {(['without', 'with'] as const).map((sc) => (
        <section key={sc} className={`tt-map tt-map--${sc}`} aria-label={SCENARIO_TITLES[sc]}>
          <header className="tt-map__header">
            <h2 className="tt-map__title">{SCENARIO_TITLES[sc]}</h2>
            {frames[sc].illustrated && (
              <span className="tt-badge" data-testid={`ai-badge-${sc}`} title="This year's texture blends an AI image illustration; numbers come from the forecast.">
                AI-illustrated
              </span>
            )}
          </header>
          <div className="tt-map__canvas">
            {!site || token === null ? (
              <div className="stage-loading" aria-busy="true" />
            ) : !token ? (
              <UnavailablePanel reason={MISSING_TOKEN_REASON} />
            ) : (
              <Suspense fallback={<div className="stage-loading" aria-busy="true" />}>
                <FutureMap {...props} site={site} token={token} scenario={sc} frame={frames[sc]} onMap={onMap} />
              </Suspense>
            )}
          </div>
        </section>
      ))}
    </>
  )
}
