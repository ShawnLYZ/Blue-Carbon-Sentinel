import { describe, expect, test } from 'vitest'
import type { YearPoint } from '@bcs/api-types'
import { frameSources, interpYear, riskDistribution, textureBlend, type IllustrationKeys } from './interp'

const band = (v: number) => ({ low: v - 0.1, central: v, high: v + 0.1 })
function yp(year: number, canopy: number, risk: YearPoint['risk_class'] = 'low'): YearPoint {
  return {
    year,
    canopy: band(canopy),
    health: band(canopy / 2),
    land: band(1),
    risk_class: risk,
    stock_tco2e: band(canopy * 1000),
    seq_tco2e: band(0),
    additional_tco2e: band(canopy * 10),
  }
}

test('interpolates bands between years', () => {
  const s = [yp(2026, 0.6), yp(2027, 0.5)]; expect(interpYear(s, 2026.5).canopy.central).toBeCloseTo(0.55)
})

test('texture blend picks keyframe segments', () => {
  expect(textureBlend(2028)).toEqual({ from: 2026, to: 2030, t: 0.5 }); expect(textureBlend(2035)).toEqual({ from: 2030, to: 2035, t: 1 })
})

describe('interpYear', () => {
  const s = [yp(2026, 0.6, 'low'), yp(2027, 0.5, 'medium'), yp(2028, 0.2, 'critical')]

  test('every band value is interpolated, low and high included', () => {
    const p = interpYear(s, 2027.25)
    expect(p.year).toBeCloseTo(2027.25)
    expect(p.canopy.low).toBeCloseTo(0.325)
    expect(p.canopy.high).toBeCloseTo(0.525)
    expect(p.stock_tco2e.central).toBeCloseTo(425)
    expect(p.additional_tco2e.central).toBeCloseTo(4.25)
    expect(p.health.central).toBeCloseTo(0.2125)
  })

  test('integer years return that keyframe; outside the horizon clamps', () => {
    expect(interpYear(s, 2027).canopy.central).toBeCloseTo(0.5)
    expect(interpYear(s, 2020).canopy.central).toBeCloseTo(0.6)
    expect(interpYear(s, 2040).canopy.central).toBeCloseTo(0.2)
  })

  test('risk class is the nearest keyframe', () => {
    expect(interpYear(s, 2026.4).risk_class).toBe('low')
    expect(interpYear(s, 2026.6).risk_class).toBe('medium')
  })

  test('an empty series throws', () => {
    expect(() => interpYear([], 2030)).toThrow()
  })
})

describe('textureBlend', () => {
  test('2026 to 2030 blends the real capture toward 2030; 2030 to 2035 blends 2030 toward 2035', () => {
    expect(textureBlend(2026)).toEqual({ from: 2026, to: 2030, t: 0 })
    expect(textureBlend(2030)).toEqual({ from: 2026, to: 2030, t: 1 })
    expect(textureBlend(2032.5)).toEqual({ from: 2030, to: 2035, t: 0.5 })
  })

  test('clamps outside the horizon', () => {
    expect(textureBlend(2020)).toEqual({ from: 2026, to: 2030, t: 0 })
    expect(textureBlend(2040)).toEqual({ from: 2030, to: 2035, t: 1 })
  })
})

describe('frameSources', () => {
  const none: IllustrationKeys = new Set()

  test('without ready illustrations, yearly repaint textures blend between integer years', () => {
    expect(frameSources(2026, 'with', none)).toEqual({
      colour: { from: { kind: 'capture' }, to: { kind: 'repaint', year: 2027 }, t: 0 },
      height: { from: 2026, to: 2027, t: 0 },
      illustrated: false,
    })
    const f = frameSources(2031.25, 'without', none)
    expect(f.colour).toEqual({ from: { kind: 'repaint', year: 2031 }, to: { kind: 'repaint', year: 2032 }, t: 0.25 })
    expect(f.height).toEqual({ from: 2031, to: 2032, t: 0.25 })
    expect(f.illustrated).toBe(false)
  })

  test('2035 uses the 2035 repaint', () => {
    const f = frameSources(2035, 'with', none)
    expect(f.colour.t).toBe(1)
    expect(f.colour.to).toEqual({ kind: 'repaint', year: 2035 })
    expect(f.height).toEqual({ from: 2034, to: 2035, t: 1 })
  })

  test('a ready keyframe illustration switches to keyframe segments and is badged', () => {
    const ready: IllustrationKeys = new Set(['with:2030'])
    const f = frameSources(2028, 'with', ready)
    expect(f.colour).toEqual({ from: { kind: 'capture' }, to: { kind: 'illustration', year: 2030 }, t: 0.5 })
    expect(f.illustrated).toBe(true)
    // The other scenario is not illustrated.
    expect(frameSources(2028, 'without', ready).illustrated).toBe(false)
  })

  test('2030 to 2035 starts from the 2030 illustration when ready, else the 2030 repaint', () => {
    const only2035: IllustrationKeys = new Set(['with:2035'])
    expect(frameSources(2032.5, 'with', only2035).colour).toEqual({
      from: { kind: 'repaint', year: 2030 },
      to: { kind: 'illustration', year: 2035 },
      t: 0.5,
    })
    const both: IllustrationKeys = new Set(['with:2030', 'with:2035'])
    expect(frameSources(2032.5, 'with', both).colour.from).toEqual({ kind: 'illustration', year: 2030 })
  })

  test('the 2030 illustration alone still shows just past 2030 and is badged', () => {
    const only2030: IllustrationKeys = new Set(['with:2030'])
    const f = frameSources(2031, 'with', only2030)
    expect(f.colour.from).toEqual({ kind: 'illustration', year: 2030 })
    expect(f.illustrated).toBe(true)
  })

  test('the badge needs the illustration to be visible in the blend', () => {
    const only2035: IllustrationKeys = new Set(['with:2035'])
    expect(frameSources(2030, 'with', only2035).illustrated).toBe(false)
    expect(frameSources(2026, 'with', new Set(['with:2030'])).illustrated).toBe(false)
  })
})

test('risk distribution counts zones per class at the nearest keyframe', () => {
  const zones = {
    A: [yp(2026, 0.6, 'low'), yp(2027, 0.5, 'high')],
    B: [yp(2026, 0.6, 'low'), yp(2027, 0.5, 'critical')],
    C: [yp(2026, 0.6, 'medium'), yp(2027, 0.5, 'medium')],
  }
  expect(riskDistribution(zones, 2026)).toEqual({ low: 2, medium: 1, high: 0, critical: 0 })
  expect(riskDistribution(zones, 2026.8)).toEqual({ low: 0, medium: 1, high: 1, critical: 1 })
})
