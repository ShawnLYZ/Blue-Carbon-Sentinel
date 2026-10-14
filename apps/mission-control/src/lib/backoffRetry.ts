// Bounded retry on a back-off schedule, for media that is "not ready yet" (404) on the server.

/** Futures files are retried at about 1, 2, 4, 8 and 16 s after the first load (then the events only). */
export const FUTURES_RETRY_DELAYS_MS: readonly number[] = [1000, 2000, 4000, 8000, 16000]

export interface BackoffOptions {
  delays?: readonly number[]
  /** Whether anything is still missing (checked before every attempt and after it). */
  isMissing: () => boolean
  /** One attempt; the next is scheduled when it settles and something is still missing. */
  retry: () => Promise<unknown>
}

/**
 * Starts the schedule: wait delays[0], retry if something is missing, wait delays[1], ... It stops for
 * good once nothing is missing, the delays run out, or the returned cancel function is called (which also
 * clears the pending timer). Never more than one attempt in flight.
 */
export function startBackoffRetry({ delays = FUTURES_RETRY_DELAYS_MS, isMissing, retry }: BackoffOptions): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const step = (i: number) => {
    if (stopped || i >= delays.length) return
    timer = setTimeout(async () => {
      timer = undefined
      if (stopped || !isMissing()) return
      try {
        await retry()
      } catch {
        // counted as still missing; the next step tries again
      }
      if (!stopped && isMissing()) step(i + 1)
    }, delays[i])
  }
  step(0)
  return () => {
    stopped = true
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }
}
