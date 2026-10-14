import { describe, expect, test } from 'vitest'
import { activeRisks, mangroveHealthPct, nodesOnline, waterQualityStatus, type BandsConfig, type ClassLimits } from './kpis'

const z = (o: { canopy: number; vari: number; base: number }) => ({
  canopy_pct: o.canopy,
  vari_mean: o.vari,
  vari_drop: o.base - o.vari,
})
const a = (risk_class: 'low' | 'medium' | 'high' | 'critical') => ({ risk_class })

const bands: BandsConfig = {
  do_mg_l: { breakpoints: [[0.5, 1.0], [2.0, 0.6], [5.0, 0]] },
  turbidity_ntu: { breakpoints: [[25, 0], [100, 0.6], [300, 1.0]] },
}
const limits: ClassLimits = { low: 30, medium: 60, high: 80 }
const wq = (id: string, readings: Record<string, number>, status = 'online') =>
  ({ id, node_type: 'water_quality', status, latest: { readings } }) as never

test('mangrove health is canopy-weighted vari relative to baseline', () => {
  expect(mangroveHealthPct([z({ canopy: 50, vari: 0.2, base: 0.25 }), z({ canopy: 10, vari: 0.1, base: 0.1 })])).toBeCloseTo(
    ((50 * 0.8 + 10 * 1) / 60) * 100,
    1,
  )
})

test('mangrove health is null without a baseline or canopy', () => {
  expect(mangroveHealthPct([])).toBeNull()
  expect(mangroveHealthPct([{ canopy_pct: 40, vari_mean: 0.2, vari_drop: null }])).toBeNull()
  expect(mangroveHealthPct([z({ canopy: 0, vari: 0.2, base: 0.25 })])).toBeNull()
})

test('active risks counts high and critical only', () => {
  expect(activeRisks([a('high'), a('critical'), a('medium')])).toBe(2)
  expect(activeRisks([])).toBe(0)
})

test('nodes online counts online nodes against all registered, ignoring decommissioned', () => {
  const n = (status: string) => ({ status }) as never
  expect(nodesOnline([n('online'), n('online'), n('offline'), n('decommissioned')])).toEqual({ online: 2, total: 3 })
})

describe('water quality status', () => {
  test('is the class of the worst stressor across online WQ nodes', () => {
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 6, turbidity_ntu: 20 })], bands, limits)).toBe('low')
    // DO 2.0 mg/L is stress 0.6 -> high; turbidity is fine
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 2, turbidity_ntu: 20 })], bands, limits)).toBe('high')
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 6 }), wq('WQ-02', { do_mg_l: 0.4 })], bands, limits)).toBe('critical')
  })
  test('classes follow the configured limits', () => {
    const tight: ClassLimits = { low: 10, medium: 20, high: 30 }
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 2 })], bands, tight)).toBe('critical') // stress 0.6 = 60
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 6 })], bands, limits)).toBe('low')
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 2 })], bands, null)).toBeNull()
  })
  test('ignores offline nodes and other node types; null with no readings', () => {
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 0.4 }, 'offline')], bands, limits)).toBeNull()
    expect(waterQualityStatus([], bands, limits)).toBeNull()
    expect(waterQualityStatus([wq('WQ-01', { do_mg_l: 6 })], null, limits)).toBeNull()
  })
})
