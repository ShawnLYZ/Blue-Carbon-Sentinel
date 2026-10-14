import type { DirectorState, DirectorStep } from '@bcs/api-types'

export type StepStatus = DirectorStep['status']

export const STATUS_LABELS: Record<StepStatus, string> = {
  pending: 'Pending',
  waiting: 'Waiting',
  blocked: 'Blocked',
  done: 'Done',
  skipped: 'Skipped',
}

/** The Simulator Console is a separate window; it has no dedicated shortcut, so the OS window switcher it is. */
export const SIM_CONSOLE_KEY_HINT = 'Alt+Tab'

/** What the operator is to do for `step` (`null`: nothing, the system works on its own). */
export function actionHint(step: Pick<DirectorStep, 'key' | 'action'>): string | null {
  switch (step.key) {
    case 'predict':
      return 'Run forecast, then scrub to 2035'
    case 'detect':
    case 'restore':
      return 'Physical action on the model'
    case 'measure':
      return `Switch to the Simulator Console window (${SIM_CONSOLE_KEY_HINT})`
    default:
      return step.action ?? null
  }
}

/** The extra line under a blocked reason: what to check. */
export function blockedHint(reason: string | null | undefined): string | null {
  return reason && /camera offline/i.test(reason) ? 'Check the camera power and Wi-Fi, or skip this step.' : null
}

/** A run whose steps are all finished: the server keeps it active with no current step. */
export function isComplete(state: DirectorState | null): boolean {
  return !!state && state.active && state.current === null
}

/** Time Travel opens once, when `predict` becomes the current step (not on every state event while it is). */
export function shouldOpenTimeTravel(prev: DirectorState | null, next: DirectorState | null): boolean {
  return next?.current === 'predict' && prev?.current !== 'predict'
}
