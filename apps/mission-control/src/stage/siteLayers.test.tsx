import { expect, test, vi } from 'vitest'

vi.mock('react-map-gl/mapbox', () => ({ Layer: () => null, Source: () => null, useMap: () => ({ current: null }) }))
const { PULSE_INTERVAL_MS, pulseOpacity, shouldPulse } = await import('./siteLayers')

test('the boundary pulse is throttled to at most 10 Hz', () => {
  expect(1000 / PULSE_INTERVAL_MS).toBeLessThanOrEqual(10)
})

test('the pulse pauses while hidden or zoomed out to the globe', () => {
  expect(shouldPulse(16, false)).toBe(true)
  expect(shouldPulse(16, true)).toBe(false)
  expect(shouldPulse(4.2, false)).toBe(false)
})

test('pulse opacity stays between 0.5 and 1', () => {
  for (let t = 0; t < 2000; t += 100) {
    expect(pulseOpacity(t)).toBeGreaterThanOrEqual(0.5)
    expect(pulseOpacity(t)).toBeLessThanOrEqual(1)
  }
})
