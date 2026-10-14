import { Panel } from '@bcs/ui'
import type { CarbonSummary } from '@bcs/api-types'
import { tco2e } from './format'

/** Standing stock, Projected total and Verified total (design §26). The stock is not a credit quantity. */
export function Summary({ summary }: { summary: CarbonSummary | null }) {
  return (
    <Panel title="Carbon summary">
      <dl className="ledger-summary" data-testid="carbon-summary">
        <div>
          <dt>Stock (standing, incl. soil)</dt>
          <dd className="bcs-mono">{summary ? tco2e(summary.stock_tco2e) : '—'}</dd>
        </div>
        <div>
          <dt>Projected (net)</dt>
          <dd className="bcs-mono" data-testid="summary-projected">{summary ? tco2e(summary.projected_tco2e) : '—'}</dd>
        </div>
        <div>
          <dt>Verified (net)</dt>
          <dd className="bcs-mono" data-testid="summary-verified">{summary ? tco2e(summary.verified_tco2e) : '—'}</dd>
        </div>
      </dl>
    </Panel>
  )
}
