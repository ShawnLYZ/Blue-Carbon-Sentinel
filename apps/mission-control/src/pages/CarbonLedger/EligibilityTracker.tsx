import { Panel } from '@bcs/ui'
import type { CoverageGap, ZoneEligibility } from '@bcs/api-types'
import { capturesText, chainText, confidenceText, gapText, isNoCoverage, sensorText, tick } from './format'

/** Per-zone progress against the four Verified rules (design §23). */
export function EligibilityTracker({
  zones,
  zoneLabel,
  gaps = [],
}: {
  zones: ZoneEligibility[]
  zoneLabel: (id: string) => string
  gaps?: CoverageGap[]
}) {
  return (
    <Panel title="Verified eligibility">
      {zones.length === 0 ? (
        <p className="hint" data-testid="eligibility-empty">Zones appear here once a plan has a Projected record.</p>
      ) : (
        <ul className="ledger-elig" data-testid="eligibility">
          {zones.map((z) => (
            <li key={`${z.plan_id}:${z.zone_id}`} data-testid="eligibility-zone" data-zone={z.zone_id} data-eligible={z.eligible}>
              <div className="ledger-elig__head">
                <strong>{zoneLabel(z.zone_id)}</strong>
                <span className="bcs-mono">{z.eligible ? 'eligible ✓' : 'not yet'}</span>
              </div>
              <div className="ledger-elig__rules bcs-mono">
                <span data-ok={z.camera.ok}>{tick(z.camera.ok)} {capturesText(z.camera)}</span>
                <span data-ok={z.sensors.ok}>{tick(z.sensors.ok)} {sensorText(z.sensors)}</span>
                <span data-ok={z.confidence.ok}>{confidenceText(z.confidence)}</span>
                <span data-ok={z.chain.ok}>{chainText(z.chain)}</span>
              </div>
              {z.reason && (
                <p className="hint" data-testid="eligibility-blocked">
                  {z.reason}
                </p>
              )}
              {z.sensors.reason && (
                <p className="hint" data-testid="eligibility-reason">
                  {z.sensors.reason}
                  {isNoCoverage(z.sensors) && (
                    <>
                      {gapText(gaps, z.zone_id) && (
                        <span data-testid="coverage-gap-suggestion"> · {gapText(gaps, z.zone_id)}</span>
                      )}
                      {' · '}
                      <a href="#/network" data-testid="coverage-gap-link">See the coverage gap on Sentinel Network</a>
                    </>
                  )}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
