import { useEffect, useRef, useState } from 'react'
import type { DirectorState } from '@bcs/api-types'
import { Button } from '@bcs/ui'
import { api } from '../data/client'
import { useAppStore } from '../data/store'
import { navigate } from '../shell/router'
import { StepCard } from './StepCard'
import { isComplete, shouldOpenTimeTravel } from './directorView'

type Branch = DirectorState['branch']

/** The right-side Demo Director panel (design §27): steps, the expected action and the real event seen. */
export function DemoDirectorPanel() {
  const open = useAppStore((s) => s.ui.director)
  const state = useAppStore((s) => s.director.state)
  const setDirector = useAppStore((s) => s.setDirector)
  const [branch, setBranch] = useState<Branch>('main')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Time Travel opens once when `predict` becomes current, whether or not the panel is shown.
  const prev = useRef<DirectorState | null>(null)
  useEffect(() => {
    if (shouldOpenTimeTravel(prev.current, state)) navigate('time-travel')
    prev.current = state
  }, [state])

  async function run(call: () => Promise<{ data?: DirectorState; error?: unknown }>) {
    setBusy(true)
    setError(null)
    try {
      const r = await call()
      if (r.data) setDirector(r.data)
      else {
        // e.g. 409: a run is active in another window; show the true state
        const cur = await api.GET('/api/v1/director')
        if (cur.data) setDirector(cur.data)
        setError((r.error as { error?: { message?: string } } | undefined)?.error?.message ?? 'The Director could not do that.')
      }
    } catch {
      setError('The Ground Station is not reachable.')
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null
  const active = !!state?.active
  const complete = isComplete(state)
  return (
    <aside className="director bcs-panel" data-testid="director-panel" aria-label="Demo Director">
      <h2 className="director__title">Demo Director</h2>
      {!active && (
        <div className="director__start">
          <fieldset className="director__branch">
            <legend>Branch</legend>
            <label><input type="radio" name="director-branch" checked={branch === 'main'} onChange={() => setBranch('main')} /> Main: camera detects a change</label>
            <label><input type="radio" name="director-branch" checked={branch === 'early_warning'} onChange={() => setBranch('early_warning')} /> Early warning: sensors warn first</label>
          </fieldset>
          <Button variant="primary" disabled={busy} onClick={() => run(() => api.POST('/api/v1/director/start', { body: { branch } }))}>Start</Button>
        </div>
      )}
      {active && state && (
        <>
          <div className="director__status" data-testid="director-status">{complete ? 'Complete' : `Running · ${state.branch === 'early_warning' ? 'early warning' : 'main'} branch`}</div>
          <ol className="director__steps">
            {state.steps.map((s) => (
              <StepCard key={s.key} step={s} current={s.key === state.current} />
            ))}
          </ol>
          <div className="director__controls">
            {!complete && <Button disabled={busy} onClick={() => run(() => api.POST('/api/v1/director/skip'))}>Skip</Button>}
            {!complete && <Button disabled={busy} onClick={() => run(() => api.POST('/api/v1/director/retry'))}>Retry</Button>}
            <Button variant="danger" disabled={busy} onClick={() => run(() => api.POST('/api/v1/director/stop'))}>Exit</Button>
          </div>
        </>
      )}
      {error && <div className="director__error" role="alert">{error}</div>}
    </aside>
  )
}
