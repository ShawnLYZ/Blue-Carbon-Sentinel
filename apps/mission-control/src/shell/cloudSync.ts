import type { SystemStatus } from '@bcs/api-types'

type SyncState = SystemStatus['sync']['state']

/** The top bar's cloud chip text (the queue count is BufferingBadge's alone). */
export function cloudChipValue(state: SyncState | undefined): string {
  return !state ? '—' : state === 'online' ? 'Online' : state === 'buffering' ? 'Buffering' : 'Offline'
}
