import { useEffect, useRef, useState } from 'react'
import type { Alert } from '@bcs/api-types'
import { useAppStore } from '../data/store'

export const TOAST_MS = 8000

/**
 * Critical alerts toast on any page (design §25): one toast per new alert ID, never repeated. The server
 * folds repeats into `occurrences` (no new alert.created), and an ID once seen is never toasted again.
 * Alerts present in the first snapshot are not toasted.
 */
export function CriticalToasts() {
  const items = useAppStore((s) => s.alerts.items)
  const loaded = useAppStore((s) => s.alerts.loaded)
  const seen = useRef<Set<string> | null>(null)
  const [toasts, setToasts] = useState<Alert[]>([])
  // Every alert ID that was ever toasted this session (dismissed or not): lets tests assert one toast per ID.
  const [shown, setShown] = useState<string[]>([])

  useEffect(() => {
    if (!loaded) return
    if (seen.current === null) {
      seen.current = new Set(items.map((a) => a.id))
      return
    }
    const known = seen.current
    const fresh = items.filter((a) => a.severity === 'critical' && !a.acknowledged_at && !known.has(a.id))
    for (const a of items) known.add(a.id)
    if (fresh.length === 0) return
    setToasts((t) => [...fresh, ...t].slice(0, 4))
    setShown((ids) => [...ids, ...fresh.map((a) => a.id)])
    for (const a of fresh) setTimeout(() => setToasts((t) => t.filter((x) => x.id !== a.id)), TOAST_MS)
  }, [items, loaded])

  return (
    <div className="toasts" role="region" aria-label="Alerts" data-testid="toast-log" data-shown={shown.join(',')}>
      {toasts.map((a) => (
        <div key={a.id} className="toast" role="alert" data-testid="toast" data-alert-id={a.id}>
          <strong>{a.type.replaceAll('_', ' ')}</strong>
          <span>{a.message}</span>
        </div>
      ))}
    </div>
  )
}
