import { calculateReport, type Report } from './model'
export const SECTION_IDS = Array.from({ length: 25 }, (_, i) => `${'ABCDE'[i % 5]}${Math.floor(i / 5) + 1}`)
export interface VerificationRequest {
  snapshot?: { id: string; capturedAt: string; sceneId: string; acquiredAt: string; conditionRevision: number }; simulation?: boolean; version: 1; id: string; created: string; verifier: string; site: string; lat: number; lng: number; scene: string
  start: string; end: string; sections: string[]; notes: string; purpose?: 'area-validation'; scope?: 'whole-farm'
  framework: 'ICVCM Core Carbon Principles'; status: 'pending'
}
export interface SectionDecision {
  id: string; mask: string[]; creditableTco2e: number; claimedTco2e: number; reason: string
}
export interface VerifierResponse {
  simulation?: boolean; requestId: string; verifier: string; reportReference: string; issuedAt: string; sections: SectionDecision[]
}
export function validateRequest(request: VerificationRequest): VerificationRequest {
  if (!request.id || !request.sections.length || new Set(request.sections).size !== request.sections.length || request.sections.some(id => !SECTION_IDS.includes(id))) throw new Error('Select at least one valid section.')
  if (request.scope === 'whole-farm' && request.sections.length !== SECTION_IDS.length) throw new Error('Whole-farm validation must include all 25 sectors.')
  if (!Number.isFinite(request.lat) || !Number.isFinite(request.lng) || Math.abs(request.lat) > 90 || Math.abs(request.lng) > 180) throw new Error('Invalid site coordinates.')
  // Reuse the calculator date validation without producing any credits.
  calculateReport({ ...request, uncertainty: 0, buffer: 0, sections: [{ id: request.sections[0]!, area: 0, project: 0, baseline: 0, emissions: 0, leakage: 0, claimed: 0, evidence: '' }] }, request.id, request.created)
  return structuredClone(request)
}
export function validateResponse(raw: unknown, request: VerificationRequest): VerifierResponse {
  const r = raw as VerifierResponse
  if (!!r?.simulation !== !!request.simulation) throw new Error('Simulated reports cannot be mixed with non-simulation requests.')
  if (!r || r.requestId !== request.id) throw new Error('Report request ID must match the selected request.')
  if (typeof r.verifier !== 'string' || !r.verifier.trim() || typeof r.reportReference !== 'string' || !r.reportReference.trim() || !Number.isFinite(Date.parse(r.issuedAt))) throw new Error('Report needs a verifier, report reference and valid issue date.')
  if (!Array.isArray(r.sections) || !r.sections.length) throw new Error('Report must include at least one section decision.')
  const seen = new Set<string>()
  for (const s of r.sections) {
    if (!s || !request.sections.includes(s.id) || seen.has(s.id)) throw new Error('Report includes a duplicate or unrequested section.')
    seen.add(s.id)
    if (!Array.isArray(s.mask) || s.mask.length !== 10 || s.mask.some(row => typeof row !== 'string' || !/^[012]{10}$/.test(row))) throw new Error(`Section ${s.id}: supply a 10 × 10 eligibility mask (1 = unclaimed creditable, 2 = already claimed, 0 = not creditable).`)
    if (![s.creditableTco2e, s.claimedTco2e].every(v => Number.isFinite(v) && v >= 0) || typeof s.reason !== 'string' || !s.reason.trim()) throw new Error(`Section ${s.id}: provide non-negative credit quantities and a decision reason.`)
    if (s.claimedTco2e > 0 && !s.mask.some(row => row.includes('2'))) throw new Error(`Section ${s.id}: map already-claimed areas with mask code 2.`)
    if (s.creditableTco2e > s.claimedTco2e && !s.mask.some(row => row.includes('1'))) throw new Error(`Section ${s.id}: unclaimed credits need mapped creditable areas.`)
    if (s.creditableTco2e > 0 && s.claimedTco2e >= s.creditableTco2e && s.mask.some(row => row.includes('1'))) throw new Error(`Section ${s.id}: fully claimed quantities cannot have unclaimed creditable cells.`)
    if (!s.mask.some(row => /[12]/.test(row)) && s.creditableTco2e > 0) throw new Error(`Section ${s.id}: credits cannot be assigned to a fully ineligible area.`)
  }
  return structuredClone(r)
}
/** Quantities and spatial eligibility come only from the received report. The derived rate is an accounting representation, not a new ecological estimate. */
export function decisionReport(request: VerificationRequest, response: VerifierResponse): Report {
  validateResponse(response, request)
  const years = (Date.parse(request.end) - Date.parse(request.start)) / 86400000 / 365.25
  const sections = response.sections.map(s => {
    const area = s.mask.join('').split('').filter(c => c === '1' || c === '2').length / 100
    return { id: s.id, area, project: area ? s.creditableTco2e / area / years : 0, baseline: 0, emissions: 0, leakage: 0, claimed: s.claimedTco2e, evidence: `${response.verifier} · ${response.reportReference} · ${s.reason}` }
  })
  return { ...calculateReport({ ...request, uncertainty: 0, buffer: 0, sections }, `${request.id}:${response.reportReference}`, response.issuedAt), simulation: !!response.simulation }
}
export const CCP_CHECKLIST = [
  ['Governance', 'Programme governance and verifier identity'], ['Tracking', 'Unique project and section identifiers'], ['Transparency', 'Public report and supporting evidence'], ['Independent verification', 'Validation and verification evidence'], ['Additionality', 'Evidence removals exceed the baseline'], ['Permanence', 'Reversal risk and safeguards'], ['Robust quantification', 'Methods, measurements and uncertainty'], ['No double counting', 'Prior claims, registry and ownership checks'], ['Safeguards', 'Social and environmental safeguards'], ['Net-zero transition', 'Compatibility with net-zero transition'],
] as const
