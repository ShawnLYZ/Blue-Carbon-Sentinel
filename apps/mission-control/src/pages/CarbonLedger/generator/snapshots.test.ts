import { describe, expect, it } from 'vitest'
import { conditionRevision, coverageChanges } from './snapshots'
import { simulateResponse } from './simulation'
import type { VerificationRequest } from './verification'
describe('assessment capture history', () => {
  it('advances demo conditions only after existing simulated captures', () => {
    expect(conditionRevision([])).toBe(1)
    expect(conditionRevision([{ simulation: true, snapshot: { conditionRevision: 3 } }, { simulation: false, snapshot: { conditionRevision: 30 } }])).toBe(4)
  })
  it('measures gained and lost creditable cells only in matched sectors', () => {
    const before = [{ id: 'A1', mask: ['1100'] }, { id: 'B1', mask: ['1111'] }]
    const after = [{ id: 'A1', mask: ['1010'] }, { id: 'C1', mask: ['1111'] }]
    expect(coverageChanges(before, after)).toEqual({ gained: 1, lost: 1, compared: 4, gainedPct: 25, lostPct: 25 })
    expect(coverageChanges([], after).compared).toBe(0)
  })
  it('keeps a past assessment repeatable while a new simulated capture may differ', () => {
    const request: VerificationRequest = { version: 1, id: 'one', created: '2026-01-01T00:00:00Z', verifier: '', site: 'Farm', lat: 3, lng: 101, scene: 'same-acquisition', start: '2026-01-01', end: '2027-01-01', sections: ['C3', 'D3'], notes: '', framework: 'ICVCM Core Carbon Principles', status: 'pending', simulation: true, snapshot: { id: 'one', capturedAt: '2026-01-01T00:00:00Z', sceneId: 'same-acquisition', acquiredAt: '2025-12-30T00:00:00Z', conditionRevision: 1 } }
    const first = simulateResponse(request, request.created)
    const next = { ...request, id: 'two', snapshot: { ...request.snapshot!, id: 'two', conditionRevision: 2 } }
    expect(simulateResponse(request, request.created)).toEqual(first)
    expect(simulateResponse(next, next.created).sections).not.toEqual(first.sections)
    expect(request.snapshot!.conditionRevision).toBe(1)
  })
})
