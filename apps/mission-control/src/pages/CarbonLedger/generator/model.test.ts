import { describe, expect, it } from 'vitest'
import { calculateReport, reportCSV, type RequestInput } from './model'
const input = (): RequestInput => ({ site: 'Farm', lat: 3, lng: 101, scene: 'S2', start: '2024-01-01', end: '2025-01-01', uncertainty: 10, buffer: 20, sections: [{ id: 'A1', area: 1, project: 12, baseline: 2, emissions: 1, leakage: 0.5, claimed: 2, evidence: '' }] })
describe('section credit reports', () => {
  it('deducts baseline, emissions, leakage, uncertainty, buffer and prior claims in order', () => {
    const report = calculateReport(input(), 'report', 'now')
    const expected = 8.5 * 366 / 365.25 * 0.9 * 0.8
    expect(report.sections[0]!.potential).toBeCloseTo(expected)
    expect(report.totals.available).toBeCloseTo(expected - 2)
    expect(report.timeline[0]!.available).toBe(0)
    expect(report.timeline.at(-1)!.available).toBeCloseTo(report.totals.available)
  })
  it('does not offset an overclaimed section against another section', () => {
    const request = input(); request.sections.push({ ...request.sections[0]!, id: 'B1', claimed: 100 })
    const report = calculateReport(request, 'r', 'now')
    expect(report.sections[1]!.available).toBe(0)
    expect(report.totals.overclaimed).toBeGreaterThan(90)
    expect(report.totals.available).toBe(report.sections[0]!.available)
  })
  it('retains negative net emissions but never generates negative credits', () => {
    const request = input(); request.sections[0]!.project = 0
    const r = calculateReport(request, 'r', 'now')
    expect(r.totals.net).toBeLessThan(0); expect(r.totals.available).toBe(0); expect(r.totals.potential).toBe(0)
  })
  it('excludes zero-area sections and supports 100% reserves', () => {
    const request = input(); request.sections[0]!.area = 0
    expect(calculateReport(request, 'r', 'now').totals.potential).toBe(0)
    request.sections[0]!.area = 1; request.buffer = 100
    expect(calculateReport(request, 'r', 'now').totals.potential).toBe(0)
  })
  it.each(['2024-02-30', '', 'wrong'])('rejects invalid dates %s', date => {
    const request = input(); request.end = date
    expect(() => calculateReport(request, 'r', 'now')).toThrow()
  })
  it('rejects reversed, excessive and zero-length periods', () => {
    for (const end of ['2023-01-01', '2024-01-01', '2040-01-01']) { const request = input(); request.end = end; expect(() => calculateReport(request, 'r', 'now')).toThrow() }
  })
  it('rejects invalid numbers, duplicate IDs and oversize sections', () => {
    for (const area of [-1, NaN, Infinity, 1.1]) { const request = input(); request.sections[0]!.area = area; expect(() => calculateReport(request, 'r', 'now')).toThrow() }
    const request = input(); request.sections.push({ ...request.sections[0]! }); expect(() => calculateReport(request, 'r', 'now')).toThrow()
    request.sections.pop(); request.buffer = 101; expect(() => calculateReport(request, 'r', 'now')).toThrow()
  })
  it('rejects arithmetic overflow', () => {
    const request = input(); request.sections[0]!.project = Number.MAX_VALUE; request.end = '2030-01-01'
    expect(() => calculateReport(request, 'r', 'now')).toThrow('too large')
  })
  it('keeps snapshots immutable and recalculation idempotent', () => {
    const request = input(); const first = calculateReport(request, 'a', 'now'); request.sections[0]!.claimed = 4
    expect(first.input.sections[0]!.claimed).toBe(2)
    expect(calculateReport(input(), 'b', 'now').totals).toEqual(first.totals)
  })
  it('exports units, assumptions and escaped evidence with spreadsheet formula protection', () => {
    const request = input(); request.sections[0]!.evidence = '=SUM(1,2) "claim"'
    const csv = reportCSV(calculateReport(request, 'r', 'now'))
    expect(csv).toContain('Unclaimed estimate tCO2e'); expect(csv).toContain("'=SUM(1,2)"); expect(csv).toContain('""claim""')
  })
})
