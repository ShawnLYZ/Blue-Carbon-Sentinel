export type RiskClass = 'low' | 'medium' | 'high' | 'critical'

const RISK: Record<RiskClass, string> = {
  low: '#2ecc71',
  medium: '#f1c40f',
  high: '#ff8c1a',
  critical: '#ff3b3b',
}

export function riskColor(cls: RiskClass): string {
  return RISK[cls]
}

/** `formatValue(7.456, 'PSU', 1)` gives `"7.5 PSU"`. Non-finite values show an em dash. */
export function formatValue(v: number, unit: string, dp: number): string {
  if (!Number.isFinite(v)) return '—'
  const n = v.toFixed(dp)
  return unit ? `${n} ${unit}` : n
}

/** AI tier display names (addendum F5). */
export const TIER_LABELS: Record<string, string> = {
  robotics_er: 'Gemini Robotics-ER 2',
  gemini_primary: 'Gemini 2.5 Flash',
  gemini_secondary: 'Gemini 3.1 Flash-Lite',
  gemma_local: 'Gemma 4 · local',
  rules: 'Rules',
}

export function tierLabel(tier: string, cached = false): string {
  const base = TIER_LABELS[tier] ?? tier
  return cached ? `${base} · cached` : base
}
