import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SimulatedBadge, StatusDot, Toggle, formatMYT } from '@bcs/ui'
import type { Point } from '../data/store'
import { applyNode, getState } from '../data/store'
import { debounce } from '../data/debounce'
import { FAULTS, PARAM_FAULTS, TYPE_LABEL, TYPE_SHORT, paramMeta } from '../data/params'
import type { HealthBody, SimNode } from '../data/types'
import { ParamSlider } from './ParamSlider'

const time = (iso: string) => formatMYT(iso, { seconds: true })

/** Battery or RSSI slider: shows the live value, sends POST /health 150 ms after the last change. */
function HealthSlider({
  label, unit, min, max, value, field, nodeId, onError, testId,
}: {
  label: string; unit: string; min: number; max: number; value: number
  field: keyof HealthBody; nodeId: string; onError: (m: string) => void; testId: string
}) {
  const [draft, setDraft] = useState<number | null>(null)
  const sent = useRef<number | null>(null)
  const send = useMemo(
    () =>
      debounce((v: number) => {
        sent.current = v
        getState()
          .client?.setHealth(nodeId, { [field]: v })
          .then(
            (n) => {
              applyNode(n)
              setDraft((d) => (d === sent.current ? null : d))
            },
            (e: Error) => {
              setDraft(null)
              onError(e.message)
            },
          )
      }),
    [nodeId, field, onError],
  )
  useEffect(() => () => send.cancel(), [send])
  const shown = draft ?? value
  return (
    <label className="health">
      <span className="health__label">{label}</span>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={1}
        value={Math.min(max, Math.max(min, Math.round(shown)))}
        onChange={(e) => {
          const v = Number(e.target.value)
          setDraft(v)
          send(v)
        }}
      />
      <span className="bcs-mono health__val" data-testid={testId}>
        {Number.isFinite(shown) ? Math.round(shown) : '—'} {unit}
      </span>
    </label>
  )
}

function FaultToggles({ node, onError }: { node: SimNode; onError: (m: string) => void }) {
  const params = Object.keys(node.readings)
  const [target, setTarget] = useState(params[0] ?? '')
  const [pending, setPending] = useState<Record<string, boolean>>({})
  const nodeId = node.node_id

  const set = (kind: string, on: boolean) => {
    const client = getState().client
    if (!client) return
    setPending((p) => ({ ...p, [kind]: on }))
    const params: Record<string, unknown> | undefined = PARAM_FAULTS.has(kind)
      ? { parameter: target }
      : kind === 'low_battery'
        ? { pct: 12 }
        : undefined
    const req = on ? client.injectFault(nodeId, { kind, params }) : client.clearFault(nodeId, kind)
    req.then(applyNode, (e: Error) => onError(e.message)).finally(() =>
      setPending((p) => {
        const rest = { ...p }
        delete rest[kind]
        return rest
      }),
    )
  }

  return (
    <div className="faults">
      <div className="faults__head">
        <span className="section-label">Faults</span>
        {params.length > 1 && (
          <select
            className="mini-select"
            aria-label="Parameter for stuck, spikes and drift"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            {params.map((p) => (
              <option key={p} value={p}>
                {paramMeta(p).label}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="faults__grid">
        {FAULTS.map((f) => (
          <Toggle
            key={f.kind}
            label={f.label}
            checked={pending[f.kind] ?? f.kind in node.faults}
            onChange={(on) => set(f.kind, on)}
          />
        ))}
      </div>
    </div>
  )
}

interface Props {
  node: SimNode
  history: Record<string, Point[]> | undefined
}

/** One simulated node: live values, override sliders, health, faults, mode and last command/ack. */
export const NodeCard = memo(function NodeCard({ node, history }: Props) {
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 5000)
    return () => clearTimeout(t)
  }, [error])
  const onError = useCallback((m: string) => setError(m), [])
  const short = TYPE_SHORT[node.node_type] ?? '?'
  const investigating = node.mode !== 'baseline'

  return (
    <article className="node-card" data-testid={`node-card-${node.node_id}`} data-type={short}>
      <header className="node-card__head">
        <span className={`type-icon type-icon--${short}`} title={TYPE_LABEL[node.node_type] ?? node.node_type}>
          {short}
        </span>
        <div className="node-card__id">
          <div className="node-card__name">{node.node_id}</div>
          <div className="node-card__sub">
            <StatusDot status={node.connected ? 'ok' : 'fail'} label={node.connected ? 'connected' : 'disconnected'} />
            <span>{TYPE_LABEL[node.node_type] ?? node.node_type} · {node.zone_label}</span>
            <span className={`mode-chip${investigating ? ' mode-chip--hot' : ''}`} data-testid="mode">
              {node.mode} · {node.interval_s}s
            </span>
          </div>
        </div>
        <SimulatedBadge />
      </header>

      <div className="node-card__params">
        {Object.keys(node.readings).map((p) => (
          <ParamSlider key={p} node={node} param={p} history={history?.[p]} onError={onError} />
        ))}
      </div>

      <div className="node-card__health">
        <HealthSlider label="Battery" unit="%" min={0} max={100} value={node.battery_pct} field="battery_pct"
          nodeId={node.node_id} onError={onError} testId="val-battery" />
        <HealthSlider label="RSSI" unit="dBm" min={-120} max={0} value={node.rssi_dbm} field="rssi_dbm"
          nodeId={node.node_id} onError={onError} testId="val-rssi" />
      </div>

      <FaultToggles node={node} onError={onError} />

      <footer className="node-card__cmd bcs-mono" data-testid="last-command">
        <span>
          cmd: {node.last_command ? `${node.last_command.type} · ${time(node.last_command.at)}` : '—'}
        </span>
        <span>ack: {node.last_ack ? `${node.last_ack.status} · ${time(node.last_ack.at)}` : '—'}</span>
      </footer>
      {error && (
        <div className="node-card__error" role="alert">
          {error}
        </div>
      )}
    </article>
  )
})
