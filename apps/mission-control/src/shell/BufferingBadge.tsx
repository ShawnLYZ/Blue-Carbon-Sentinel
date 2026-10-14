import { useAppStore } from '../data/store'

/** The single place that gives the queue count of an outage: shown only in the offline state (three consecutive
 *  failed sync passes, addendum H6), not for ordinary unsent work while the cloud is reachable. */
export function BufferingBadge() {
  const sync = useAppStore((s) => s.system.status?.sync)
  if (!sync || sync.state !== 'offline') return null
  return (
    <span className="topbar__buffering" data-testid="buffering-badge" role="status" style={{ color: 'var(--risk-medium)', fontWeight: 600 }}>
      Buffering offline ({sync.queue} queued)
    </span>
  )
}
