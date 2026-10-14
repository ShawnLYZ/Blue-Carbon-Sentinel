// Times are stored and sent as UTC ISO 8601; Mission Control shows Malaysia time (addendum F2).
const MYT = 'Asia/Kuala_Lumpur'

export function formatMYT(iso: string, opts: { seconds?: boolean } = {}): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: MYT,
    hour: '2-digit',
    minute: '2-digit',
    second: opts.seconds ? '2-digit' : undefined,
    hourCycle: 'h23',
  }).formatToParts(d)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '00'
  const hms = `${get('hour')}:${get('minute')}` + (opts.seconds ? `:${get('second')}` : '')
  return `${hms} MYT`
}

export function formatMYTDateTime(iso: string, opts: { seconds?: boolean } = {}): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const date = new Intl.DateTimeFormat('en-CA', { timeZone: MYT }).format(d)
  return `${date} ${formatMYT(iso, opts)}`
}
