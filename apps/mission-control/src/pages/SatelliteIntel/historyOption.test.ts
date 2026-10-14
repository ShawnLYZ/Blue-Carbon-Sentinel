import { describe, expect, it } from 'vitest'
import type { History } from '@bcs/api-types'
import { AXIS_FIRST_YEAR, AXIS_LAST_YEAR, BASELINE_LABEL, historyOption, historyPoints } from './historyOption'

const h = {
  label: BASELINE_LABEL,
  series: {
    'KSL-A1': [{ year: 2016, canopy_pct: 70, vari_equiv: 0.3 }, { year: 2017, canopy_pct: 60, vari_equiv: 0.3 }],
    'KSL-B3': [{ year: 2016, canopy_pct: 50, vari_equiv: 0.2 }, { year: 2017, canopy_pct: 40, vari_equiv: 0.2 }],
  },
  real: [
    { t: '2026-10-12T02:00:00Z', zone_id: 'KSL-A1', canopy_pct: 80 },
    { t: '2026-10-12T02:00:00Z', zone_id: 'KSL-B3', canopy_pct: 60 },
    { t: '2025-06-01T00:00:00Z', zone_id: 'KSL-A1', canopy_pct: 99 },
  ],
} as unknown as History

describe('historyPoints', () => {
  it('averages zones by year and drops real points before 2026', () => {
    const p = historyPoints(h)
    expect(p.baseline).toEqual([[2016, 60], [2017, 50]])
    expect(p.real).toHaveLength(1)
    expect(p.real[0]![0]).toBeGreaterThan(2026.7)
    expect(p.real[0]![1]).toBe(70)
  })
  it('can select one zone', () => {
    expect(historyPoints(h, 'KSL-B3').baseline).toEqual([[2016, 50], [2017, 40]])
    expect(historyPoints(h, 'KSL-B3').real[0]![1]).toBe(60)
  })
})

describe('historyOption', () => {
  const o = historyOption(historyPoints(h))
  it('labels the axes and spans 2016-2035', () => {
    expect(o.yAxis.name).toBe('Canopy cover (%)')
    expect([o.xAxis.min, o.xAxis.max]).toEqual([AXIS_FIRST_YEAR, AXIS_LAST_YEAR])
  })
  it('draws the labelled baseline dashed and real points solid', () => {
    expect(o.series[0]!.name).toBe(BASELINE_LABEL)
    expect(o.series[0]!.lineStyle.type).toBe('dashed')
    expect(o.series[1]!.lineStyle.type).toBe('solid')
  })
})
