import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { PlanVersion } from '@bcs/api-types'
import { EMPTY_PLAN_HINT, PlanEditor, emptyPlanHint } from './PlanEditor'
import { PROPOSAL_TIMEOUT_MS, PROPOSAL_TIMEOUT_TEXT, armProposalTimeout, type TimeTravelState } from './useTimeTravel'

const plan = (items: PlanVersion['items']): PlanVersion =>
  ({
    plan_id: 'p1',
    version: 1,
    created_at: '2026-10-16T02:00:00.000Z',
    source: 'ai',
    status: 'draft',
    items,
    warnings: [],
  }) as unknown as PlanVersion

const noop = async () => undefined
function tt(over: Partial<TimeTravelState>): TimeTravelState {
  return {
    forecast: null,
    forecastLoading: false,
    running: null,
    runError: null,
    illustrations: [],
    illustrationRev: 0,
    plan: null,
    proposing: null,
    planBusy: false,
    planError: null,
    zoneNotes: {},
    runForecast: noop,
    proposePlan: noop,
    applyPlan: noop,
    setZoneInterventions: noop,
    ...over,
  }
}
const render = (s: TimeTravelState) =>
  renderToStaticMarkup(<PlanEditor tt={s} zones={[]} selectedZone={null} onSelectZone={() => undefined} />)

describe('empty plan hint (ruling R29)', () => {
  const item = {
    zone_id: 'KSL-B3',
    interventions: [{ kind: 'silt_fence' }],
    priority: 1,
    rationale: 'AI',
    expected_uplift: { canopy_pp_2035: 0, tco2e_2035: 0 },
  } as PlanVersion['items'][number]

  test('only a plan with no items gets the hint', () => {
    expect(emptyPlanHint(plan([]))).toBe('No zone is at high or critical risk; add interventions zone by zone.')
    expect(emptyPlanHint(plan([item]))).toBeNull()
    expect(emptyPlanHint(null)).toBeNull()
  })

  test('the editor shows it for an empty plan, not while drafting nor for a plan with items', () => {
    expect(render(tt({ plan: plan([]) }))).toContain(EMPTY_PLAN_HINT)
    expect(render(tt({ plan: plan([]), proposing: 'req-2' }))).not.toContain(EMPTY_PLAN_HINT)
    expect(render(tt({ plan: plan([item]) }))).not.toContain(EMPTY_PLAN_HINT)
    expect(render(tt({}))).not.toContain(EMPTY_PLAN_HINT)
  })

  test('the timeout message is shown as the plan error and "Propose plan (AI)" is enabled again', () => {
    const html = render(tt({ planError: PROPOSAL_TIMEOUT_TEXT }))
    expect(html).toContain('The AI plan proposal didn&#x27;t arrive — try again.')
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Propose plan \(AI\)/)
    expect(render(tt({ proposing: 'req-1' }))).toMatch(/<button[^>]*disabled=""[^>]*>Propose plan \(AI\)/)
  })
})

describe('proposal timeout (ruling R29)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  test('a proposal still pending after 60 s times out', () => {
    vi.useFakeTimers()
    const onTimeout = vi.fn()
    armProposalTimeout('req-1', () => 'req-1', onTimeout)
    vi.advanceTimersByTime(PROPOSAL_TIMEOUT_MS - 1)
    expect(onTimeout).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(onTimeout).toHaveBeenCalledTimes(1)
    expect(PROPOSAL_TIMEOUT_MS).toBe(60_000)
  })

  test('nothing happens when the proposal arrived (disarmed) or another one is pending', () => {
    vi.useFakeTimers()
    const onTimeout = vi.fn()
    const disarm = armProposalTimeout('req-1', () => 'req-1', onTimeout)
    disarm()
    armProposalTimeout('req-1', () => 'req-2', onTimeout)
    armProposalTimeout('req-1', () => null, onTimeout)
    vi.advanceTimersByTime(2 * PROPOSAL_TIMEOUT_MS)
    expect(onTimeout).not.toHaveBeenCalled()
  })
})
