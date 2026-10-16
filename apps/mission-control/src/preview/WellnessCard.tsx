import type { Raster } from './satellite'
import { RISK_PALETTE, type Attribute, type RiskZone } from './scenarioRisk'
import { wellnessSummary } from './wellness'

export function WellnessCard({ zone, raster, active, compact = false }: { zone: RiskZone; raster: Raster | null; active: Attribute[]; compact?: boolean }) {
  const summary = wellnessSummary(zone, active, raster)
  return <section className={`dt-wellness${compact ? ' dt-wellness--compact' : ''}`} aria-label={`Zone ${zone.id} wellness summary`}>
    <header><strong>Zone {zone.id}</strong><span style={{ color: RISK_PALETTE[summary.risk] }}>{summary.score === null ? 'Unassessed' : `${summary.score}% stress · ${summary.risk}`}</span></header>
    <div className="dt-wellness-observed"><span>{summary.clearPct}% clear land</span><span>{summary.vegetationPct === null ? '—' : `${summary.vegetationPct}%`} vegetated pixels</span></div>
    <div className="dt-wellness-columns"><span>Attribute / value</span><span>Stress</span></div>
    <div className="dt-wellness-rows">{summary.rows.map(row => <div key={row.key}><span><b>{row.label}</b><small>{row.value} · {row.source}</small></span><div className="dt-wellness-bar"><i style={{ width: `${row.pct ?? 0}%`, background: RISK_PALETTE[row.risk] }} /></div><strong style={{ color: RISK_PALETTE[row.risk] }}>{!row.enabled ? 'Off' : row.pct === null ? '—' : `${row.pct}%`}</strong></div>)}</div>
    <p className="dt-wellness-good"><b>Good:</b> {summary.good}</p>
    <p className="dt-wellness-concern"><b>{summary.score === null ? 'Data:' : summary.risk === 'low' ? 'Watch:' : 'Concern:'}</b> {summary.concern}</p>
    <footer>Percentages are model stress scores, not measured health or survival rates. Water and soil values are scenario assumptions.</footer>
  </section>
}
