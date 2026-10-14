export type DotStatus = 'ok' | 'warn' | 'fail' | 'off'

export function StatusDot({ status, label }: { status: DotStatus; label?: string }) {
  return <span className={`bcs-dot bcs-dot--${status}`} role="img" aria-label={label ?? status} title={label ?? status} />
}
