import { describe, expect, it } from 'vitest'
import { SECTION_IDS, decisionReport, validateRequest, validateResponse, type VerificationRequest, type VerifierResponse } from './verification'
const request = (): VerificationRequest => ({ version: 1, id: 'req', created: '2026-01-01T00:00:00Z', verifier: '', site: 'Farm', lat: 3, lng: 101, scene: 'S2', start: '2026-01-01', end: '2027-01-01', sections: ['A1', 'C3'], notes: '', framework: 'ICVCM Core Carbon Principles', status: 'pending' })
const response = (): VerifierResponse => ({ requestId: 'req', verifier: 'Example verifier', reportReference: 'ref', issuedAt: '2026-10-16T00:00:00Z', sections: [{ id: 'C3', mask: Array(10).fill('1111122000'), creditableTco2e: 12, claimedTco2e: 3, reason: 'Surveyed areas creditable; two columns already claimed.' }] })
describe('section verifier workflow', () => {
  it('validates the entire farm in one area-validation request', () => {
    const r = validateRequest({ ...request(), sections: [...SECTION_IDS], scope: 'whole-farm', purpose: 'area-validation' })
    expect(r.sections).toHaveLength(25); expect(r.purpose).toBe('area-validation')
    expect(() => validateRequest({ ...request(), scope: 'whole-farm' })).toThrow('all 25')
  })
  it('accepts a blank verifier and creates no automatic eligibility', () => {
    const r = validateRequest(request()); expect(r.verifier).toBe(''); expect(r.status).toBe('pending'); expect(r).not.toHaveProperty('credits')
  })
  it('rejects empty, duplicate and unknown requested sections', () => {
    for (const sections of [[], ['A1', 'A1'], ['Z8']]) expect(() => validateRequest({ ...request(), sections })).toThrow()
  })
  it('rejects an invalid reporting period', () => expect(() => validateRequest({ ...request(), end: '2025-01-01' })).toThrow())
  it('accepts partial responses and calculates credits only for received sections', () => {
    const r = decisionReport(request(), response())
    expect(r.sections.map(s => s.id)).toEqual(['C3']); expect(r.sections[0]!.area).toBe(.7)
    expect(r.totals.potential).toBeCloseTo(12); expect(r.totals.available).toBeCloseTo(9)
  })
  it('rejects mismatched requests and unrequested or duplicate decisions', () => {
    expect(() => validateResponse({ ...response(), requestId: 'wrong' }, request())).toThrow()
    const raw = response(); raw.sections[0]!.id = 'B2'; expect(() => validateResponse(raw, request())).toThrow()
    raw.sections = [response().sections[0]!, response().sections[0]!]; expect(() => validateResponse(raw, request())).toThrow()
  })
  it('requires exact spatial masks and provenance', () => {
    const raw = response(); raw.sections[0]!.mask[0] = '111X000000'; expect(() => validateResponse(raw, request())).toThrow()
    expect(() => validateResponse({ ...response(), verifier: '' }, request())).toThrow()
    expect(() => validateResponse({ ...response(), reportReference: '' }, request())).toThrow()
  })
  it('does not issue credits for fully ineligible masks', () => {
    const raw = response(); raw.sections[0]!.mask = Array(10).fill('0000000000')
    expect(() => validateResponse(raw, request())).toThrow()
    raw.sections[0]!.creditableTco2e = 0; raw.sections[0]!.claimedTco2e = 0
    expect(decisionReport(request(), raw).totals.available).toBe(0)
  })
  it('rejects invalid credit quantities', () => {
    for (const creditableTco2e of [-1, Infinity, NaN]) { const raw = response(); raw.sections[0]!.creditableTco2e = creditableTco2e; expect(() => validateResponse(raw, request())).toThrow() }
  })
})
