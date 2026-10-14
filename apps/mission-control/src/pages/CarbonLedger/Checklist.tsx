import { Button, Panel } from '@bcs/ui'
import type { EvidenceChecklist, PlanSummary } from '@bcs/api-types'
import { CHECKLIST_KEYS, CHECKLIST_LABELS, tick } from './format'

/** The four evidence items of the selected plan and "Generate Projected record" (enabled when all pass). */
export function Checklist({
  plans,
  planId,
  onSelectPlan,
  checklist,
  busy,
  error,
  onGenerate,
}: {
  plans: PlanSummary[]
  planId: string | null
  onSelectPlan: (id: string) => void
  checklist: EvidenceChecklist | null
  busy: boolean
  error: string | null
  onGenerate: () => void
}) {
  const complete = !!checklist && checklist.missing.length === 0
  return (
    <Panel title="Evidence checklist">
      {plans.length === 0 ? (
        <p className="hint">No restoration plan yet. Propose and apply one on Time Travel.</p>
      ) : (
        <>
          {plans.length > 1 && (
            <label className="ledger-plan-select">
              <span className="hint">Plan</span>
              <select value={planId ?? ''} onChange={(e) => onSelectPlan(e.target.value)} aria-label="Plan">
                {plans.map((p) => (
                  <option key={p.plan_id} value={p.plan_id}>
                    {p.plan_id.slice(-8)} · v{p.version} · {p.status}
                  </option>
                ))}
              </select>
            </label>
          )}
          <ul className="ledger-checklist" data-testid="checklist">
            {CHECKLIST_KEYS.map((k) => {
              const ok = !!checklist?.[k]
              return (
                <li key={k} data-item={k} data-ok={ok}>
                  <span className={`ledger-tick ledger-tick--${ok ? 'ok' : 'no'}`} aria-label={ok ? 'passed' : 'missing'}>{tick(ok)}</span> {CHECKLIST_LABELS[k]}
                </li>
              )
            })}
          </ul>
        </>
      )}
      <div className="row-actions">
        <Button variant="primary" onClick={onGenerate} disabled={!complete || busy}>
          Generate Projected record
        </Button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Panel>
  )
}
