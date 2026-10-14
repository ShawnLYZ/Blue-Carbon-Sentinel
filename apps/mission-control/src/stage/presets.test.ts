import { describe, expect, it } from 'vitest'
import { DEFAULT_FLIGHT_MS, PAGE_FLIGHT_MS, PAGE_PRESETS } from './presets'

describe('cinematic flight durations (design §26: 1.5-3 s)', () => {
  it('every page with a preset has a duration in range', () => {
    for (const page of Object.keys(PAGE_PRESETS)) {
      const ms = PAGE_FLIGHT_MS[page] ?? DEFAULT_FLIGHT_MS
      expect(ms, page).toBeGreaterThanOrEqual(1500)
      expect(ms, page).toBeLessThanOrEqual(3000)
    }
  })
  it('every listed duration and the default are in range', () => {
    for (const ms of [...Object.values(PAGE_FLIGHT_MS), DEFAULT_FLIGHT_MS]) {
      expect(ms).toBeGreaterThanOrEqual(1500)
      expect(ms).toBeLessThanOrEqual(3000)
    }
  })
})
