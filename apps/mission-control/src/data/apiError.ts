/** An openapi-fetch `error` value (the Ground Station's ErrorEnvelope), read for the operator. */
export function apiErrorText(error: unknown, fallback = 'The Ground Station did not accept the request.'): string {
  if (error && typeof error === 'object') {
    const e = error as { error?: { message?: unknown }; message?: unknown; detail?: unknown }
    if (typeof e.error?.message === 'string') return e.error.message
    if (typeof e.message === 'string') return e.message
    if (typeof e.detail === 'string') return e.detail
  }
  return fallback
}

/** The ErrorEnvelope code (`camera_offline`, `non_convex`, ...), if any. */
export function apiErrorCode(error: unknown): string | null {
  if (error && typeof error === 'object') {
    const code = (error as { error?: { code?: unknown } }).error?.code
    if (typeof code === 'string') return code
  }
  return null
}

/** Message for a rejected fetch (network failure). */
export function networkErrorText(e: unknown): string {
  return e instanceof Error ? `Network error: ${e.message}` : 'Network error'
}
