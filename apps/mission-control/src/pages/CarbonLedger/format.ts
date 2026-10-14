// Text formats of the Carbon Ledger page (design §23 eligibility tracker, §26).
import type { CoverageGap, ZoneEligibility } from '@bcs/api-types'

export const DISCLAIMER = 'Demo record — not a certified carbon credit'

/** "2/3 captures". */
export function capturesText(c: ZoneEligibility['camera']): string {
  return `${c.have}/${c.need} captures`
}

/** Seconds as m:ss ("80" -> "1:20"). */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** "1:20 / 2:00 healthy". */
export function sensorText(s: ZoneEligibility['sensors']): string {
  return `${clock(s.healthy_s)} / ${clock(s.need_s)} healthy`
}

/** Truncated (never rounded) to 2 dp, so a value just under the need never reads as reaching it. */
function floor2(x: number): string {
  return (Math.floor(x * 100 + 1e-9) / 100).toFixed(2)
}

/** "0.83 ≥ 0.80 ✓" or "0.79 < 0.80 ✗" (0.7996 shows 0.79: truncated, not rounded across the threshold). */
export function confidenceText(c: ZoneEligibility['confidence']): string {
  const v = floor2(c.value)
  const n = c.need.toFixed(2)
  return c.ok ? `${v} ≥ ${n} ✓` : `${v} < ${n} ✗`
}

/** "chain ✓" or "chain ✗". */
export function chainText(c: ZoneEligibility['chain']): string {
  return c.ok ? 'chain ✓' : 'chain ✗'
}

export const tick = (ok: boolean): string => (ok ? '✓' : '✗')

/** A quantity string (decimal, 3 dp) with its unit. */
export function tco2e(q: string | number): string {
  const n = typeof q === 'number' ? q : Number(q)
  return `${Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) : String(q)} tCO₂e`
}

export const CHECKLIST_LABELS = {
  satellite: 'Satellite evidence (an evidence-grade capture)',
  sensor: 'Sensor evidence (every plan zone covered by a node)',
  ai: 'AI forecast (ready, with parameters)',
  restoration: 'Restoration plan applied',
} as const

export type ChecklistKey = keyof typeof CHECKLIST_LABELS
export const CHECKLIST_KEYS = Object.keys(CHECKLIST_LABELS) as ChecklistKey[]

/** True when the sensor rule failed because no node covers the zone. */
export function isNoCoverage(s: ZoneEligibility['sensors']): boolean {
  return !s.ok && /no coverage/i.test(s.reason ?? '')
}

/** The coverage-gap suggestion text for a zone ("add a soil probe at e 40 m, s 25 m"), or null without one. */
export function gapText(gaps: CoverageGap[], zoneId: string): string | null {
  const g = gaps.find((x) => x.zone_id === zoneId)
  if (!g) return null
  const kind = g.node_type === 'soil_probe' ? 'soil probe' : 'water-quality node'
  return `Suggested: add a ${kind} at e ${g.e_m.toFixed(0)} m, s ${g.s_m.toFixed(0)} m (${g.reason})`
}
