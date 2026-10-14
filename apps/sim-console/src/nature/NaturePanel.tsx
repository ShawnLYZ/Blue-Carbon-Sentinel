import { useEffect, useMemo, useState } from 'react'
import { Toggle } from '@bcs/ui'
import { debounce } from '../data/debounce'
import { getState, setState, useConsole } from '../data/store'
import type { NaturePatch } from '../data/types'

function send(patch: NaturePatch, onError: (m: string) => void) {
  const client = getState().client
  if (!client) return
  client.patchNature(patch).then(
    (res) =>
      setState((s) => ({
        state: s.state ? { ...s.state, nature: res.nature, fast_forward: res.fast_forward } : s.state,
      })),
    (e: Error) => onError(e.message),
  )
}

/** A slider whose value follows the server until it is moved; PATCH /nature 150 ms after the last change. */
function NatureSlider({
  label, unit, min, max, step, value, toPatch, onError, testId, disabled,
}: {
  label: string; unit: string; min: number; max: number; step: number; value: number | undefined
  toPatch: (v: number) => NaturePatch; onError: (m: string) => void; testId: string; disabled?: boolean
}) {
  const [draft, setDraft] = useState<number | null>(null)
  const push = useMemo(
    () =>
      debounce((v: number) => {
        send(toPatch(v), onError)
        setTimeout(() => setDraft(null), 600) // let the server value catch up before following it again
      }),
    [toPatch, onError],
  )
  useEffect(() => () => push.cancel(), [push])
  const shown = draft ?? value ?? min
  return (
    <label className="nature-slider">
      <span className="nature-slider__label">{label}</span>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={shown}
        disabled={disabled}
        onChange={(e) => {
          const v = Number(e.target.value)
          setDraft(v)
          push(v)
        }}
      />
      <span className="bcs-mono nature-slider__val" data-testid={testId}>
        {unit === '×' ? `×${shown}` : `${shown} ${unit}`}
      </span>
    </label>
  )
}

const meanPatch = (v: number): NaturePatch => ({ tide: { mean_cm: v } })
const ampPatch = (v: number): NaturePatch => ({ tide: { amplitude_cm: v } })
const ffPatch = (v: number): NaturePatch => ({ fast_forward: Math.max(1, v) })

/** Tides (mean, amplitude, spring-neap), diurnal cycles, noise and fast-forward (1–200). */
export function NaturePanel() {
  const nature = useConsole((s) => s.state?.nature)
  const ffState = useConsole((s) => s.state?.fast_forward)
  const ffLive = useConsole((s) => s.status?.fast_forward)
  const [error, setError] = useState<string | null>(null)
  const onError = useMemo(() => (m: string) => setError(m), [])
  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 5000)
    return () => clearTimeout(t)
  }, [error])
  const ff = ffLive ?? ffState
  // Before the runtime starts, /state answers nature: {} (no tide yet).
  const tide = nature?.tide
  const disabled = !tide

  return (
    <div className="nature">
      <div className="nature__toggles">
        <Toggle label="Tide" checked={tide?.enabled ?? false} disabled={disabled}
          onChange={(v) => send({ tide: { enabled: v } }, onError)} />
        <Toggle label="Spring-neap" checked={tide?.spring_neap ?? false} disabled={disabled}
          onChange={(v) => send({ tide: { spring_neap: v } }, onError)} />
        <Toggle label="Diurnal" checked={nature?.diurnal ?? false} disabled={disabled}
          onChange={(v) => send({ diurnal: v }, onError)} />
        <Toggle label="Noise" checked={nature?.noise ?? false} disabled={disabled}
          onChange={(v) => send({ noise: v }, onError)} />
      </div>
      <NatureSlider label="Tide mean" unit="cm" min={-200} max={200} step={5} value={tide?.mean_cm}
        toPatch={meanPatch} onError={onError} testId="tide-mean" disabled={disabled || !tide?.enabled} />
      <NatureSlider label="Tide amplitude" unit="cm" min={0} max={300} step={5} value={tide?.amplitude_cm}
        toPatch={ampPatch} onError={onError} testId="tide-amplitude" disabled={disabled || !tide?.enabled} />
      <NatureSlider label="Fast-forward" unit="×" min={1} max={200} step={1} value={ff}
        toPatch={ffPatch} onError={onError} testId="nature-fast-forward" disabled={disabled} />
      <p className="hint">Tide period 12.42 h. Fast-forward speeds up nature; timestamps stay real.</p>
      {error && <div className="banner banner--error" role="alert">{error}</div>}
    </div>
  )
}
