import { Panel } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { DB_WARN_BYTES, lagText, pausedText, usageLine } from './cloudView'

/** Read-only cloud sync and usage (addendum A2): lag, queue, database and storage against their limits. */
export function CloudSection() {
  const status = useAppStore((s) => s.system.status)
  if (!status) {
    return (
      <Panel title="Cloud">
        <p className="page__blurb">Loading the cloud status…</p>
      </Panel>
    )
  }
  const { sync, cloud } = status
  const db = usageLine(cloud.db_bytes, DB_WARN_BYTES)
  const storage = usageLine(cloud.storage_bytes, cloud.storage_budget_bytes)
  return (
    <Panel title="Cloud">
      <dl className="kv-list" data-testid="cloud-section">
        <dt>Sync</dt>
        <dd data-testid="cloud-state">{sync.state}</dd>
        <dt>Sync lag</dt>
        <dd className="bcs-mono" data-testid="cloud-lag">
          {lagText(sync.lag_s)}
        </dd>
        <dt>Queue</dt>
        <dd className="bcs-mono" data-testid="cloud-queue">
          {sync.queue} rows · {sync.media_queue} media
        </dd>
        <dt>Database (warns at 400 MB)</dt>
        <dd className="bcs-mono" data-testid="cloud-db" data-level={db.level}>
          {db.text}
          {db.level === 'warn' ? ' · over the warning' : ''}
        </dd>
        <dt>Storage (800 MB budget)</dt>
        <dd className="bcs-mono" data-testid="cloud-storage" data-level={storage.level}>
          {storage.text}
          {storage.level === 'warn' ? ' · over the budget' : ''}
        </dd>
        <dt>Project</dt>
        <dd data-testid="cloud-paused">{pausedText(cloud.paused)}</dd>
      </dl>
      <p className="hint">
        <a href={cloud.dashboard_url} target="_blank" rel="noreferrer" data-testid="cloud-dashboard">
          Open the Supabase dashboard
        </a>
      </p>
    </Panel>
  )
}
