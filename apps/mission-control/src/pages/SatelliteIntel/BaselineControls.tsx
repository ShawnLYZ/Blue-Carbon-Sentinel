import { useState } from 'react'
import { Button, formatMYTDateTime, Panel } from '@bcs/ui'
import type { CaptureSummary } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'

/** POST /baseline with no body: the Ground Station uses the latest evidence-grade capture. Resolves to an error text or null. */
export async function setBaselineNow(): Promise<string | null> {
  try {
    const r = await api.POST('/api/v1/baseline', { body: {} })
    return r.error ? apiErrorText(r.error, 'The baseline was not set.') : null
  } catch (e) {
    return networkErrorText(e)
  }
}

/** The current baseline and "Set baseline now" (US 48). */
export function BaselineControls({ captures }: { captures: CaptureSummary[] | null }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const baseline = captures?.find((c) => c.is_baseline) ?? null

  const run = async () => {
    setBusy(true)
    setError(null)
    setError(await setBaselineNow())
    setBusy(false)
  }

  return (
    <Panel title="Baseline">
      <div className="kv">
        <span>Current baseline</span>
        <span className="bcs-mono" data-testid="baseline-at">
          {baseline ? formatMYTDateTime(baseline.taken_at, { seconds: true }) : captures ? 'none in the recent captures' : '—'}
        </span>
      </div>
      <div className="row-actions">
        <Button variant="primary" onClick={run} disabled={busy}>
          {busy ? 'Setting…' : 'Set baseline now'}
        </Button>
        <span className="hint">Uses the latest evidence-grade capture.</span>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Panel>
  )
}
