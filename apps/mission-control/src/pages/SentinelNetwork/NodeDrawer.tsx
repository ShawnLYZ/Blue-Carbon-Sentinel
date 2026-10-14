import { useEffect, useMemo, useState } from 'react'
import { Button, Panel, SimulatedBadge, formatMYT } from '@bcs/ui'
import type { Node, NodeDetail, TelemetryPoint } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { useAppStore, type LivePoint } from '../../data/store'
import { TYPE_LABEL, TYPE_PARAMS, fmtNum, paramMeta, sourceText } from '../../data/network'

/** Debounce for refetching the drawer after the node's events (investigation mode samples every 2 s). */
export const DRAWER_SETTLE_MS = 600
const PACKETS_SHOWN = 12
const EVENTS_SHOWN = 12

function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    if (Object.is(value, settled)) return
    const t = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(t)
  }, [value, settled, ms])
  return settled
}

/** GET /nodes/{id}, refetched (debounced) whenever the node's live events move its store revision. */
export function useNodeDetail(id: string): { detail: NodeDetail | null; error: string | null } {
  const rev = useSettled(useAppStore((s) => s.nodes.rev[id] ?? 0), DRAWER_SETTLE_MS)
  const taskCount = useAppStore((s) => s.tasks.items.length)
  const [detail, setDetail] = useState<NodeDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setDetail(null), [id])
  useEffect(() => {
    let alive = true
    api.GET('/api/v1/nodes/{node_id}', { params: { path: { node_id: id } } }).then(
      (r) => {
        if (!alive) return
        if (r.data) {
          setDetail(r.data)
          setError(null)
        } else setError(apiErrorText(r.error, 'Could not load the node.'))
      },
      (e: unknown) => alive && setError(networkErrorText(e)),
    )
    return () => {
      alive = false
    }
  }, [id, rev, taskCount])
  return { detail, error }
}

const NO_POINTS: LivePoint[] = []

/**
 * The packet view: the stored recent samples (oldest first from GET /nodes/{id}) merged with the live
 * buffer, newest first. Only the live events carry `replay`, so a replayed sample is known from there.
 */
export function packetRows(stored: TelemetryPoint[], live: LivePoint[], limit: number): LivePoint[] {
  const byT = new Map<string, LivePoint>()
  for (const p of stored) byT.set(p.t, p)
  for (const p of live) byT.set(p.t, { ...byT.get(p.t), ...p })
  return [...byT.values()].sort((a, b) => (a.t < b.t ? 1 : a.t > b.t ? -1 : 0)).slice(0, limit)
}

function readingsText(readings: Record<string, number>): string {
  return Object.entries(readings)
    .map(([k, v]) => {
      const m = paramMeta(k)
      return `${m.label} ${v.toFixed(m.dp)}${m.unit ? ` ${m.unit}` : ''}`
    })
    .join(' · ')
}

/** The selected node: identity, latest readings, recent packets, edge flags and tasks (design §26). */
export function NodeDrawer({ node, zoneLabel, onClose }: { node: Node; zoneLabel: (id: string) => string; onClose: () => void }) {
  const { detail, error } = useNodeDetail(node.id)
  const src = sourceText(node.source)
  const latest = node.latest
  const live = useAppStore((s) => s.nodes.telemetry[node.id] ?? NO_POINTS)
  const packets = useMemo(() => packetRows(detail?.recent_telemetry ?? [], live, PACKETS_SHOWN), [detail, live])
  const covers = [...(node.covers.water ?? []), ...(node.covers.soil ?? [])]
  const flagEvents = (detail?.recent_events ?? []).slice(0, EVENTS_SHOWN)

  return (
    <Panel
      title={`${node.id} · ${TYPE_LABEL[node.node_type]}`}
      className="node-drawer"
      actions={
        <span className="node-drawer__actions">
          {node.source === 'simulated' ? <SimulatedBadge /> : <span className="bcs-chip">{src}</span>}
          <Button className="panel-action" onClick={onClose} aria-label="Close node drawer">
            Close
          </Button>
        </span>
      }
    >
      <div data-testid="node-drawer" data-node-id={node.id}>
        <dl className="kv-list">
          <dt>Status</dt>
          <dd>
            {node.status}
            {node.status === 'online' && node.mode ? ` · ${node.mode}` : ''}
            {node.interval_s ? ` · every ${node.interval_s} s` : ''}
          </dd>
          <dt>Zone</dt>
          <dd>{zoneLabel(node.zone_id)}</dd>
          <dt>Position</dt>
          <dd className="bcs-mono">
            e {node.position.e_m.toFixed(1)} m, s {node.position.s_m.toFixed(1)} m
          </dd>
          <dt>Covers</dt>
          <dd>{node.node_type === 'tide_gauge' ? 'whole site (water level)' : covers.length ? covers.map(zoneLabel).join(', ') : '—'}</dd>
          <dt>Firmware</dt>
          <dd className="bcs-mono">{node.fw_version ?? '—'}</dd>
          <dt>Battery / RSSI</dt>
          <dd className="bcs-mono">
            {fmtNum(latest?.health.battery_pct, 0, '%')} / {fmtNum(latest?.health.rssi_dbm, 0, 'dBm')}
          </dd>
        </dl>

        <h4 className="drawer-heading">Latest readings</h4>
        <dl className="kv-list">
          {TYPE_PARAMS[node.node_type].map((p) => {
            const m = paramMeta(p)
            return (
              <div key={p} style={{ display: 'contents' }}>
                <dt>{m.label}</dt>
                <dd className="bcs-mono" data-testid={`latest-${p}`}>
                  {fmtNum(latest?.readings[p], m.dp, m.unit)}
                </dd>
              </div>
            )
          })}
        </dl>

        <h4 className="drawer-heading">
          Recent packets <SimulatedBadge />
        </h4>
        <ul className="packet-list" data-testid="packet-view">
          {packets.map((p) => (
            <li key={p.t} className="packet-list__item" data-late={p.late} data-replay={p.replay === true}>
              <span className="bcs-mono">{formatMYT(p.t, { seconds: true })}</span>
              <span className="packet-list__src">{p.replay ? `REPLAY · ${src}` : src}</span>
              <span>{p.mode}{p.late ? ' · late' : ''}</span>
              <span className="packet-list__readings">{readingsText(p.readings)}</span>
            </li>
          ))}
          {detail && packets.length === 0 && <li className="hint">No packets yet.</li>}
          {!detail && !error && <li className="hint">Loading…</li>}
        </ul>

        <h4 className="drawer-heading">Edge flags and events</h4>
        {latest && latest.flags.length > 0 && (
          <p className="hint">
            Latest sample:{' '}
            {latest.flags.map((f) => `${f.kind} on ${paramMeta(f.parameter).label} (score ${f.score.toFixed(2)})`).join('; ')}
          </p>
        )}
        <ul className="packet-list">
          {flagEvents.map((ev) => (
            <li key={ev.id} className="packet-list__item">
              <span className="bcs-mono">{formatMYT(ev.at, { seconds: true })}</span>
              <span className="packet-list__src">{ev.origin === 'node' ? src : 'GROUND STATION'}</span>
              <span>{ev.kind.replaceAll('_', ' ')}</span>
              <span className="packet-list__readings">
                {ev.parameter ? paramMeta(ev.parameter).label : ''}
                {ev.value !== null && ev.value !== undefined ? ` = ${ev.value}` : ''}
                {ev.score !== null && ev.score !== undefined ? ` (score ${ev.score.toFixed(2)})` : ''}
              </span>
            </li>
          ))}
          {detail && flagEvents.length === 0 && <li className="hint">No edge flags or events.</li>}
        </ul>

        <h4 className="drawer-heading">Tasks</h4>
        <ul className="packet-list">
          {(detail?.tasks ?? []).map((t) => {
            const cmd = t.commands.find((c) => c.node_id === node.id)
            return (
              <li key={t.id} className="packet-list__item">
                <span className="bcs-mono">{formatMYT(t.created_at)}</span>
                <span>{t.status}</span>
                <span>{t.zone_id ? zoneLabel(t.zone_id) : '—'}</span>
                <span className="packet-list__readings">
                  {t.trigger}
                  {cmd ? ` · ack ${cmd.ack_status.replaceAll('_', ' ')}` : ''}
                </span>
              </li>
            )
          })}
          {detail && detail.tasks.length === 0 && <li className="hint">No tasks yet.</li>}
        </ul>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Panel>
  )
}
