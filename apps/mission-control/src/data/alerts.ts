import type { Alert } from '@bcs/api-types'
import { api } from './client'
import { useAppStore } from './store'

/** Open alerts, newest activity first. */
export function openAlerts(items: Alert[]): Alert[] {
  return items.filter((a) => !a.acknowledged_at).sort((a, b) => b.last_seen_at.localeCompare(a.last_seen_at))
}

/** POST /alerts/{id}/ack; the store follows at once (the alert.acknowledged event then repeats it harmlessly). */
export async function acknowledgeAlert(id: string): Promise<void> {
  const r = await api.POST('/api/v1/alerts/{alert_id}/ack', { params: { path: { alert_id: id } } })
  if (r.data?.acknowledged_at) useAppStore.getState().acknowledgeAlert(id, r.data.acknowledged_at)
}

/**
 * Re-reads the alert list. The server folds a duplicate into `occurrences` without an event (addendum J2
 * has only alert.created and alert.acknowledged), so counts and last-seen times are refreshed over HTTP.
 */
export async function refreshAlerts(): Promise<void> {
  const r = await api.GET('/api/v1/alerts')
  if (r.data) useAppStore.getState().setAlerts(r.data)
}
