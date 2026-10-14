// The numbers under each map for the selected year (US 144, 145): mangrove cover, carbon stock, the risk
// distribution and the "with" - "without" difference in additional tCO2e. All from the forecast, never from
// images. The stock is a STANDING ecosystem stock (soil included, Donato 2011); the additional figure is the
// extra sequestration over 2026-2035 plus avoided biomass loss. They differ by about 100x and never add (R6).
import { riskColor } from '@bcs/ui'
import type { Forecast } from '@bcs/api-types'
import { RISK_CLASSES, interpYear, riskDistribution, type Scenario } from '../../lib/interp'
import { formatYear } from './YearSlider'

const int = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

function pct(v: number): string {
  return `${(v * 100).toFixed(1)} %`
}

export function signed(v: number): string {
  const r = Math.round(v)
  return `${r > 0 ? '+' : r < 0 ? '−' : '±'}${int.format(Math.abs(r))}`
}

export function ScenarioNumbers({ forecast, scenario, year }: { forecast: Forecast | null; scenario: Scenario; year: number }) {
  const testId = `numbers-${scenario}`
  const site = forecast?.scenarios[scenario].site ?? []
  if (!forecast || site.length === 0)
    return (
      <div className="tt-numbers" data-testid={testId}>
        <p className="hint">{forecast ? 'This forecast has no zones.' : 'Waiting for a forecast.'}</p>
      </div>
    )
  const p = interpYear(site, year)
  const withP = interpYear(forecast.scenarios.with.site, year)
  const withoutP = interpYear(forecast.scenarios.without.site, year)
  const diff = withP.additional_tco2e.central - withoutP.additional_tco2e.central
  const risk = riskDistribution(forecast.scenarios[scenario].zones, year)
  return (
    <div className="tt-numbers" data-testid={testId}>
      <div className="tt-numbers__year bcs-mono">{formatYear(year)}</div>
      <dl className="tt-numbers__grid">
        <div>
          <dt>Mangrove cover</dt>
          <dd>
            <strong className="bcs-mono">{pct(p.canopy.central)}</strong>
            <span className="tt-numbers__band bcs-mono">
              {pct(Math.min(p.canopy.low, p.canopy.high))} – {pct(Math.max(p.canopy.low, p.canopy.high))}
            </span>
          </dd>
        </div>
        <div>
          <dt>Carbon stock (standing)</dt>
          <dd>
            <strong className="bcs-mono">{int.format(p.stock_tco2e.central)} tCO₂e</strong>
            <span className="tt-numbers__note">whole ecosystem incl. soil; Donato 2011</span>
          </dd>
        </div>
        <div>
          <dt>Risk (zones)</dt>
          <dd className="tt-numbers__risk">
            {RISK_CLASSES.map((k) => (
              <span key={k} className="tt-risk" style={{ borderColor: riskColor(k) }} title={`${k}: ${risk[k]} zones`}>
                <span className="tt-risk__dot" style={{ background: riskColor(k) }} />
                {k} {risk[k]}
              </span>
            ))}
          </dd>
        </div>
        <div>
          <dt>Additional 2026–{formatYear(year)} (with − without)</dt>
          <dd>
            <strong className="bcs-mono">{signed(diff)} tCO₂e</strong>
            <span className="tt-numbers__note">extra sequestration since 2026, not part of the stock</span>
          </dd>
        </div>
      </dl>
    </div>
  )
}
