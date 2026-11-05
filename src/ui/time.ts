// Malaysia time (MYT) formatting, en-MY.

const TZ = 'Asia/Kuala_Lumpur'

const timeFmt = new Intl.DateTimeFormat('en-MY', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const timeSecFmt = new Intl.DateTimeFormat('en-MY', {
  timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})
const dateFmt = new Intl.DateTimeFormat('en-MY', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' })

export function formatMYT(ms: number, opts?: { seconds?: boolean }): string {
  return `${(opts?.seconds ? timeSecFmt : timeFmt).format(ms)} MYT`
}

export function formatMYTDateTime(ms: number): string {
  return `${dateFmt.format(ms)}, ${timeFmt.format(ms)} MYT`
}

export function timeAgo(ms: number | null, now: number): string {
  if (ms == null) return 'never'
  const s = Math.floor((now - ms) / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s} s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.floor(h / 24)
  return `${d} day${d === 1 ? '' : 's'} ago`
}

export function formatArea(m2: number): string {
  return `${(m2 / 10_000).toFixed(2)} ha`
}
