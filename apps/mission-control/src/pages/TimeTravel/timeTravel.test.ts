import { describe, expect, test } from 'vitest'
import type { PlanItem, YearPoint } from '@bcs/api-types'
import { forecastGuidance, withZoneInterventions } from './useTimeTravel'
import { defaultSaplings } from './ZonePlanPanel'
import { formatYear } from './YearSlider'
import { canopyLoss, saplingGrowth, saplingSpots, treeDecline } from '../../twin/FutureTrees'

const band = (v: number) => ({ low: v, central: v, high: v })
function yp(year: number, canopy: number, extra: Record<string, unknown> = {}): YearPoint {
  return {
    year,
    canopy: band(canopy),
    health: band(1),
    land: band(1),
    risk_class: 'low',
    stock_tco2e: band(0),
    seq_tco2e: band(0),
    additional_tco2e: band(0),
    ...extra,
  } as YearPoint
}

describe('forecast 409 guidance (Review Focus 3)', () => {
  test('no evidence-grade capture: take a capture first', () => {
    expect(forecastGuidance('The forecast needs an evidence-grade capture; take one first.')).toMatch(/^Take a capture first/)
  })
  test('no baseline: set a baseline first', () => {
    expect(forecastGuidance('The forecast needs a baseline; set one first.')).toMatch(/^Set a baseline first/)
  })
  test('anything else is shown as is', () => {
    expect(forecastGuidance('boom')).toBe('boom')
  })
})

describe('withZoneInterventions', () => {
  const item: PlanItem = {
    zone_id: 'KSL-B3',
    interventions: [{ kind: 'silt_fence' }],
    priority: 2,
    rationale: 'AI',
    expected_uplift: { canopy_pp_2035: 1, tco2e_2035: 2 },
  }
  test('replaces the zone, keeping its rationale', () => {
    const out = withZoneInterventions([item], 'KSL-B3', [{ kind: 'plant_avicennia', sapling_count: 440 }])
    expect(out).toHaveLength(1)
    expect(out[0]!.rationale).toBe('AI')
    expect(out[0]!.interventions).toEqual([{ kind: 'plant_avicennia', sapling_count: 440 }])
  })
  test('adds a new zone item and drops an emptied one', () => {
    const added = withZoneInterventions([item], 'KSL-A1', [{ kind: 'stop_pollution' }])
    expect(added.map((i) => i.zone_id)).toEqual(['KSL-B3', 'KSL-A1'])
    expect(added[1]!.priority).toBe(3)
    expect(withZoneInterventions([item], 'KSL-B3', [])).toEqual([])
  })
})

test('default saplings follow min(mud, 0.5 ha) x 4,400', () => {
  expect(defaultSaplings(30)).toBe(1320)
  expect(defaultSaplings(80)).toBe(2200)
  expect(defaultSaplings(undefined)).toBe(1100)
  expect(defaultSaplings(0)).toBe(100)
})

test('year label', () => {
  expect(formatYear(2035)).toBe('2035')
  expect(formatYear(2030.5)).toBe('2030.5')
})

describe('future trees', () => {
  test('canopy loss is relative to 2026', () => {
    const s = [yp(2026, 0.6), yp(2027, 0.3)]
    expect(canopyLoss(s, 2026)).toBe(0)
    expect(canopyLoss(s, 2027)).toBeCloseTo(0.5)
    expect(canopyLoss(undefined, 2027)).toBe(0)
  })

  test('the share of declining trees follows the zone loss', () => {
    const n = 2000
    const declining = (loss: number) => Array.from({ length: n }, (_, i) => treeDecline(i, loss)).filter((d) => d > 0).length / n
    expect(declining(0)).toBe(0)
    expect(declining(0.3)).toBeGreaterThan(0.25)
    expect(declining(0.3)).toBeLessThan(0.4)
    expect(declining(1)).toBe(1)
    expect(Array.from({ length: n }, (_, i) => treeDecline(i, 1)).every((d) => d === 1)).toBe(true)
  })

  test('saplings grow with the cohort fraction when the API passes it, else with the canopy gained', () => {
    const withCohorts = [yp(2026, 0.5, { cohort_fraction: 0 }), yp(2035, 0.6, { cohort_fraction: 0.8 })]
    expect(saplingGrowth(withCohorts, undefined, 2035)).toBeCloseTo(0.8)
    const w = [yp(2026, 0.5), yp(2035, 0.7)]
    const wo = [yp(2026, 0.5), yp(2035, 0.5)]
    expect(saplingGrowth(w, wo, 2026)).toBe(0)
    expect(saplingGrowth(w, wo, 2030.5)).toBeCloseTo(0.5)
    expect(saplingGrowth(w, wo, 2035)).toBeCloseTo(1)
  })

  test('saplings stand on the zone mud pixels', () => {
    const classes = new Uint8Array(256 * 256)
    // Zone B3 (col 1, row 2): one mud pixel at its top-left raster cell.
    const x = Math.floor(256 / 5)
    const y = Math.floor((2 * 256) / 5)
    classes[y * 256 + x] = 3
    for (const [e, s] of saplingSpots(1, 2, 10, classes)) {
      expect(Math.floor(e / (500 / 256))).toBe(x)
      expect(Math.floor(s / (500 / 256))).toBe(y)
    }
    for (const [e, s] of saplingSpots(1, 2, 10, null)) {
      expect(e).toBeGreaterThanOrEqual(100)
      expect(e).toBeLessThan(200)
      expect(s).toBeGreaterThanOrEqual(200)
      expect(s).toBeLessThan(300)
    }
  })
})
