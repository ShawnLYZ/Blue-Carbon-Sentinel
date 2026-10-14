import { useState } from 'react'
import { Button, Modal } from '@bcs/ui'
import { getState, refreshCoverage, refreshState, setState, useConsole } from '../data/store'
import { TYPE_LABEL, TYPE_SHORT } from '../data/params'
import type { SimPosition } from '../data/types'

type Confirm = { kind: 'move'; nodeId: string; to: SimPosition } | { kind: 'remove'; nodeId: string }
const INSTALL_TYPES = ['water_quality', 'soil_probe'] as const

const at = (p: SimPosition) => `(${p.e_m.toFixed(0)}, ${p.s_m.toFixed(0)}) m`

/** Install at a gap suggestion or a picked mini-map point; move and remove, each confirmed first. */
export function LifecyclePanel() {
  const nodes = useConsole((s) => s.nodes)
  const gaps = useConsole((s) => s.coverage?.gaps)
  const picked = useConsole((s) => s.picked)
  const suggestion = useConsole((s) => s.suggestion)
  const [nodeType, setNodeType] = useState<string>('water_quality')
  const [target, setTarget] = useState<string>('')
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const nodeId = target || nodes[0]?.node_id || ''

  const run = async (label: string, fn: () => Promise<unknown>, ok: (res: unknown) => string) => {
    setBusy(true)
    try {
      const res = await fn()
      setMessage({ ok: true, text: ok(res) })
      setState({ picked: null, suggestion: null })
    } catch (e) {
      setMessage({ ok: false, text: `${label} failed: ${(e as Error).message}` })
    } finally {
      setBusy(false)
      refreshCoverage()
      refreshState()
    }
  }
  const installedId = (res: unknown) => (res as { node?: { id?: string } })?.node?.id ?? 'node'

  const installSuggestion = (id: string) =>
    run('Install', () => getState().client!.install({ suggestion_id: id }), (r) => `Installed ${installedId(r)} (SIMULATED).`)
  const installAtPoint = () =>
    picked &&
    run('Install', () => getState().client!.install({ node_type: nodeType, position: picked }),
      (r) => `Installed ${installedId(r)} at ${at(picked)} (SIMULATED).`)

  const doConfirm = () => {
    const c = confirm
    setConfirm(null)
    if (!c) return
    if (c.kind === 'move')
      void run('Move', () => getState().client!.move(c.nodeId, { position: c.to, confirm: true }), () => `Moved ${c.nodeId} to ${at(c.to)}.`)
    else void run('Remove', () => getState().client!.remove(c.nodeId, { confirm: true }), () => `Removed ${c.nodeId}.`)
  }

  return (
    <div className="lifecycle">
      <section>
        <div className="section-label">Install</div>
        {(gaps ?? []).length === 0 ? (
          <p className="hint">No coverage-gap suggestions right now.</p>
        ) : (
          <ul className="gap-list">
            {(gaps ?? []).map((g) => (
              <li key={g.id} className={suggestion === g.id ? 'is-picked' : undefined}>
                <span>
                  <strong>{TYPE_SHORT[g.node_type]}</strong> for {g.zone_id.replace(/^KSL-/, '')} at {at(g)}
                  <span className="hint"> · {g.reason}</span>
                </span>
                <Button disabled={busy} onClick={() => void installSuggestion(g.id)}>
                  Install at suggestion
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="lifecycle__row">
          <select className="mini-select" aria-label="Node type to install" value={nodeType} onChange={(e) => setNodeType(e.target.value)}>
            {INSTALL_TYPES.map((t) => (
              <option key={t} value={t}>{TYPE_LABEL[t]}</option>
            ))}
          </select>
          <Button disabled={busy || !picked} onClick={() => void installAtPoint()}>
            Install at picked point
          </Button>
        </div>
        <p className="hint">{picked ? `Picked ${at(picked)}.` : 'Click the mini-map to pick a point.'}</p>
      </section>

      <section>
        <div className="section-label">Move or remove</div>
        <div className="lifecycle__row">
          <select className="mini-select" aria-label="Node to move or remove" value={nodeId} onChange={(e) => setTarget(e.target.value)}>
            {nodes.map((n) => (
              <option key={n.node_id} value={n.node_id}>{n.node_id}</option>
            ))}
          </select>
          <Button disabled={busy || !picked || !nodeId} onClick={() => picked && setConfirm({ kind: 'move', nodeId, to: picked })}>
            Move to picked point…
          </Button>
          <Button variant="danger" disabled={busy || !nodeId} onClick={() => setConfirm({ kind: 'remove', nodeId })}>
            Remove…
          </Button>
        </div>
      </section>

      {message && (
        <div className={`banner ${message.ok ? 'banner--ok' : 'banner--error'}`} role="status">
          {message.text}
        </div>
      )}

      <Modal open={confirm !== null} title={confirm?.kind === 'move' ? 'Move node' : 'Remove node'} onClose={() => setConfirm(null)}>
        {confirm && (
          <div className="confirm">
            <p>
              {confirm.kind === 'move'
                ? `Move ${confirm.nodeId} to ${at(confirm.to)}? Sensors are anchored; this records a physical relocation.`
                : `Remove ${confirm.nodeId}? It is decommissioned and its ID is never reused.`}
            </p>
            <div className="confirm__actions">
              <Button onClick={() => setConfirm(null)}>Cancel</Button>
              <Button variant={confirm.kind === 'remove' ? 'danger' : 'primary'} onClick={doConfirm}>
                {confirm.kind === 'move' ? 'Confirm move' : 'Confirm remove'}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
