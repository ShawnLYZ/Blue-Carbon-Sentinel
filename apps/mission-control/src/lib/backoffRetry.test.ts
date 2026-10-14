import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { FUTURES_RETRY_DELAYS_MS, startBackoffRetry } from './backoffRetry'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

test('missing files are retried at 1, 2, 4, 8 and 16 s, then never again', async () => {
  const at: number[] = []
  const t0 = Date.now()
  startBackoffRetry({ isMissing: () => true, retry: async () => void at.push(Date.now() - t0) })
  await vi.advanceTimersByTimeAsync(60_000)
  expect(FUTURES_RETRY_DELAYS_MS).toEqual([1000, 2000, 4000, 8000, 16000])
  expect(at).toEqual([1000, 3000, 7000, 15000, 31000])
  expect(vi.getTimerCount()).toBe(0)
})

test('no retry once nothing is missing, and the schedule stops when a retry completes the set', async () => {
  let missing = 3
  const retry = vi.fn(async () => {
    missing -= 2
  })
  startBackoffRetry({ isMissing: () => missing > 0, retry })
  await vi.advanceTimersByTimeAsync(1000)
  expect(retry).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(2000)
  expect(retry).toHaveBeenCalledTimes(2) // missing went 3 -> 1 -> -1
  await vi.advanceTimersByTimeAsync(60_000)
  expect(retry).toHaveBeenCalledTimes(2)
  expect(vi.getTimerCount()).toBe(0)

  const never = vi.fn(async () => undefined)
  startBackoffRetry({ isMissing: () => false, retry: never })
  await vi.advanceTimersByTimeAsync(60_000)
  expect(never).not.toHaveBeenCalled()
})

test('cancel (forecast change or unmount) clears the pending timer', async () => {
  const retry = vi.fn(async () => undefined)
  const cancel = startBackoffRetry({ isMissing: () => true, retry })
  await vi.advanceTimersByTimeAsync(1000)
  expect(retry).toHaveBeenCalledTimes(1)
  expect(vi.getTimerCount()).toBe(1)
  cancel()
  expect(vi.getTimerCount()).toBe(0)
  await vi.advanceTimersByTimeAsync(60_000)
  expect(retry).toHaveBeenCalledTimes(1)
})

test('cancel during an attempt schedules nothing more; a failed attempt counts as still missing', async () => {
  let cancel = () => {}
  const retry = vi.fn(async () => {
    cancel()
  })
  cancel = startBackoffRetry({ isMissing: () => true, retry })
  await vi.advanceTimersByTimeAsync(60_000)
  expect(retry).toHaveBeenCalledTimes(1)

  const failing = vi.fn(async () => {
    throw new Error('network')
  })
  startBackoffRetry({ isMissing: () => true, retry: failing, delays: [10, 20] })
  await vi.advanceTimersByTimeAsync(1000)
  expect(failing).toHaveBeenCalledTimes(2)
})
