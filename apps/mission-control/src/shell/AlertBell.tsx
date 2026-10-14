import { useState } from 'react'
import { formatMYT } from '@bcs/ui'
import { openAlerts } from '../data/alerts'
import { useAppStore } from '../data/store'

/** The top-bar bell: the number of unacknowledged alerts and a compact list of the newest. */
export function AlertBell() {
  const items = useAppStore((s) => s.alerts.items)
  const [open, setOpen] = useState(false)
  const unacked = openAlerts(items)
  const worst = unacked.some((a) => a.severity === 'critical') ? 'critical' : unacked.some((a) => a.severity === 'warning') ? 'warning' : 'info'
  return (
    <div className="bell">
      <button type="button" className="bell__btn" aria-label={`Alerts (${unacked.length} open)`} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7zM10 20a2 2 0 0 0 4 0" />
        </svg>
        <span data-testid="alert-bell-count" className={`bell__count bell__count--${unacked.length === 0 ? 'zero' : worst}`}>
          {unacked.length}
        </span>
      </button>
      {open && (
        <div className="bell__menu bcs-panel" role="menu">
          {unacked.length === 0 && <p className="bell__empty">No open alerts</p>}
          {unacked.slice(0, 6).map((a) => (
            <div key={a.id} className={`bell__item bell__item--${a.severity}`} role="menuitem">
              <strong>
                {a.type.replaceAll('_', ' ')}
                {a.occurrences > 1 && <span className="bcs-mono"> ×{a.occurrences}</span>}
              </strong>
              <span>{a.message}</span>
              <span className="bcs-mono">{formatMYT(a.last_seen_at)}</span>
            </div>
          ))}
          {unacked.length > 6 && <a className="bell__more" href="#/command" onClick={() => setOpen(false)}>All {unacked.length} open alerts</a>}
        </div>
      )}
    </div>
  )
}
