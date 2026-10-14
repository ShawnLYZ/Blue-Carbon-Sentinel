import { useEffect, useState } from 'react'
import { Panel } from '@bcs/ui'
import { liveStats, type LiveStats } from '../../twin/liveStats'

const REFRESH_MS = 500
const STALE_MS = 3000

function ms(v: number): string {
  return `${Math.round(v)} ms`
}

/** Read-only frame-to-screen readout of the live surface (targets: >= 5 fps, <= 500 ms). */
export function LiveStatsSection() {
  const [stats, setStats] = useState<LiveStats | null>(() => liveStats())
  useEffect(() => {
    const id = setInterval(() => setStats(liveStats()), REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  return (
    <Panel title="Live surface">
      {stats ? (
        <dl className="kv-list" data-testid="live-stats">
          <dt>Surface rate</dt>
          <dd className="bcs-mono" data-testid="live-stats-fps">
            {stats.fps.toFixed(1)} fps
          </dd>
          <dt>Server latency</dt>
          <dd className="bcs-mono" data-testid="live-stats-server">
            {ms(stats.serverLatencyMs)}
          </dd>
          <dt>Browser receive → upload</dt>
          <dd className="bcs-mono" data-testid="live-stats-client">
            {ms(stats.receiveToUploadMs)}
          </dd>
          <dt>Frame to screen</dt>
          <dd className="bcs-mono" data-testid="live-stats-total">
            {ms(stats.frameToScreenMs)}
          </dd>
          <dt>Newest frame</dt>
          <dd className="bcs-mono">{stats.ageMs > STALE_MS ? `${(stats.ageMs / 1000).toFixed(0)} s ago (not updating)` : 'current'}</dd>
        </dl>
      ) : (
        <p className="page__blurb" data-testid="live-stats-empty">
          No live frame has reached the map yet.
        </p>
      )}
      <p className="hint">
        Frame to screen = server latency (camera frame to processed) + browser time from receiving the frame to
        uploading it for the next map render. Targets: at least 5 fps, at most 500 ms.
      </p>
    </Panel>
  )
}
