import { useEffect, useMemo, useState } from 'react'
import { Panel, SourceChip } from '@bcs/ui'
import type { History } from '@bcs/api-types'
import { api } from '../../data/client'
import { useSettledRev } from '../../data/hooks'
import { useAppStore } from '../../data/store'
import { LazyEChart } from '../../lib/LazyEChart'
import { BASELINE_LABEL, historyOption, historyPoints } from './historyOption'
import { useZoneLabels } from './shared'

/** The history for the chart; refetched on `history.updated`. `null` until generated. */
function useHistory(): { history: History | null; error: string | null } {
  const rev = useSettledRev('history')
  const [history, setHistory] = useState<History | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    api.GET('/api/v1/history').then(
      (r) => {
        if (!live) return
        if (r.data) {
          setHistory(r.data)
          setError(null)
        } else if (r.response.status === 404) setHistory(null)
        else setError('Could not load the history.')
      },
      () => {
        if (live) setError('Could not load the history.')
      },
    )
    return () => {
      live = false
    }
  }, [rev])
  return { history, error }
}

/** Canopy cover 2016-2035: the labelled, dashed AI baseline and the real capture points (2026 on), solid. */
export function HistoryChart() {
  const { history, error } = useHistory()
  const zoneId = useAppStore((s) => s.ui.selectedZoneId)
  const zoneLabel = useZoneLabels()
  const hasZone = !!zoneId && !!history?.series[zoneId]
  const option = useMemo(
    () => (history ? historyOption(historyPoints(history, hasZone ? zoneId : null)) : null),
    [history, zoneId, hasZone],
  )
  const empty = !history || Object.keys(history.series).length === 0
  return (
    <Panel
      title="Canopy history"
      actions={history?.source ? <SourceChip tier={history.source.tier} model={history.source.model} cached={history.source.cached} /> : undefined}
    >
      <div data-testid="history-chart" data-baseline-style="dashed" data-y-axis={option?.yAxis.name} data-scope={hasZone ? zoneId : 'site'}>
        {empty || !option ? (
          <p className="hint">{error ?? 'The AI baseline appears after the first baseline capture.'}</p>
        ) : (
          <>
            <LazyEChart option={option} height={240} />
            <p className="hint history-label">
              {history.label || BASELINE_LABEL} (dashed). Solid points are real captures. Showing{' '}
              {hasZone && zoneId ? zoneLabel(zoneId) : 'the mean of all zones'}.
            </p>
          </>
        )}
      </div>
    </Panel>
  )
}
