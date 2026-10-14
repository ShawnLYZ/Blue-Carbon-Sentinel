import { useState } from 'react'
import { Button, Panel, SimulatedBadge, formatMYTDateTime } from '@bcs/ui'
import type { LedgerRecord } from '@bcs/api-types'
import { DISCLAIMER, tco2e } from './format'

interface Evidence {
  captures?: { id: string; role: string; taken_at: string }[]
  telemetry_window?: Record<string, unknown>
}

function asEvidence(content: unknown): Evidence {
  const e = (content as { evidence?: unknown } | null)?.evidence
  return e && typeof e === 'object' ? (e as Evidence) : {}
}

/** Saves the PDF the Ground Station builds for the record (BC-yyyy-nnnnn.pdf). */
async function downloadPack(recordId: string): Promise<void> {
  const res = await fetch(`/api/v1/ledger/records/${encodeURIComponent(recordId)}/evidence-pack`)
  if (!res.ok) throw new Error(`The evidence pack could not be built (${res.status}).`)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = `${recordId}.pdf`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export function RecordDetail({ record, zoneLabel }: { record: LedgerRecord | null; zoneLabel: (id: string) => string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!record)
    return (
      <Panel title="Record detail">
        <p className="hint">Select a record to see its content, hashes and evidence.</p>
      </Panel>
    )
  const c = (record.content ?? {}) as Record<string, unknown>
  const evidence = asEvidence(record.content)
  const zones = Array.isArray(c.zone_ids) ? (c.zone_ids as string[]) : []
  const ded = c.deductions as Record<string, string> | undefined
  const conf = c.confidence as { overall?: string } | undefined
  const pack = async () => {
    setBusy(true)
    setError(null)
    try {
      await downloadPack(record.record_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The evidence pack could not be downloaded.')
    }
    setBusy(false)
  }
  return (
    <Panel
      title={`Record ${record.record_id}`}
      actions={
        <Button onClick={pack} disabled={busy}>
          Download evidence pack
        </Button>
      }
    >
      <div data-testid="record-detail" data-record-id={record.record_id}>
        <p className="hint">{DISCLAIMER}</p>
        <dl className="ledger-kv">
          <dt>Type</dt>
          <dd>{record.type === 'projected' ? 'Projected' : 'Verified'}</dd>
          <dt>Quantity (net)</dt>
          <dd className="bcs-mono">{tco2e(record.quantity_tco2e)}</dd>
          <dt>Time</dt>
          <dd className="bcs-mono">{formatMYTDateTime(record.created_at, { seconds: true })}</dd>
          {zones.length > 0 && (
            <>
              <dt>Zones</dt>
              <dd>{zones.map(zoneLabel).join(', ')}</dd>
            </>
          )}
          {typeof c.gross_tco2e === 'string' && (
            <>
              <dt>Gross</dt>
              <dd className="bcs-mono">{tco2e(c.gross_tco2e)}</dd>
            </>
          )}
          {ded && (
            <>
              <dt>Buffer</dt>
              <dd className="bcs-mono">
                {ded.buffer_pct} % · {tco2e(ded.buffer_tco2e)}
              </dd>
              <dt>Uncertainty</dt>
              <dd className="bcs-mono">{tco2e(ded.uncertainty_tco2e)}</dd>
            </>
          )}
          {conf?.overall && (
            <>
              <dt>Confidence</dt>
              <dd className="bcs-mono">{conf.overall}</dd>
            </>
          )}
          {typeof c.method_note === 'string' && (
            <>
              <dt>Methodology</dt>
              <dd data-testid="record-method-note">{c.method_note}</dd>
            </>
          )}
        </dl>
        <h4 className="ledger-h">Evidence</h4>
        <ul className="ledger-links" data-testid="evidence-links">
          {(evidence.captures ?? []).map((cap) => (
            <li key={`${cap.role}:${cap.id}`}>
              <a href="#/satellite" data-testid="evidence-capture-link" title="Open Satellite Intelligence to compare captures">
                Capture ({cap.role}) {formatMYTDateTime(cap.taken_at)}
              </a>
            </li>
          ))}
          {evidence.telemetry_window && (
            <li>
              <a href="#/network" data-testid="evidence-telemetry-link" title="Open Sentinel Network">
                Sensor telemetry window
              </a>{' '}
              <SimulatedBadge />
            </li>
          )}
        </ul>
        <h4 className="ledger-h">Hashes</h4>
        <dl className="ledger-kv ledger-kv--hash">
          <dt>Hash</dt>
          <dd className="bcs-mono" data-testid="record-hash">{record.hash}</dd>
          <dt>Previous</dt>
          <dd className="bcs-mono" data-testid="record-prev-hash">{record.previous_hash}</dd>
        </dl>
        <details className="ledger-canonical">
          <summary>Canonical JSON</summary>
          <pre className="bcs-mono" data-testid="record-canonical">{record.canonical}</pre>
        </details>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Panel>
  )
}
