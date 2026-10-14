// Time Travel's page state: the forecast shown, its illustrations, the restoration plan being edited and
// the live events that move them (forecast.ready, illustration.ready, plan.updated). Forecast and plan
// runs are asynchronous on the Ground Station: the POST answers 202 and the event says when it is done.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { EventMap, Forecast, Illustration, Intervention, PlanItem, PlanVersion } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { onLiveEvent } from '../../data/live'
import { useAppStore } from '../../data/store'

/** Coalesces the 4 illustration.ready events of a forecast into one refetch. */
export const ILLUSTRATION_SETTLE_MS = 300

/** A pending AI plan proposal is given up after this long (ruling R29: a failed draft emits no event). */
export const PROPOSAL_TIMEOUT_MS = 60_000
export const PROPOSAL_TIMEOUT_TEXT = "The AI plan proposal didn't arrive — try again."

/**
 * Arms the proposal timeout for request `id`: after `ms`, if `current()` is still `id`, calls `onTimeout`.
 * Returns the disarm function (call it when the proposal arrives or the page goes away).
 */
export function armProposalTimeout(
  id: string,
  current: () => string | null,
  onTimeout: () => void,
  ms: number = PROPOSAL_TIMEOUT_MS,
): () => void {
  const timer = setTimeout(() => {
    if (current() === id) onTimeout()
  }, ms)
  return () => clearTimeout(timer)
}

/** What to do when a forecast cannot start (409, Review Focus 3). */
export function forecastGuidance(message: string): string {
  if (/evidence-grade capture|needs a capture/i.test(message))
    return `Take a capture first: the forecast starts from the latest evidence-grade capture (Satellite Intelligence, Capture now). ${message}`
  if (/baseline/i.test(message))
    return `Set a baseline first: on Satellite Intelligence, set an evidence-grade capture as the baseline. ${message}`
  return message
}

/** Per-zone notes from the last edit made in that zone's panel. */
export interface ZoneNote {
  warnings: string[]
  error: string | null
}

export interface TimeTravelState {
  forecast: Forecast | null
  /** `loading` until GET /forecasts/latest answered. */
  forecastLoading: boolean
  /** The forecast run in progress (202 accepted, no forecast.ready yet). */
  running: string | null
  runError: string | null
  illustrations: Illustration[]
  /** Bumps on each settled batch of illustration.ready events of the shown forecast. */
  illustrationRev: number
  plan: PlanVersion | null
  /** A proposal in progress (its plan ID). */
  proposing: string | null
  planBusy: boolean
  planError: string | null
  zoneNotes: Record<string, ZoneNote>
  runForecast: () => Promise<void>
  proposePlan: () => Promise<void>
  applyPlan: () => Promise<void>
  setZoneInterventions: (zoneId: string, interventions: Intervention[]) => Promise<void>
}

/** The plan's items with `zoneId`'s interventions replaced (an emptied zone is dropped). */
export function withZoneInterventions(items: PlanItem[], zoneId: string, interventions: Intervention[]): PlanItem[] {
  const out: PlanItem[] = []
  let found = false
  for (const it of items) {
    if (it.zone_id !== zoneId) out.push(it)
    else {
      found = true
      if (interventions.length) out.push({ ...it, interventions })
    }
  }
  if (!found && interventions.length)
    out.push({
      zone_id: zoneId,
      interventions,
      priority: 3,
      rationale: 'Operator edit',
      expected_uplift: { canopy_pp_2035: 0, tco2e_2035: 0 },
    })
  return out
}

export function useTimeTravel(): TimeTravelState {
  const [forecast, setForecast] = useState<Forecast | null>(null)
  const [forecastLoading, setForecastLoading] = useState(true)
  const [running, setRunning] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [illustrations, setIllustrations] = useState<Illustration[]>([])
  const [illustrationRev, setIllustrationRev] = useState(0)
  const [plan, setPlan] = useState<PlanVersion | null>(null)
  const [proposing, setProposing] = useState<string | null>(null)
  const [planBusy, setPlanBusy] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [zoneNotes, setZoneNotes] = useState<Record<string, ZoneNote>>({})

  const forecastRef = useRef<Forecast | null>(null)
  forecastRef.current = forecast
  const runningRef = useRef<string | null>(null)
  runningRef.current = running
  const planRef = useRef<PlanVersion | null>(null)
  planRef.current = plan
  const proposingRef = useRef<string | null>(null)
  proposingRef.current = proposing
  /** forecast.ready events seen (an event can beat the POST's own answer). */
  const finished = useRef(new Map<string, string>())
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const loadIllustrations = useCallback(async (id: string, bump: boolean) => {
    const r = await api.GET('/api/v1/forecasts/{forecast_id}/illustrations', { params: { path: { forecast_id: id } } })
    if (!alive.current || forecastRef.current?.id !== id || !r.data) return
    setIllustrations(r.data)
    if (bump) setIllustrationRev((v) => v + 1)
  }, [])

  const showForecast = useCallback(
    (f: Forecast) => {
      // Never step back to an older forecast (events and fetches can arrive out of order).
      const cur = forecastRef.current
      if (cur && cur.id !== f.id && cur.created_at > f.created_at) return
      if (cur?.id !== f.id) {
        forecastRef.current = f
        setForecast(f)
        setIllustrations([])
        loadIllustrations(f.id, false).catch(() => undefined)
      }
    },
    [loadIllustrations],
  )

  const finishRun = useCallback(
    async (id: string, status: string) => {
      if (runningRef.current === id) {
        runningRef.current = null
        setRunning(null)
      }
      const r = await api.GET('/api/v1/forecasts/{forecast_id}', { params: { path: { forecast_id: id } } })
      if (!alive.current || !r.data) return
      if (r.data.status === 'ready') showForecast(r.data)
      else if (status === 'failed' || r.data.status === 'failed') {
        const why = (r.data.summary as { error?: string } | undefined)?.error
        setRunError(`The forecast failed${why ? `: ${why}` : '.'} The last good forecast stays on screen.`)
      }
    },
    [showForecast],
  )

  const loadPlan = useCallback(async (planId: string) => {
    const r = await api.GET('/api/v1/plans/{plan_id}', { params: { path: { plan_id: planId }, query: {} } })
    if (!alive.current || !r.data) return false
    const cur = planRef.current
    if (!cur || cur.plan_id !== r.data.plan_id || r.data.version >= cur.version) {
      planRef.current = r.data
      setPlan(r.data)
    }
    if (proposingRef.current === planId) {
      proposingRef.current = null
      setProposing(null)
    }
    return true
  }, [])

  // Initial snapshot: the newest ready forecast (404: none yet) and the newest plan.
  useEffect(() => {
    api.GET('/api/v1/forecasts/latest').then(
      (r) => {
        if (!alive.current) return
        if (r.data) showForecast(r.data)
        setForecastLoading(false)
      },
      () => alive.current && setForecastLoading(false),
    )
    api.GET('/api/v1/plans').then(
      (r) => {
        const newest = r.data?.[0]
        if (newest && !planRef.current) loadPlan(newest.plan_id).catch(() => undefined)
      },
      () => undefined,
    )
  }, [showForecast, loadPlan])

  // Live events.
  useEffect(() => {
    let settle: ReturnType<typeof setTimeout> | undefined
    const off = onLiveEvent((e) => {
      if (e.type === 'forecast.ready') {
        const d = e.data as EventMap['forecast.ready']
        finished.current.set(d.forecast_id, d.status)
        if (d.status === 'ready' || d.forecast_id === runningRef.current) finishRun(d.forecast_id, d.status).catch(() => undefined)
      } else if (e.type === 'illustration.ready') {
        const d = e.data as EventMap['illustration.ready']
        const id = forecastRef.current?.id
        if (!id || d.forecast_id !== id) return
        clearTimeout(settle)
        settle = setTimeout(() => loadIllustrations(id, true).catch(() => undefined), ILLUSTRATION_SETTLE_MS)
      } else if (e.type === 'plan.updated') {
        const d = e.data as EventMap['plan.updated']
        if (d.plan_id === proposingRef.current || d.plan_id === planRef.current?.plan_id || !planRef.current)
          loadPlan(d.plan_id).catch(() => undefined)
      }
    })
    return () => {
      off()
      clearTimeout(settle)
    }
  }, [finishRun, loadIllustrations, loadPlan])

  // A proposal whose plan.updated never comes (the planner failed) stops spinning after 60 s.
  useEffect(() => {
    if (!proposing) return
    return armProposalTimeout(
      proposing,
      () => proposingRef.current,
      () => {
        if (!alive.current) return
        proposingRef.current = null
        setProposing(null)
        setPlanError(PROPOSAL_TIMEOUT_TEXT)
      },
    )
  }, [proposing])

  // After a reconnect, events of a run in progress may have been missed: check it once.
  useEffect(
    () =>
      useAppStore.subscribe((s, prev) => {
        if (s.system.connection !== 'open' || prev.system.connection === 'open') return
        const id = runningRef.current
        if (id) finishRun(id, 'unknown').catch(() => undefined)
        const pid = proposingRef.current
        if (pid) loadPlan(pid).catch(() => undefined)
      }),
    [finishRun, loadPlan],
  )

  /** A run accepted with `id`: wait for its forecast.ready (unless it already arrived). */
  const track = useCallback(
    (id: string) => {
      const done = finished.current.get(id)
      if (done) finishRun(id, done).catch(() => undefined)
      else {
        runningRef.current = id
        setRunning(id)
      }
    },
    [finishRun],
  )

  const runForecast = useCallback(async () => {
    setRunError(null)
    try {
      const r = await api.POST('/api/v1/forecasts', { body: {} })
      if (r.data) track(r.data.forecast_id)
      else setRunError(forecastGuidance(apiErrorText(r.error, 'The forecast could not start.')))
    } catch (e) {
      setRunError(networkErrorText(e))
    }
  }, [track])

  const proposePlan = useCallback(async () => {
    setPlanError(null)
    setPlanBusy(true)
    try {
      const r = await api.POST('/api/v1/plans/propose', { body: {} })
      if (!r.data) {
        setPlanError(apiErrorText(r.error, 'The planner did not accept the request.'))
        return
      }
      const id = r.data.request_id
      proposingRef.current = id
      setProposing(id)
      // plan.updated may have come before this answer: look once.
      const got = await api.GET('/api/v1/plans/{plan_id}', { params: { path: { plan_id: id }, query: {} } })
      if (got.data) await loadPlan(id)
    } catch (e) {
      setPlanError(networkErrorText(e))
    } finally {
      setPlanBusy(false)
    }
  }, [loadPlan])

  const setZoneInterventions = useCallback(async (zoneId: string, interventions: Intervention[]) => {
    const cur = planRef.current
    if (!cur) return
    setPlanBusy(true)
    try {
      const r = await api.PUT('/api/v1/plans/{plan_id}', {
        params: { path: { plan_id: cur.plan_id } },
        body: { items: withZoneInterventions(cur.items, zoneId, interventions) },
      })
      if (r.data) {
        planRef.current = r.data
        setPlan(r.data)
        // Warnings (e.g. the species switch, which names no zone) belong to the panel the edit came from.
        setZoneNotes((n) => ({ ...n, [zoneId]: { warnings: r.data.warnings ?? [], error: null } }))
      } else {
        // 422: the plan is unchanged and stays editable (Review Focus 2).
        setZoneNotes((n) => ({ ...n, [zoneId]: { warnings: [], error: apiErrorText(r.error, 'The plan edit was rejected.') } }))
      }
    } catch (e) {
      setZoneNotes((n) => ({ ...n, [zoneId]: { warnings: [], error: networkErrorText(e) } }))
    } finally {
      setPlanBusy(false)
    }
  }, [])

  const applyPlan = useCallback(async () => {
    const cur = planRef.current
    if (!cur) return
    setPlanError(null)
    setRunError(null)
    setPlanBusy(true)
    try {
      const r = await api.POST('/api/v1/plans/{plan_id}/apply', {
        params: { path: { plan_id: cur.plan_id } },
        body: { version: cur.version },
      })
      if (r.data) {
        planRef.current = r.data.plan
        setPlan(r.data.plan)
        track(r.data.forecast_id)
      } else setPlanError(forecastGuidance(apiErrorText(r.error, 'The plan could not be applied.')))
    } catch (e) {
      setPlanError(networkErrorText(e))
    } finally {
      setPlanBusy(false)
    }
  }, [track])

  return {
    forecast,
    forecastLoading,
    running,
    runError,
    illustrations,
    illustrationRev,
    plan,
    proposing,
    planBusy,
    planError,
    zoneNotes,
    runForecast,
    proposePlan,
    applyPlan,
    setZoneInterventions,
  }
}
