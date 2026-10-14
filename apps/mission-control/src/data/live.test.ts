import { expect, test } from 'vitest'
import { applyEvent } from './live'
import { useAppStore } from './store'

const ev = (type: string, data: unknown = {}) => ({ v: 1 as const, type, id: type, at: '2026-10-08T00:00:00.000Z', data })

test('capture, metric, flag and baseline events move the captures counter; calibration its own', () => {
  const before = useAppStore.getState().rev
  for (const t of ['capture.created', 'zone.metrics', 'zone.flagged', 'baseline.updated']) applyEvent(ev(t))
  applyEvent(ev('calibration.updated'))
  applyEvent(ev('something.else'))
  const after = useAppStore.getState().rev
  expect(after.captures - before.captures).toBe(4)
  expect(after.calibration - before.calibration).toBe(1)
})
