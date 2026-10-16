export interface SectionInput {
  id: string; area: number; project: number; baseline: number; emissions: number; leakage: number
  claimed: number; evidence: string
}
export interface RequestInput {
  site: string; lat: number; lng: number; scene: string; start: string; end: string
  uncertainty: number; buffer: number; sections: SectionInput[]
}
export interface SectionResult extends SectionInput {
  gross: number; deductions: number; net: number; potential: number; available: number; overclaimed: number
}
export interface Report {
  simulation?: boolean; version: 1; id: string; created: string; input: RequestInput; days: number; sections: SectionResult[]
  totals: { area: number; net: number; potential: number; claimed: number; available: number; overclaimed: number }
  timeline: { date: string; potential: number; available: number }[]
}
const DAY = 86400000
function dateValue(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN
  const t = Date.parse(value + 'T00:00:00Z')
  return Number.isFinite(t) && new Date(t).toISOString().slice(0, 10) === value ? t : NaN
}
export function calculateReport(input: RequestInput, id: string, created: string): Report {
  const start = dateValue(input.start), end = dateValue(input.end)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) throw new Error('Choose a valid end date after the start date (end date is exclusive).')
  const days = (end - start) / DAY
  if (days > 3660) throw new Error('Reports support a maximum period of 10 years.')
  if (!input.site.trim() || !input.sections.length) throw new Error('Provide a site and at least one section.')
  if (!Number.isFinite(input.lat) || !Number.isFinite(input.lng) || Math.abs(input.lat) > 90 || Math.abs(input.lng) > 180) throw new Error('Site coordinates are invalid.')
  for (const v of [input.uncertainty, input.buffer]) if (!Number.isFinite(v) || v < 0 || v > 100) throw new Error('Uncertainty and buffer must be between 0% and 100%.')
  const ids = new Set<string>()
  const sections = input.sections.map(s => {
    if (!/^[A-E][1-5]$/.test(s.id) || ids.has(s.id)) throw new Error('Section IDs must be non-empty and unique.')
    ids.add(s.id)
    for (const key of ['area', 'project', 'baseline', 'emissions', 'leakage', 'claimed'] as const) {
      if (!Number.isFinite(s[key]) || s[key] < 0) throw new Error(`Section ${s.id}: all quantities must be finite and non-negative.`)
    }
    if (s.area > 1) throw new Error(`Section ${s.id}: area cannot exceed its 1 ha analytical boundary.`)
    const years = days / 365.25
    const gross = s.area * s.project * years
    const deductions = s.area * (s.baseline + s.emissions + s.leakage) * years
    const net = gross - deductions
    const potential = Math.max(0, net) * (1 - input.uncertainty / 100) * (1 - input.buffer / 100)
    if (![gross, deductions, net, potential].every(Number.isFinite)) throw new Error(`Section ${s.id}: quantities are too large to calculate.`)
    return { ...s, gross, deductions, net, potential, available: Math.max(0, potential - s.claimed), overclaimed: Math.max(0, s.claimed - potential) }
  })
  const totals = sections.reduce((a, s) => ({ area: a.area + s.area, net: a.net + s.net, potential: a.potential + s.potential, claimed: a.claimed + s.claimed, available: a.available + s.available, overclaimed: a.overclaimed + s.overclaimed }), { area: 0, net: 0, potential: 0, claimed: 0, available: 0, overclaimed: 0 })
  if (!Object.values(totals).every(Number.isFinite)) throw new Error('Total quantities are too large to calculate.')
  const dates = [start]
  let next = Date.UTC(new Date(start).getUTCFullYear(), new Date(start).getUTCMonth() + 1, 1)
  while (next < end) { dates.push(next); const d = new Date(next); next = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) }
  dates.push(end)
  // Projection within ONE report; repeated/overlapping report requests are never summed.
  const timeline = dates.map(t => {
    const fraction = (t - start) / (end - start)
    return { date: new Date(t).toISOString().slice(0, 10), potential: totals.potential * fraction, available: sections.reduce((sum, s) => sum + Math.max(0, s.potential * fraction - s.claimed), 0) }
  })
  return { version: 1, id, created, input: structuredClone(input), days, sections, totals, timeline }
}
export function reportCSV(report: Report): string {
  const safe = (value: string | number) => '"' + String(value).replace(/^[=+@\-]/, "'$&").replaceAll('"', '""') + '"'
  const rows: (string | number)[][] = [
    ['Report', report.id, 'Site', report.input.site, 'Start (inclusive)', report.input.start, 'End (exclusive)', report.input.end, 'Status', report.simulation ? 'SIMULATED DEMO DATA; no actual verification or issued credits' : 'Planning estimate; not issued credits'],
    ['Section', 'Area ha', 'Project tCO2e/ha/year', 'Baseline tCO2e/ha/year', 'Emissions tCO2e/ha/year', 'Leakage tCO2e/ha/year', 'Uncertainty %', 'Buffer %', 'Net tCO2e', 'Potential tCO2e', 'Already claimed tCO2e', 'Unclaimed estimate tCO2e', 'Overclaimed tCO2e', 'Evidence'],
    ...report.sections.map(s => [s.id, s.area, s.project, s.baseline, s.emissions, s.leakage, report.input.uncertainty, report.input.buffer, s.net, s.potential, s.claimed, s.available, s.overclaimed, s.evidence]),
  ]
  return rows.map(row => row.map(safe).join(',')).join('\r\n')
}
