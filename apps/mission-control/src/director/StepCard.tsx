import type { DirectorStep } from '@bcs/api-types'
import { formatMYT } from '@bcs/ui'
import { STATUS_LABELS, actionHint, blockedHint } from './directorView'

const ICONS: Record<DirectorStep['status'], string> = { pending: '○', waiting: '◔', blocked: '⚠', done: '✓', skipped: '↷' }

export function StepCard({ step, current }: { step: DirectorStep; current: boolean }) {
  const hint = current || step.status === 'blocked' ? actionHint(step) : null
  const blocked = step.status === 'blocked' ? (step.blocked_reason ?? 'Blocked') : null
  return (
    <li className={`dstep dstep--${step.status}${current ? ' dstep--current' : ''}`} data-testid={`step-${step.key}`} data-status={step.status}>
      <span className="dstep__icon" role="img" aria-label={STATUS_LABELS[step.status]}>{ICONS[step.status]}</span>
      <div className="dstep__body">
        <div className="dstep__caption">{step.n > 0 ? `${step.n}. ` : ''}{step.caption}</div>
        {hint && <div className="dstep__action">{hint}</div>}
        {blocked && <div className="dstep__blocked">{blocked}</div>}
        {blocked && blockedHint(blocked) && <div className="dstep__hint">{blockedHint(blocked)}</div>}
        {step.detected && (
          <div className="dstep__detected">
            {step.detected.summary} <span className="bcs-mono">{formatMYT(step.detected.at, { seconds: true })}</span>
          </div>
        )}
      </div>
    </li>
  )
}
