import { describe, expect, it } from 'vitest'
import { calculateReport, type RequestInput } from './model'
import { createSale, withSales } from './sales'
const input = (): RequestInput => ({ site: 'Farm', lat: 3, lng: 101, scene: 's2', start: '2026-01-01', end: '2027-01-01', buffer: 0, uncertainty: 0, sections: ['A1', 'B1'].map(id => ({ id, area: 1, project: 10, baseline: 0, emissions: 0, leakage: 0, claimed: 0, evidence: '' })) })
const report = () => calculateReport(input(), 'report', 'now')
describe('local credit sales', () => {
  it('allocates across sections, reduces totals, and preserves the original report', () => {
    const original = report(), sale = createSale(original, 12, 'sale', 'now')
    expect(sale.allocations.map(a => a.section)).toEqual(['A1', 'B1'])
    const result = withSales(original, [sale])
    expect(result.totals.available).toBeCloseTo(original.totals.available - 12)
    expect(result.sections[0]!.available).toBe(0)
    expect(original.input.sections[0]!.claimed).toBe(0)
    expect(result.timeline.at(-1)!.available).toBeCloseTo(result.totals.available)
  })
  it.each([0, -1, NaN, Infinity, 0.001, 100])('rejects invalid or excessive amount %s', amount => expect(() => createSale(report(), amount, 's', 'now')).toThrow())
  it('does not reset sold quantities on regeneration or different report IDs', () => {
    const sale = createSale(report(), 5, 'sale', 'now')
    const regenerated = calculateReport(input(), 'new', 'now')
    expect(withSales(regenerated, [sale]).totals.available).toBeCloseTo(report().totals.available - 5)
    expect(withSales(regenerated, []).totals.available).toBeCloseTo(report().totals.available)
  })
  it('reserves sales for overlapping periods, but not adjacent periods or other sites', () => {
    const sale = createSale(report(), 5, 'sale', 'now')
    const overlap = input(); overlap.start = '2026-06-01'
    const r = calculateReport(overlap, 'new', 'now')
    expect(withSales(r, [sale]).totals.available).toBeCloseTo(r.totals.available - 5)
    const next = input(); next.start = '2027-01-01'; next.end = '2028-01-01'
    const n = calculateReport(next, 'n', 'now'); expect(withSales(n, [sale])).toEqual(n)
    const other = input(); other.lat = 4
    const o = calculateReport(other, 'o', 'now'); expect(withSales(o, [sale])).toEqual(o)
  })
  it('rejects a subsequent sale that exceeds the remaining balance', () => {
    const sale = createSale(report(), 15, 'sale', 'now')
    expect(() => createSale(withSales(report(), [sale]), 6, 'next', 'now')).toThrow('exceeds')
  })
})
