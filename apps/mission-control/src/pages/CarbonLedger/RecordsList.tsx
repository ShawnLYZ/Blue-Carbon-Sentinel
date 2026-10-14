import { Panel, formatMYTDateTime } from '@bcs/ui'
import type { LedgerRecord } from '@bcs/api-types'
import { tco2e } from './format'

function linkText(ok: boolean | null | undefined): string {
  return ok === null || ok === undefined ? '—' : ok ? '✓' : '✗'
}

/** The chain, newest first: index, ID, type, quantity, time (MYT) and the per-record link check. */
export function RecordsList({
  records,
  selectedId,
  onSelect,
}: {
  records: LedgerRecord[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <Panel title="Records">
      {records.length === 0 ? (
        <p className="hint">No records yet. Generate a Projected record from an applied plan.</p>
      ) : (
        <div className="metrics-table__wrap">
          <table className="node-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Record</th>
                <th scope="col">Type</th>
                <th scope="col">Quantity</th>
                <th scope="col">Time</th>
                <th scope="col">Link</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr
                  key={r.record_id}
                  data-testid="record-row"
                  data-record-id={r.record_id}
                  aria-selected={r.record_id === selectedId}
                  className="node-table__row"
                  onClick={() => onSelect(r.record_id)}
                >
                  <td className="bcs-mono">{r.chain_index}</td>
                  <th scope="row">{r.record_id}</th>
                  <td>
                    <span className={`ledger-badge ledger-badge--${r.type}`}>{r.type === 'projected' ? 'Projected' : 'Verified'}</span>
                  </td>
                  <td className="bcs-mono">{tco2e(r.quantity_tco2e)}</td>
                  <td className="bcs-mono">{formatMYTDateTime(r.created_at)}</td>
                  <td
                    className="bcs-mono"
                    data-testid="link-ok"
                    data-link-ok={String(r.link_ok ?? null)}
                    title={r.link_ok == null ? 'Not verified yet' : r.link_ok ? 'Hash link intact' : 'Hash link broken'}
                  >
                    {linkText(r.link_ok)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
