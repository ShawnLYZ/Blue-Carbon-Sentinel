// Command Center (design §26): the KPI tiles over the live map, and the alert feed.
import { useEffect } from 'react'
import { refreshAlerts } from '../../data/alerts'
import { refreshZoneSummaries } from '../../data/live'
import { useSettledRev } from '../../data/hooks'
import { AlertFeed } from './AlertFeed'
import { KpiTiles } from './KpiTiles'
import { PlannedSites } from './PlannedSites'

const ALERT_REFRESH_MS = 10_000

export function CommandCenter() {
  const rev = useSettledRev('captures')
  useEffect(() => {
    refreshZoneSummaries().catch(() => undefined)
  }, [rev])
  // Repeats of an open alert only bump its occurrence count (no event), so the feed re-reads it now and then.
  useEffect(() => {
    const read = () => refreshAlerts().catch(() => undefined)
    read()
    const t = setInterval(read, ALERT_REFRESH_MS)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="page page--side">
      <h1 className="page__title">Command Center</h1>
      <div className="cc">
        <KpiTiles />
        <PlannedSites />
        <AlertFeed />
      </div>
    </div>
  )
}
