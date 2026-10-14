import { Panel } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { CommissioningSummary, RecommissionButton } from '../SentinelNetwork/CoveragePanel'

/** The latest commissioning run and "Re-commission" (design §26 System). */
export function CommissioningSection() {
  const run = useAppStore((s) => s.coverage.commissioning)
  const coverage = useAppStore((s) => s.coverage.coverage)
  return (
    <Panel title="Commissioning">
      <CommissioningSummary run={run} coverage={coverage} />
      <p className="hint">
        Commissioning places every node from the latest capture&apos;s class map, or spreads them evenly when no usable capture
        exists (low confidence).
      </p>
      <div className="row-actions">
        <RecommissionButton />
      </div>
    </Panel>
  )
}
