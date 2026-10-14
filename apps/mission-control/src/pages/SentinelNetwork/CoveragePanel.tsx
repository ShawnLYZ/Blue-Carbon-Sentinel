import { useState } from 'react'
import { Button, Chip, Modal, Panel, formatMYTDateTime } from '@bcs/ui'
import type { CommissioningRun, Coverage } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { useAppStore } from '../../data/store'
import { METHOD_TEXT, RECOMMISSION_TEXT, TYPE_LABEL } from '../../data/network'

/** "Re-commission" with its confirmation dialog; the run result goes to the store. */
export function RecommissionButton() {
  const setCommissioning = useAppStore((s) => s.setCommissioning)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.POST('/api/v1/commissioning', { body: { confirm: true } })
      if (r.data) {
        setCommissioning(r.data)
        setOpen(false)
      } else setError(apiErrorText(r.error, 'Commissioning failed.'))
    } catch (e) {
      setError(networkErrorText(e))
    }
    setBusy(false)
  }

  return (
    <>
      <Button variant="danger" onClick={() => (setError(null), setOpen(true))} disabled={busy}>
        Re-commission
      </Button>
      <Modal open={open} title="Re-commission the network?" onClose={() => !busy && setOpen(false)}>
        <p className="page__blurb">{RECOMMISSION_TEXT}</p>
        <div className="row-actions">
          <Button onClick={() => setOpen(false)} disabled={busy}>
            Keep current positions
          </Button>
          <Button variant="danger" onClick={run} disabled={busy}>
            {busy ? 'Commissioning…' : 'Re-commission now'}
          </Button>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Modal>
    </>
  )
}

/** Method, confidence, reasons and time of a commissioning run, as a key-value list. */
export function CommissioningSummary({ run, coverage }: { run: CommissioningRun | null; coverage: Coverage | null }) {
  const covered = coverage ? coverage.zones.filter((z) => z.covered).length : null
  return (
    <dl className="kv-list" data-testid="commissioning-status">
      <dt>Method</dt>
      <dd>{run ? (METHOD_TEXT[run.method] ?? run.method) : 'not commissioned yet'}</dd>
      <dt>Confidence</dt>
      <dd>
        {run ? (
          <span className={`badge badge--confidence-${run.confidence}`} data-testid="commissioning-confidence">
            {run.confidence}
          </span>
        ) : (
          '—'
        )}
      </dd>
      <dt>Run at</dt>
      <dd className="bcs-mono">{run ? formatMYTDateTime(run.created_at, { seconds: true }) : '—'}</dd>
      <dt>Placed</dt>
      <dd>{run ? `${run.positions.length} nodes${run.capture_id ? ' from the latest capture' : ' without a capture'}` : '—'}</dd>
      <dt>Coverage</dt>
      <dd>{covered === null ? '—' : `${covered} / ${coverage!.zones.length} zones covered by a WQ or SP node`}</dd>
      {run && run.reasons.length > 0 && (
        <>
          <dt>Reasons</dt>
          <dd>
            <ul className="reasons">
              {run.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </dd>
        </>
      )}
    </dl>
  )
}

/** Commissioning status with Re-commission, plus the coverage-gap suggestions (design §15, §26). */
export function CoveragePanel({ zoneLabel }: { zoneLabel: (id: string) => string }) {
  const run = useAppStore((s) => s.coverage.commissioning)
  const coverage = useAppStore((s) => s.coverage.coverage)
  const gaps = coverage?.gaps ?? []
  return (
    <Panel title="Coverage and commissioning" actions={run ? <Chip>{run.confidence} confidence</Chip> : undefined}>
      <CommissioningSummary run={run} coverage={coverage} />
      <div className="row-actions">
        <RecommissionButton />
      </div>
      <h4 className="drawer-heading">Gap suggestions</h4>
      {gaps.length === 0 ? (
        <p className="hint">No flagged or high-risk zone is without WQ/SP coverage.</p>
      ) : (
        <ul className="gap-list">
          {gaps.map((g) => (
            <li key={g.id} data-testid="gap-suggestion" className="gap-list__item">
              <strong>{zoneLabel(g.zone_id)}</strong>: add a {TYPE_LABEL[g.node_type].toLowerCase()} at e {g.e_m.toFixed(0)} m, s{' '}
              {g.s_m.toFixed(0)} m
              {g.newly_covered.length > 0 && <> — newly covers {g.newly_covered.map(zoneLabel).join(', ')}</>}
              <span className="hint"> ({g.reason})</span>
            </li>
          ))}
        </ul>
      )}
      {gaps.length > 0 && <p className="hint">Install a simulated node at a suggestion from the Simulator Console.</p>}
    </Panel>
  )
}
