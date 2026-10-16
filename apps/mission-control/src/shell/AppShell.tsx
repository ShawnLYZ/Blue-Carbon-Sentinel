import { lazy, Suspense, useCallback, type ComponentType } from 'react'
import { MapStage } from '../stage/MapStage'
import { StageHud } from '../stage/StageHud'
import { useCarbonRefresh } from '../data/carbon'
import { useAppStore } from '../data/store'
import { AboutCover } from './AboutCover'
import { NavRail } from './NavRail'
import { PageTransition } from './PageTransition'
import { DemoDirectorPanel } from '../director/DemoDirectorPanel'
import { CriticalToasts } from './CriticalToasts'
import { TopBar } from './TopBar'
import { useHashRoute, type PageKey } from './router'
import { useGlobalShortcuts } from './shortcuts'
import { CommandCenter } from '../pages/CommandCenter'
import { SatelliteIntel } from '../pages/SatelliteIntel'
import { SentinelNetwork } from '../pages/SentinelNetwork'
import { DigitalTwin } from '../pages/DigitalTwin'
import { TimeTravel } from '../pages/TimeTravel'
import { CarbonLedger } from '../pages/CarbonLedger'
import { System } from '../pages/System'

const MangrovePreview = lazy(() => import('../preview/MangrovePreview'))
const DigitalTwinPreview = lazy(() => import('../preview/DigitalTwinPreview'))

const PAGE_COMPONENTS: Partial<Record<PageKey, ComponentType>> = {
  command: CommandCenter,
  satellite: SatelliteIntel,
  network: SentinelNetwork,
  twin: DigitalTwin,
  'time-travel': TimeTravel,
  ledger: CarbonLedger,
  system: System,
}

export function AppShell() {
  const page = useHashRoute()
  useCarbonRefresh() // the one carbon-summary reader for the tiles and the twin columns
  const toggleDirector = useAppStore((s) => s.toggleDirector)
  const directorOpen = useAppStore((s) => s.ui.director)
  useGlobalShortcuts(useCallback(() => toggleDirector(), [toggleDirector]))
  const Page = PAGE_COMPONENTS[page]
  const preview = new URLSearchParams(location.search).has('mangrove-preview') && (page === 'satellite' || page === 'twin')

  // director-open reserves a right gutter for the Demo Director panel so page controls reflow beside it.
  return (
    <div className={directorOpen ? 'shell director-open' : 'shell'}>
      <TopBar />
      <NavRail page={page} />
      <main className="stage-area">
        {/* The map stays mounted across pages; Time Travel hides it and mounts its own paired maps (design §21). */}
        <MapStage hidden={page === 'time-travel' || preview} suspendFeed={page === 'time-travel'} renderTwin={!preview} />
        {page !== 'time-travel' && !preview && <StageHud page={page} />}
        <PageTransition pageKey={page}>
          {preview ? <Suspense fallback={<div className="stage-loading" />}>{page === 'twin' ? <DigitalTwinPreview /> : <MangrovePreview />}</Suspense> : Page && <Page />}
          {page === 'about' && <AboutCover />}
        </PageTransition>
        <DemoDirectorPanel />
      </main>
      <CriticalToasts />
    </div>
  )
}
