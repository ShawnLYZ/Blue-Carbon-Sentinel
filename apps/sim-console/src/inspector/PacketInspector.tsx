import { useMemo, useState } from 'react'
import { SimulatedBadge, formatMYT } from '@bcs/ui'
import { useConsole, type PacketRow } from '../data/store'

const SHOWN = 200
type Validity = 'all' | 'valid' | 'invalid'

export function isReplay(p: PacketRow): boolean {
  return typeof p.payload === 'object' && p.payload !== null && (p.payload as { replay?: unknown }).replay === true
}

export interface PacketFilter {
  node: string
  channel: string
  direction: string
  validity: Validity
}

export function filterPackets(packets: PacketRow[], f: PacketFilter): PacketRow[] {
  return packets.filter(
    (p) =>
      (f.node === 'all' || p.node_id === f.node) &&
      (f.channel === 'all' || p.channel === f.channel) &&
      (f.direction === 'all' || p.direction === f.direction) &&
      (f.validity === 'all' || (f.validity === 'valid') === p.valid),
  )
}

function json(v: unknown): string {
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

/** Bottom drawer: every packet the simulated nodes send and receive, validated like the Ground Station. */
export function PacketInspector() {
  const live = useConsole((s) => s.packets)
  const dropped = useConsole((s) => s.dropped)
  const nodes = useConsole((s) => s.nodes)
  const [frozen, setFrozen] = useState<PacketRow[] | null>(null)
  const [filter, setFilter] = useState<PacketFilter>({ node: 'all', channel: 'all', direction: 'all', validity: 'all' })
  const [selected, setSelected] = useState<number | null>(null)
  const [open, setOpen] = useState(true)
  const packets = frozen ?? live
  const channels = useMemo(() => [...new Set(live.map((p) => p.channel))].sort(), [live])
  const shown = useMemo(() => filterPackets(packets, filter).slice(0, SHOWN), [packets, filter])
  const pick = shown.find((p) => p.seq === selected) ?? null
  const set = (patch: Partial<PacketFilter>) => setFilter((f) => ({ ...f, ...patch }))
  const fresh = frozen ? live.findIndex((p) => p.seq === frozen[0]?.seq) : 0

  return (
    <div className={`inspector${open ? '' : ' inspector--closed'}`}>
      <div className="inspector__bar">
        <button type="button" className="mini-btn" aria-expanded={open} aria-label={open ? 'Collapse inspector' : 'Expand inspector'}
          onClick={() => setOpen((o) => !o)}>
          {open ? '▾' : '▸'}
        </button>
        <span className="inspector__title">Packet inspector</span>
        <SimulatedBadge />
        <select className="mini-select" aria-label="Filter by node" value={filter.node} onChange={(e) => set({ node: e.target.value })}>
          <option value="all">All nodes</option>
          {nodes.map((n) => (
            <option key={n.node_id} value={n.node_id}>{n.node_id}</option>
          ))}
        </select>
        <select className="mini-select" aria-label="Filter by channel" value={filter.channel} onChange={(e) => set({ channel: e.target.value })}>
          <option value="all">All channels</option>
          {channels.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select className="mini-select" aria-label="Filter by direction" value={filter.direction} onChange={(e) => set({ direction: e.target.value })}>
          <option value="all">Both directions</option>
          <option value="up">↑ up (node → GS)</option>
          <option value="down">↓ down (GS → node)</option>
        </select>
        <div className="seg" role="group" aria-label="Validity">
          {(['all', 'valid', 'invalid'] as const).map((v) => (
            <button key={v} type="button" className="seg__btn" aria-pressed={filter.validity === v}
              data-testid={`inspector-filter-${v}`} onClick={() => set({ validity: v })}>
              {v}
            </button>
          ))}
        </div>
        <button type="button" className={`mini-btn${frozen ? ' mini-btn--on' : ''}`} onClick={() => setFrozen(frozen ? null : live)}>
          {frozen ? `Resume${fresh > 0 ? ` (${fresh} new)` : ''}` : 'Pause'}
        </button>
        <span className="inspector__count bcs-mono">
          {shown.length}/{packets.length}
          {dropped > 0 && <span className="inspector__dropped"> · {dropped} dropped</span>}
        </span>
      </div>
      {open && (
        <div className="inspector__body">
          <div className="inspector__list" role="list">
            {shown.length === 0 && <div className="hint inspector__empty">No packets match.</div>}
            {shown.map((p) => (
              <div
                key={p.seq}
                role="listitem"
                data-testid="packet-row"
                className={`packet${p.valid ? '' : ' packet--invalid'}${selected === p.seq ? ' packet--sel' : ''}`}
                onClick={() => setSelected(p.seq)}
              >
                <span className="packet__t bcs-mono">{formatMYT(p.at, { seconds: true })}</span>
                <span className={`packet__dir packet__dir--${p.direction}`}>{p.direction === 'up' ? '↑' : '↓'}</span>
                <span className="packet__node bcs-mono">{p.node_id}</span>
                <span className="packet__ch">{p.channel}</span>
                {isReplay(p) && <span className="packet__tag">REPLAY · SIMULATED</span>}
                <span className={`packet__valid${p.valid ? '' : ' packet__valid--bad'}`}>{p.valid ? 'valid' : 'INVALID'}</span>
                {!p.valid && <span className="packet__err">{p.errors.join('; ')}</span>}
              </div>
            ))}
          </div>
          <div className="inspector__json" data-testid="packet-json">
            {pick ? (
              <>
                <div className="inspector__jsonhead">
                  <span className="bcs-mono">{pick.topic}</span>
                  <span className="packet__tag">{isReplay(pick) ? 'REPLAY · SIMULATED' : 'SIMULATED'}</span>
                </div>
                {!pick.valid && (
                  <ul className="inspector__errors">
                    {pick.errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                )}
                <pre className="bcs-mono">{json(pick.payload)}</pre>
              </>
            ) : (
              <div className="hint">Select a packet to see its JSON.</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
