import { describe, expect, it } from 'vitest'
import { simulateResponse, simulationStage } from './simulation'
import { decisionReport, type VerificationRequest } from './verification'
import { createSale, withSales } from './sales'
const request = (): VerificationRequest => ({ simulation: true, version: 1, id: 'demo', created: '2026-10-16T00:00:00Z', verifier: '', site: 'Farm', lat: 3, lng: 101, scene: '', start: '2026-01-01', end: '2027-01-01', sections: ['A1', 'C3', 'D3'], notes: '', framework: 'ICVCM Core Carbon Principles', status: 'pending' })
describe('simulated verifier', () => {
  it('moves from sent to processing, checking and complete', () => {
    const r = request(), start = Date.parse(r.created)
    expect([0, 2000, 6000, 8000].map(t => simulationStage(r, start + t))).toEqual(['sent', 'processing', 'checking', 'complete'])
  })
  it('returns repeatable masks and quantities only for requested sections', () => {
    const r = request(), response = simulateResponse(r, r.created)
    expect(response.simulation).toBe(true); expect(response.sections.map(s => s.id)).toEqual(r.sections)
    expect(simulateResponse(r, r.created)).toEqual(response)
    const report = decisionReport(r, response)
    expect(report.simulation).toBe(true); expect(report.totals.available).toBeGreaterThan(0)
    expect(response.sections[0]!.creditableTco2e).toBe(0)
    expect(response.sections[1]!.mask.join('')).toContain('2')
    expect(response.sections[1]!.mask.join('')).toContain('1')
  })
  it('cannot simulate a non-simulation request', () => expect(() => simulateResponse({ ...request(), simulation: false }, request().created)).toThrow())
  it('keeps demo sale balances separate from non-simulated reports', () => {
    const demo = decisionReport(request(), simulateResponse(request(), request().created))
    const sale = createSale(demo, 1, 'sale', 'now')
    expect(withSales(demo, [sale]).totals.available).toBeCloseTo(demo.totals.available - 1)
    const real = { ...demo, simulation: false }
    expect(withSales(real, [sale]).totals.available).toBe(real.totals.available)
    expect(withSales(demo, [sale]).simulation).toBe(true)
  })
})
