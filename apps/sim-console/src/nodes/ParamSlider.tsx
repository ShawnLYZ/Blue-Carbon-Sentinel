import { useEffect, useMemo, useRef, useState } from 'react'
import type { Point } from '../data/store'
import { applyNode, getState } from '../data/store'
import { debounce } from '../data/debounce'
import { paramMeta } from '../data/params'
import type { Behaviour, SimNode } from '../data/types'
import { Sparkline } from './Sparkline'

interface Props {
  node: SimNode
  param: string
  history: Point[] | undefined
  onError: (message: string) => void
}

/**
 * One reading: live value with unit, a 2-minute sparkline, and an override slider (POST /overrides,
 * debounced 150 ms) with a hold/drift toggle. "Release" removes the override.
 */
export function ParamSlider({ node, param, history, onError }: Props) {
  const meta = paramMeta(param)
  const live = node.readings[param]
  const override = node.overrides[param]
  const [draft, setDraft] = useState<number | null>(null)
  const [behaviour, setBehaviour] = useState<Behaviour>(override?.behaviour ?? 'hold')
  const sent = useRef<number | null>(null)
  const nodeId = node.node_id

  useEffect(() => {
    if (override) setBehaviour(override.behaviour)
  }, [override])

  const send = useMemo(
    () =>
      debounce((value: number, b: Behaviour) => {
        const client = getState().client
        if (!client) return
        sent.current = value
        client.setOverride(nodeId, { parameter: param, value, behaviour: b }).then(
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
    [nodeId, param, onError],
  )
  useEffect(() => () => send.cancel(), [send])

  const release = () => {
    send.cancel()
    setDraft(null)
    getState()
      .client?.clearOverride(nodeId, param)
      .then(applyNode, (e: Error) => onError(e.message))
  }

  const toggleBehaviour = () => {
    const next: Behaviour = behaviour === 'hold' ? 'drift' : 'hold'
    setBehaviour(next)
    if (override) send(draft ?? override.value, next)
  }

  const shown = draft ?? override?.value ?? live ?? meta.min
  const clamped = Math.min(meta.max, Math.max(meta.min, shown))

  return (
    <div className={`param${override ? ' param--override' : ''}`} data-testid={`param-${param}`}>
      <div className="param__head">
        <span className="param__label">{meta.label}</span>
        <span className="param__value">
          <span className="bcs-mono" data-testid={`val-${param}`}>
            {Number.isFinite(live) ? live.toFixed(meta.dp) : '—'}
          </span>
          {meta.unit && <span className="param__unit">{meta.unit}</span>}
        </span>
        <Sparkline points={history} />
      </div>
      <div className="param__ctl">
        <input
          type="range"
          className="param__range"
          aria-label={`${meta.label} override`}
          min={meta.min}
          max={meta.max}
          step={meta.step}
          value={clamped}
          onChange={(e) => {
            const v = Number(e.target.value)
            setDraft(v)
            send(v, behaviour)
          }}
        />
        <button
          type="button"
          className="mini-btn"
          data-on={behaviour === 'drift'}
          aria-label={`${meta.label} behaviour: ${behaviour}`}
          title="Hold keeps the value; drift lets nature move it from there"
          onClick={toggleBehaviour}
        >
          {behaviour}
        </button>
        <button
          type="button"
          className="mini-btn"
          aria-label={`Release ${meta.label}`}
          title="Remove the override"
          disabled={!override}
          onClick={release}
        >
          ×
        </button>
      </div>
    </div>
  )
}
