/** The database warning line (addendum A2). The storage budget comes from the status (`storage_budget_bytes`). */
export const DB_WARN_BYTES = 400_000_000

export type Level = 'ok' | 'warn' | 'unknown'

export function megabytes(bytes: number): string {
  const mb = bytes / 1_000_000
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`
}

/** "12 MB of 400 MB", or "unknown" when the cloud has not reported a size. Warns at or over the limit. */
export function usageLine(used: number | null | undefined, limit: number): { text: string; level: Level } {
  if (used === null || used === undefined) return { text: 'unknown', level: 'unknown' }
  return { text: `${megabytes(used)} of ${megabytes(limit)}`, level: used >= limit ? 'warn' : 'ok' }
}

export function lagText(lagS: number | null | undefined): string {
  return lagS === null || lagS === undefined ? 'not measured' : `${lagS.toFixed(1)} s`
}

export function pausedText(paused: boolean | null | undefined): string {
  if (paused === null || paused === undefined) return 'unknown'
  return paused ? 'paused (resume it in the dashboard)' : 'running'
}
