// Time Travel & Restoration (design §21, §26): two linked futures 2026 -> 2035 ("without" | "with"
// restoration) from the latest real capture, one year slider, the numbers and uncertainty bands under each
// map, and the restoration plan editor. While this page is shown the persistent map is hidden and paused
// (AppShell / MapStage). Everything the slider needs is preloaded once per forecast, so scrubbing makes no
// request (Review Focus 5); the page never waits on image illustrations (Review Focus 1).
import { useEffect, useMemo, useState } from 'react'
import type { Forecast, PlanItem, PlanVersion } from '@bcs/api-types'
import { api } from '../../data/client'
import { useAppStore } from '../../data/store'
import { FIRST_YEAR, frameSources, type FrameSources, type Scenario } from '../../lib/interp'
import type { Planting } from '../../twin/FutureTrees'
import { BandsChart } from './BandsChart'
import { useFuturesMedia } from './futuresMedia'
import { PlanEditor } from './PlanEditor'
import { ScenarioNumbers } from './ScenarioNumbers'
import { TwinMaps } from './TwinMaps'
import { useTimeTravel } from './useTimeTravel'
import { YearSlider } from './YearSlider'
import { DENSITY_PER_HA, ZonePlanPanel, isPlanting } from './ZonePlanPanel'

/** The plan items the shown forecast was run with (its plan version), for the saplings on the "with" map. */
function useForecastPlanItems(forecast: Forecast | null, plan: PlanVersion | null): PlanItem[] {
  const [fetched, setFetched] = useState<{ key: string; items: PlanItem[] } | null>(null)
  const planId = forecast?.plan_id ?? null
  const version = forecast?.plan_version ?? null
  const key = planId && version ? `${planId}:${version}` : null
  const local = plan && key === `${plan.plan_id}:${plan.version}` ? plan.items : null
  useEffect(() => {
    if (!key || local || fetched?.key === key) return
    let live = true
    api
      .GET('/api/v1/plans/{plan_id}', { params: { path: { plan_id: planId! }, query: { version: version! } } })
      .then((r) => {
        if (live && r.data) setFetched({ key, items: r.data.items })
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [key, local, fetched, planId, version])
  if (!key) return []
  return local ?? (fetched?.key === key ? fetched.items : [])
}

export function TimeTravel() {
  const tt = useTimeTravel()
  const site = useAppStore((s) => s.site.site)
  const config = useAppStore((s) => s.system.config)
  const treePoints = useAppStore((s) => s.trees.points)
  const metrics = useAppStore((s) => s.zones.metrics)
  const [year, setYear] = useState(FIRST_YEAR)
  // "Open in Time Travel" on the Digital Twin's zone card arrives with that zone selected.
  const [selectedZone, setSelectedZone] = useState<string | null>(() => useAppStore.getState().ui.selectedZoneId)

  const preload = useFuturesMedia(tt.forecast, tt.illustrations, tt.illustrationRev)
  const { media, version } = preload

  // Ready illustrations whose image has loaded (the badge needs the image actually shown).
  const readyKey = tt.illustrations
    .filter((i) => i.status === 'ready' && media?.illustrations.has(`${i.scenario}:${i.year}`))
    .map((i) => `${i.scenario}:${i.year}`)
    .sort()
    .join(',')
  const ready = useMemo(() => new Set(readyKey ? readyKey.split(',') : []), [readyKey])
  const frames = useMemo<Record<Scenario, FrameSources>>(
    () => ({ without: frameSources(year, 'without', ready), with: frameSources(year, 'with', ready) }),
    [year, ready],
  )

  const planItems = useForecastPlanItems(tt.forecast, tt.plan)
  const plantings = useMemo<Planting[]>(() => {
    const zones = site?.zones ?? []
    const out: Planting[] = []
    for (const it of planItems) {
      const z = zones.find((x) => x.id === it.zone_id)
      if (!z) continue
      const saplings = it.interventions
        .filter((iv) => isPlanting(iv.kind))
        .reduce((n, iv) => n + (iv.sapling_count ?? Math.round((iv.planted_area_ha ?? 0) * DENSITY_PER_HA)), 0)
      if (saplings > 0) out.push({ zoneId: z.id, col: z.col, row: z.row, saplings })
    }
    return out
  }, [planItems, site])

  // Tree points of the base capture (the latest located points; none before any were located).
  const trees = useMemo(() => treePoints?.points ?? [], [treePoints])

  return (
    <div className="tt-page">
      <div className="tt-bar">
        <h1 className="page__title">Time Travel &amp; Restoration</h1>
        <YearSlider year={year} onChange={setYear} />
      </div>
      {!tt.forecastLoading && !tt.forecast && (
        <p className="tt-banner" role="note">
          No forecast yet. Run a forecast to see both futures from the latest evidence-grade capture.
        </p>
      )}
      {tt.runError && (
        <p className="tt-banner tt-banner--error" role="alert">
          {tt.runError}
        </p>
      )}
      <div className="tt-body">
        <div className="tt-grid">
          <TwinMaps
            site={site}
            token={config ? config.mapbox_token ?? '' : null}
            forecast={tt.forecast}
            preload={preload}
            frames={frames}
            year={year}
            trees={trees}
            plantings={plantings}
            selectedZone={selectedZone}
            onSelectZone={setSelectedZone}
          />
          {(['without', 'with'] as const).map((sc) => (
            <div key={sc} className={`tt-stats tt-stats--${sc}`}>
              <ScenarioNumbers forecast={tt.forecast} scenario={sc} year={year} />
              <BandsChart forecast={tt.forecast} scenario={sc} year={year} />
            </div>
          ))}
        </div>
        <aside className="tt-side">
          <PlanEditor tt={tt} zones={site?.zones ?? []} selectedZone={selectedZone} onSelectZone={setSelectedZone} />
          {selectedZone && (
            <ZonePlanPanel
              key={selectedZone}
              zoneId={selectedZone}
              plan={tt.plan}
              note={tt.zoneNotes[selectedZone]}
              busy={tt.planBusy}
              mudPct={metrics[selectedZone]?.mud_pct}
              onChange={(ivs) => void tt.setZoneInterventions(selectedZone, ivs)}
              onClose={() => setSelectedZone(null)}
            />
          )}
        </aside>
      </div>
      <span
        data-testid="futures-preload"
        data-settled={preload.settled ? 'true' : 'false'}
        data-missing={preload.missing}
        data-version={version}
        hidden
      />
    </div>
  )
}
