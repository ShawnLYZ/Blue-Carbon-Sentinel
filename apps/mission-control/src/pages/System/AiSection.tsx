import { useEffect, useState } from 'react'
import { Panel, SourceChip, formatMYTDateTime } from '@bcs/ui'
import type { AIStatus } from '@bcs/api-types'
import { api } from '../../data/client'
import { useSettledRev } from '../../data/hooks'
import { keyStateText } from './aiStatusView'

const REFRESH_MS = 10_000

export function useAiStatus(): { status: AIStatus | null; error: string | null } {
  const rev = useSettledRev('ai')
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS)
    return () => clearInterval(id)
  }, [])
  useEffect(() => {
    let live = true
    api.GET('/api/v1/ai/status').then(
      (r) => {
        if (!live) return
        if (r.data) {
          setStatus(r.data)
          setError(null)
        } else setError('Could not load the AI status.')
      },
      () => {
        if (live) setError('Could not load the AI status.')
      },
    )
    return () => {
      live = false
    }
  }, [rev, tick])
  return { status, error }
}

/** Read-only AI status (spec 17): tier per role, key health by slot and model, daily counts, local model. No controls. */
export function AiSection() {
  const { status, error } = useAiStatus()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const daily = status ? Object.entries(status.daily) : []
  return (
    <Panel title="AI">
      <div data-testid="ai-section">
        {!status ? (
          <p className="hint">{error ?? 'Loading the AI status…'}</p>
        ) : (
          <>
            <table className="ai-table" data-testid="ai-roles">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Last tier</th>
                  <th>Last answer</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(status.roles).map(([role, r]) => (
                  <tr key={role} data-testid={`ai-role-${role}`} data-degraded={r.degraded}>
                    <td className="bcs-mono">{role}</td>
                    <td>{r.last_tier ? <SourceChip tier={r.last_tier} /> : <span className="hint">not called yet</span>}</td>
                    <td className="hint">
                      {r.last_at ? `${r.last_status ?? ''} ${formatMYTDateTime(r.last_at, { seconds: true })}` : ''}
                      {r.degraded ? ' · degraded' : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 className="ai-sub">Gemini keys (slot numbers only)</h3>
            <div data-testid="ai-keys">
              {status.keys.length === 0 ? (
                <p className="hint">No Gemini keys are configured; the local model and rules answer.</p>
              ) : (
                <table className="ai-table">
                  <thead>
                    <tr>
                      <th>Slot</th>
                      <th>Model</th>
                      <th>State</th>
                      <th>Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.keys.map((k) => (
                      <tr key={`${k.slot}-${k.model}`} data-testid="ai-key-row" data-state={k.state}>
                        <td className="bcs-mono">{k.slot}</td>
                        <td className="bcs-mono">{k.model}</td>
                        <td>{keyStateText(k.state, k.cooldown_until, now)}</td>
                        <td className="bcs-mono">{k.tokens}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <h3 className="ai-sub">Today</h3>
            <div data-testid="ai-daily">
              {daily.length === 0 ? (
                <p className="hint">No AI calls today.</p>
              ) : (
                <dl className="kv-list">
                  {daily.map(([k, v]) => (
                    <div key={k} className="kv-list__row">
                      <dt>{k}</dt>
                      <dd className="bcs-mono">{v}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
            <h3 className="ai-sub">Local model</h3>
            <p data-testid="ai-ollama" className="hint">
              {status.ollama.model ?? 'none configured'} · {status.ollama.reachable ? 'reachable' : 'not reachable'} ·{' '}
              {status.ollama.vision ? 'vision enabled' : 'vision off (text only)'}
            </p>
          </>
        )}
      </div>
    </Panel>
  )
}
