// Resilient /ws/events client (addendum J2, J3): subscribe and buffer, fetch snapshots over HTTP,
// apply buffered events newer than the snapshot, then pass events straight through.
// Reconnects use back-off from 0.5 s up to a 5 s cap.
import type { EventEnvelope } from '@bcs/api-types'

export type ConnState = 'connecting' | 'open' | 'closed'

/** The part of a WebSocket the resync logic needs; lets tests drive it without a socket. */
export interface SocketLike {
  onmessage: ((ev: { data: string }) => void) | null
}

export interface Snapshot {
  /** Server time of the snapshot (ISO UTC). Events at or before it are already reflected. */
  at: string
}

export const BACKOFF_START_MS = 500
export const BACKOFF_CAP_MS = 5000

/** First `n` reconnect delays: 500, 1000, 2000, 4000, then 5000 forever. */
export function backoffDelays(n: number): number[] {
  const out: number[] = []
  let d = BACKOFF_START_MS
  for (let i = 0; i < n; i++) {
    out.push(d)
    d = Math.min(d * 2, BACKOFF_CAP_MS)
  }
  return out
}

function parseEvent(raw: string): EventEnvelope | null {
  try {
    const e = JSON.parse(raw) as EventEnvelope
    return e && typeof e.id === 'string' && typeof e.at === 'string' ? e : null
  } catch {
    return null
  }
}

/**
 * J3 steps 1-3 on an already-subscribed socket. Events are buffered until `fetchSnapshot` resolves;
 * buffered events whose `at` is newer than the snapshot are then applied in arrival order, and later
 * events go straight to `apply`. Rejects if the snapshot cannot be fetched (the caller reconnects).
 */
export async function startResync(
  ws: SocketLike,
  fetchSnapshot: () => Promise<Snapshot>,
  apply: (e: EventEnvelope) => void,
): Promise<void> {
  let buffer: EventEnvelope[] | null = []
  ws.onmessage = (ev) => {
    const e = parseEvent(ev.data)
    if (!e) return
    if (buffer) buffer.push(e)
    else apply(e)
  }
  const snap = await fetchSnapshot()
  const cutoff = Date.parse(snap.at)
  const pending = buffer
  buffer = null
  for (const e of pending) {
    if (Date.parse(e.at) > cutoff) apply(e)
  }
}

export interface ConnectOptions {
  /** Fetches and applies HTTP snapshots; defaults to "nothing to fetch" (all events apply). */
  fetchSnapshot?: () => Promise<Snapshot>
  /** Socket URL; defaults to `/ws/events` on the page's origin. */
  url?: string
  /** Test seam. */
  createSocket?: (url: string) => WebSocket
}

function defaultUrl(): string {
  const { protocol, host } = globalThis.location
  return `${protocol === 'https:' ? 'wss:' : 'ws:'}//${host}/ws/events`
}

/** Connects and keeps reconnecting until the returned function is called. */
export function connectEvents(
  onEvent: (e: EventEnvelope) => void,
  onState: (s: ConnState) => void,
  opts: ConnectOptions = {},
): () => void {
  const fetchSnapshot = opts.fetchSnapshot ?? (async () => ({ at: new Date(0).toISOString() }))
  let stopped = false
  let attempt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let current: WebSocket | null = null

  const schedule = () => {
    if (stopped) return
    const delay = backoffDelays(attempt + 1)[attempt]!
    attempt += 1
    timer = setTimeout(open, delay)
  }

  function open() {
    if (stopped) return
    onState('connecting')
    let ws: WebSocket
    try {
      ws = (opts.createSocket ?? ((u) => new WebSocket(u)))(opts.url ?? defaultUrl())
    } catch {
      onState('closed')
      schedule()
      return
    }
    current = ws
    let dead = false
    const fail = () => {
      if (dead) return
      dead = true
      if (current === ws) current = null
      if (!stopped) onState('closed')
      schedule()
    }
    ws.onopen = () => {
      if (stopped || dead) return
      onState('open')
      startResync(
        ws as unknown as SocketLike,
        fetchSnapshot,
        (e) => {
          if (!stopped && !dead) onEvent(e)
        },
      )
        .then(() => {
          if (!stopped && !dead) attempt = 0
        })
        .catch(() => ws.close())
    }
    ws.onclose = fail
    ws.onerror = () => ws.close()
  }

  open()
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
    const ws = current
    current = null
    if (ws) {
      ws.onclose = null
      ws.close()
    }
    onState('closed')
  }
}
