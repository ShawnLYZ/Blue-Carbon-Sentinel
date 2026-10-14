import { useState } from 'react'
import type { Alert } from '@bcs/api-types'
import { Button, Panel, formatMYT } from '@bcs/ui'
import { acknowledgeAlert } from '../../data/alerts'
import { useAppStore } from '../../data/store'

const ICON: Record<Alert['severity'], string> = { critical: '⛔', warning: '⚠', info: 'ℹ' }

/** Open alerts first (newest activity first), then acknowledged ones. */
export function sortFeed(items: Alert[]): Alert[] {
  return [...items].sort((a, b) => {
    const ao = a.acknowledged_at ? 1 : 0
    const bo = b.acknowledged_at ? 1 : 0
    return ao - bo || b.last_seen_at.localeCompare(a.last_seen_at)
  })
}

export function AlertFeed() {
  const items = useAppStore((s) => s.alerts.items)
  const [busy, setBusy] = useState<string | null>(null)
  const feed = sortFeed(items).slice(0, 30)
  const ack = (id: string) => {
    setBusy(id)
    acknowledgeAlert(id)
      .catch(() => undefined)
      .finally(() => setBusy(null))
  }
  return (
    <Panel title="Alerts">
      {feed.length === 0 ? (
        <p className="hint">No alerts. Everything is quiet.</p>
      ) : (
        <ul className="alert-feed" data-testid="alert-feed">
          {feed.map((a) => (
            <li key={a.id} className={`alert-feed__item alert-feed__item--${a.severity}`} data-acked={a.acknowledged_at ? 'true' : 'false'}>
              <span className="alert-feed__icon" role="img" aria-label={a.severity}>
                {ICON[a.severity]}
              </span>
              <div className="alert-feed__body">
                <span>{a.message}</span>
                <span className="alert-feed__meta bcs-mono">
                  {formatMYT(a.last_seen_at)}
                  {a.occurrences > 1 && <strong> ×{a.occurrences}</strong>}
                </span>
              </div>
              {a.acknowledged_at ? (
                <span className="alert-feed__done">Done</span>
              ) : (
                <Button onClick={() => ack(a.id)} disabled={busy === a.id}>
                  Acknowledge
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
