// The restoration plan editor (US 150-152): run the forecast, ask the AI for a plan, apply it (which
// starts its forecast). The zone grid mirrors the "with restoration" map's 3D zone hits, so zones can be
// picked without WebGL; a picked zone opens its ZonePlanPanel.
import { Button, SourceChip } from '@bcs/ui'
import type { Illustration, PlanVersion, Zone } from '@bcs/api-types'
import { KIND_LABELS } from './ZonePlanPanel'
import type { TimeTravelState } from './useTimeTravel'

function illustrationSummary(list: Illustration[]): string {
  if (list.length === 0) return 'Image keyframes: not requested yet. The code-only repaint is shown.'
  const n = (s: Illustration['status']) => list.filter((i) => i.status === s).length
  if (n('pending')) return `Image keyframes: ${n('ready')} ready, ${n('pending')} pending. The code-only repaint is shown meanwhile.`
  if (n('ready') === list.length) return 'Image keyframes: all ready for 2030 and 2035.'
  const reason = list.find((i) => i.status !== 'ready' && i.error)?.error
  return `Image keyframes: ${n('ready')} of ${list.length} ready${reason ? ` (${reason})` : ''}. The code-only repaint is shown where none is ready.`
}

/** Ruling R29: an empty plan (e.g. an AI draft with no zone at risk) says how to go on. */
export const EMPTY_PLAN_HINT = 'No zone is at high or critical risk; add interventions zone by zone.'

export function emptyPlanHint(plan: PlanVersion | null): string | null {
  return plan && plan.items.length === 0 ? EMPTY_PLAN_HINT : null
}

function planLine(plan: PlanVersion): string {
  return `Plan v${plan.version} · ${plan.status} · ${plan.source === 'ai' ? 'AI' : plan.source === 'operator' ? 'operator' : 'AI + operator'}`
}

export interface PlanEditorProps {
  tt: TimeTravelState
  zones: Pick<Zone, 'id' | 'label' | 'row' | 'col'>[]
  selectedZone: string | null
  onSelectZone: (zoneId: string | null) => void
}

export function PlanEditor({ tt, zones, selectedZone, onSelectZone }: PlanEditorProps) {
  const { plan, forecast } = tt
  const applied = !!plan && plan.status === 'applied' && forecast?.plan_id === plan.plan_id && forecast.plan_version === plan.version
  const sorted = [...zones].sort((a, b) => a.row - b.row || a.col - b.col)
  const planned = new Set(plan?.items.filter((i) => i.interventions.length).map((i) => i.zone_id))
  const tiers = forecast ? [...new Set(Object.values(forecast.parameter_sources).map((s) => s.tier))] : []
  const emptyHint = tt.proposing ? null : emptyPlanHint(plan)

  return (
    <section className="bcs-panel tt-plan" aria-label="Restoration plan">
      <header className="tt-plan__head">
        <h3 className="bcs-panel__title">Restoration plan</h3>
        {plan?.ai && <SourceChip tier={plan.ai.tier} model={plan.ai.model} cached={plan.ai.cached} />}
      </header>
      <div className="row-actions">
        <Button variant="primary" disabled={tt.running !== null} onClick={() => void tt.runForecast()}>
          Run forecast
        </Button>
        <Button disabled={tt.proposing !== null || tt.planBusy} onClick={() => void tt.proposePlan()}>
          Propose plan (AI)
        </Button>
        <Button disabled={!plan || tt.planBusy || applied || tt.running !== null} onClick={() => void tt.applyPlan()}>
          Apply plan
        </Button>
      </div>
      <p className="tt-plan__status" data-testid="plan-status" role="status">
        {tt.proposing ? 'The AI is drafting a plan…' : plan ? planLine(plan) : 'No plan yet.'}
        {tt.running ? ' · forecasting…' : ''}
      </p>
      {tt.planError && (
        <p className="tt-zone__error" role="alert">
          {tt.planError}
        </p>
      )}
      {plan && plan.warnings && plan.warnings.length > 0 && plan.source === 'ai' && (
        <ul className="tt-zone__warnings">
          {plan.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {emptyHint && (
        <p className="hint" data-testid="plan-empty-hint">
          {emptyHint}
        </p>
      )}
      {plan && plan.items.length > 0 && (
        <ul className="tt-plan__items">
          {plan.items.map((it) => (
            <li key={it.zone_id}>
              <button type="button" className="tt-plan__zone bcs-mono" onClick={() => onSelectZone(it.zone_id)}>
                {it.zone_id}
              </button>{' '}
              {it.interventions.map((iv) => KIND_LABELS[iv.kind] + (iv.sapling_count ? ` (${iv.sapling_count})` : '')).join(', ') || '—'}
            </li>
          ))}
        </ul>
      )}
      <div className="tt-plan__zones">
        <span className="hint">Zones on the “With restoration” map</span>
        <div className="zone-picker" role="group" aria-label="Plan zones">
          {sorted.map((z) => (
            <button
              key={z.id}
              type="button"
              className="zone-picker__cell"
              data-testid={`zone-hit-with-${z.id}`}
              aria-pressed={z.id === selectedZone}
              data-planned={planned.has(z.id) ? 'true' : 'false'}
              title={planned.has(z.id) ? `${z.id}: has interventions` : z.id}
              onClick={() => onSelectZone(z.id === selectedZone ? null : z.id)}
            >
              {z.label}
            </button>
          ))}
        </div>
      </div>
      {forecast && (
        <p className="hint tt-plan__meta">
          Forecast {forecast.plan_version ? `with plan v${forecast.plan_version}` : 'without a plan'} · prediction confidence{' '}
          {forecast.confidence_prediction.toFixed(2)} · parameters: {tiers.join(', ') || '—'}
        </p>
      )}
      <p className="hint tt-plan__meta">{illustrationSummary(tt.illustrations)}</p>
    </section>
  )
}
