import { useEffect, useState } from 'react'
import { Button } from '@bcs/ui'
import { getState, refreshState, useConsole } from '../data/store'
import type { ScenarioApplied } from '../data/types'
import { GRID, labelForCell } from './zonePicker'

/** The 7 presets (K1 catalogue IDs) and their button names. */
export const PRESETS: { id: string; label: string }[] = [
  { id: 'sediment_runoff', label: 'Sediment runoff' },
  { id: 'salt_intrusion', label: 'Salt intrusion' },
  { id: 'low_oxygen', label: 'Low oxygen' },
  { id: 'heat_stress', label: 'Heat stress' },
  { id: 'heavy_rain', label: 'Heavy rain' },
  { id: 'healthy', label: 'Healthy' },
  { id: 'recovery', label: 'Recovery' },
]
const LABEL = Object.fromEntries(PRESETS.map((p) => [p.id, p.label]))
export const DEFAULT_RAMP_S = 60

type Outcome = { kind: 'ok'; res: ScenarioApplied } | { kind: 'error'; message: string } | { kind: 'cleared'; zone: string }

/** 5 x 5 zone picker, the presets and the ramp time; the API's warning shows as a banner. */
export function ScenarioPanel() {
  const active = useConsole((s) => s.state?.zone_scenarios)
  const online = useConsole((s) => s.sim === 'online')
  const [zone, setZone] = useState<string | null>(null)
  const [ramp, setRamp] = useState(String(DEFAULT_RAMP_S))
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => setOutcome(null), [zone])

  const apply = async (scenario: string) => {
    const client = getState().client
    if (!client || !zone) return
    const r = Number(ramp)
    setBusy(true)
    try {
      const res = await client.applyScenario(zone, {
        scenario,
        ramp_s: ramp.trim() !== '' && Number.isFinite(r) && r >= 0 ? r : undefined,
      })
      setOutcome({ kind: 'ok', res })
    } catch (e) {
      setOutcome({ kind: 'error', message: (e as Error).message })
    } finally {
      setBusy(false)
      refreshState()
    }
  }

  const clear = async () => {
    const client = getState().client
    if (!client || !zone) return
    try {
      await client.clearScenario(zone)
      setOutcome({ kind: 'cleared', zone })
    } catch (e) {
      setOutcome({ kind: 'error', message: (e as Error).message })
    }
    refreshState()
  }

  return (
    <div className="scenarios">
      <div className="zone-picker" role="group" aria-label="Zone">
        {Array.from({ length: GRID * GRID }, (_, i) => {
          const label = labelForCell(i % GRID, Math.floor(i / GRID))
          const running = active?.[label]
          return (
            <button
              key={label}
              type="button"
              className="zone-cell"
              data-testid={`zone-${label}`}
              aria-pressed={zone === label}
              title={running ? `${LABEL[running.scenario] ?? running.scenario} running` : label}
              onClick={() => setZone(label)}
            >
              {label}
              {running && <span className="zone-cell__dot" aria-hidden="true" />}
            </button>
          )
        })}
      </div>

      <div className="scenarios__row">
        <span className="scenarios__zone">
          Zone: <strong className="bcs-mono">{zone ?? '—'}</strong>
          {zone && active?.[zone] && <em> · {LABEL[active[zone].scenario] ?? active[zone].scenario} running</em>}
        </span>
        <label className="ramp">
          Ramp time (s)
          <input
            type="number"
            min={0}
            max={3600}
            step={1}
            value={ramp}
            onChange={(e) => setRamp(e.target.value)}
          />
        </label>
      </div>

      <div className="presets">
        {PRESETS.map((p) => (
          <Button key={p.id} disabled={!zone || busy || !online} onClick={() => void apply(p.id)}>
            {p.label}
          </Button>
        ))}
        <Button variant="danger" disabled={!zone || !active?.[zone]} onClick={() => void clear()}>
          Clear zone
        </Button>
      </div>

      {!zone && <p className="hint">Pick a zone, then a preset.</p>}
      {outcome?.kind === 'ok' && outcome.res.warning && (
        <div className="banner banner--warn" role="alert" data-testid="scenario-warning">
          {outcome.res.warning}
        </div>
      )}
      {outcome?.kind === 'ok' && !outcome.res.warning && (
        <p className="hint" data-testid="scenario-result">
          {LABEL[outcome.res.scenario] ?? outcome.res.scenario} on {outcome.res.zone_label} (ramp {outcome.res.ramp_s} s)
          {outcome.res.nodes.length > 0 &&
            ` → ${outcome.res.nodes.map((n) => `${n.node_id} ×${n.factor.toFixed(2)}`).join(', ')}`}
        </p>
      )}
      {outcome?.kind === 'cleared' && <p className="hint">Cleared {outcome.zone}.</p>}
      {outcome?.kind === 'error' && (
        <div className="banner banner--error" role="alert">
          {outcome.message}
        </div>
      )}
    </div>
  )
}
