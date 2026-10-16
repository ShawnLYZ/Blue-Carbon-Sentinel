import { SECTION_IDS, validateRequest, validateResponse, type VerificationRequest, type VerifierResponse } from './verification'
export const SIMULATION_MS = 8000
export function simulationStage(request: VerificationRequest, now: number) {
  const elapsed = Math.max(0, now - Date.parse(request.created))
  return elapsed < 1500 ? 'sent' : elapsed < 5000 ? 'processing' : elapsed < SIMULATION_MS ? 'checking' : 'complete'
}
/** Repeatable demo decisions, independent of satellite measurements and actual CCP assessment. */
export function simulateResponse(request: VerificationRequest, issuedAt: string): VerifierResponse {
  validateRequest(request)
  if (!request.simulation) throw new Error('Only simulation requests can receive demo decisions.')
  const years = (Date.parse(request.end) - Date.parse(request.start)) / 86400000 / 365.25
  const revision = request.snapshot?.conditionRevision ?? 0
  const sections = request.sections.map(id => {
    const index = SECTION_IDS.indexOf(id)
    const cells = Array.from({ length: 100 }, (_, i) => ({ i, rank: Math.sin((i % 10 + index + revision * .8) * .5) + Math.cos((Math.floor(i / 10) - index - revision * .6) * .6) }))
    cells.sort((a, b) => a.rank - b.rank)
    const eligible = (index + revision) % 7 === 0 ? 0 : 45 + (index * 7 + revision * 11) % 45
    const claimed = eligible ? 8 + index * 3 % 18 : 0
    const mask = Array.from({ length: 10 }, () => Array<string>(10).fill('0'))
    cells.forEach((c, rank) => { mask[Math.floor(c.i / 10)]![c.i % 10] = rank < eligible - claimed ? '1' : rank < eligible ? '2' : '0' })
    const total = +(eligible / 100 * 8 * years).toFixed(4)
    return { id, mask: mask.map(row => row.join('')), creditableTco2e: total, claimedTco2e: eligible ? +(total * claimed / eligible).toFixed(4) : 0, reason: eligible ? `SIMULATED condition revision ${revision}: sample spatial screening and prior-claim checks. Pattern and 8 tCO₂e/ha/year rate are illustrative; no real verification performed.` : 'SIMULATED: section excluded by example eligibility checks. No real verification performed.' }
  })
  return validateResponse({ requestId: request.id, simulation: true, verifier: 'Simulated verifier (demo only)', reportReference: `SIM-${request.id.slice(0, 8)}`, issuedAt, sections }, request)
}
