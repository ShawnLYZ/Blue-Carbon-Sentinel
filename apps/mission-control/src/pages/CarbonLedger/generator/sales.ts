import { calculateReport, type Report } from './model'
export interface LocalSale {
  simulation?: boolean; id: string; created: string; reportId: string; lat: number; lng: number; start: string; end: string
  amount: number; allocations: { section: string; amount: number }[]
}
export function relevantSales(report: Report, sales: LocalSale[]) {
  // Conservatively reserve the entire sale in any overlapping period, preventing re-generation from resetting balances.
  return sales.filter(s => !!s.simulation === !!report.simulation && s.lat === report.input.lat && s.lng === report.input.lng && s.start < report.input.end && s.end > report.input.start)
}
export function withSales(report: Report, sales: LocalSale[]): Report {
  const relevant = relevantSales(report, sales)
  if (!relevant.length) return report
  const input = structuredClone(report.input)
  for (const section of input.sections) section.claimed += relevant.reduce((sum, sale) => sum + sale.allocations.filter(a => a.section === section.id).reduce((n, a) => n + a.amount, 0), 0)
  return { ...calculateReport(input, report.id, report.created), simulation: report.simulation }
}
export function createSale(report: Report, amount: number, id: string, created: string): LocalSale {
  if (!Number.isFinite(amount) || amount <= 0 || Math.abs(amount * 100 - Math.round(amount * 100)) > 1e-7) throw new Error('Enter a positive amount with up to 2 decimal places.')
  if (amount > report.totals.available) throw new Error('Amount exceeds the available unclaimed balance.')
  let remaining = amount
  const allocations: LocalSale['allocations'] = []
  for (const section of report.sections) {
    const taken = Math.min(remaining, section.available)
    if (taken > 0) { allocations.push({ section: section.id, amount: taken }); remaining = Math.max(0, remaining - taken) }
    if (remaining === 0) break
  }
  return { simulation: !!report.simulation, id, created, reportId: report.id, lat: report.input.lat, lng: report.input.lng, start: report.input.start, end: report.input.end, amount, allocations }
}
