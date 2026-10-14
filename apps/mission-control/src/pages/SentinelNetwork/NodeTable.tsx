import { SimulatedBadge, StatusDot, formatMYT, type DotStatus } from '@bcs/ui'
import type { Node } from '@bcs/api-types'
import { TYPE_COLOUR, TYPE_LABEL, TYPE_SHORT, fmtNum, sourceText } from '../../data/network'

const STATUS_DOT: Record<Node['status'], DotStatus> = { online: 'ok', offline: 'fail', unknown: 'off', decommissioned: 'off' }

/**
 * Every node: type, ID, zone, mode, battery, RSSI, last seen (MYT) and its source badge (design §26).
 * Battery, RSSI and last seen update with each live sample. A row selects the node.
 */
export function NodeTable({
  nodes,
  selectedId,
  onSelect,
  zoneLabel,
}: {
  nodes: Node[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  zoneLabel: (id: string) => string
}) {
  if (nodes.length === 0) return <p className="page__blurb">No Sentinel Nodes are registered yet.</p>
  return (
    <div className="metrics-table__wrap">
      <table className="node-table">
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col">ID</th>
            <th scope="col">Zone</th>
            <th scope="col">Mode</th>
            <th scope="col">Battery</th>
            <th scope="col">RSSI</th>
            <th scope="col">Last seen</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((n) => {
            const h = n.latest?.health
            const selected = n.id === selectedId
            return (
              <tr
                key={n.id}
                data-testid="node-row"
                data-node-id={n.id}
                data-status={n.status}
                aria-selected={selected}
                className="node-table__row"
                onClick={() => onSelect(selected ? null : n.id)}
              >
                <td>
                  <span className="node-type" style={{ color: n.status === 'online' ? TYPE_COLOUR[n.node_type] : undefined }} title={TYPE_LABEL[n.node_type]}>
                    {TYPE_SHORT[n.node_type]}
                  </span>
                </td>
                <th scope="row">
                  <button type="button" className="link-button" aria-pressed={selected} onClick={(e) => (e.stopPropagation(), onSelect(selected ? null : n.id))}>
                    <StatusDot status={STATUS_DOT[n.status]} label={`${n.id} ${n.status}`} /> {n.id}
                  </button>
                </th>
                <td>{zoneLabel(n.zone_id)}</td>
                <td data-mode={n.mode ?? ''}>{n.status === 'online' ? (n.mode ?? '—') : n.status}</td>
                <td className="bcs-mono" data-testid="node-battery">{fmtNum(h?.battery_pct, 0, '%')}</td>
                <td className="bcs-mono">{fmtNum(h?.rssi_dbm, 0, 'dBm')}</td>
                <td className="bcs-mono" data-testid="node-last-seen">
                  {n.last_seen_at ? formatMYT(n.last_seen_at, { seconds: true }) : 'never'}
                </td>
                <td>{n.source === 'simulated' ? <SimulatedBadge /> : <span className="bcs-chip">{sourceText(n.source)}</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
