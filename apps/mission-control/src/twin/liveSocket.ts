// /ws/live client (addendum J1, J3): binary frames in, one config message out on every (re)connect.
// The server sends the newest frame on connect, so a reconnect needs no other resync.
import { backoffDelays } from '../data/events'
import { decodeLiveFrame, type LiveFrame } from './liveDecoder'

/** J3 reconnect delays: 0.5 s doubling to a 5 s cap (shared with /ws/events). */
export const liveReconnectDelays = backoffDelays

export interface LiveSocketOptions {
  /** Socket URL; defaults to `/ws/live` on the page's origin (Vite proxies /ws in dev). */
  url?: string
  /** Test seam. */
  createSocket?: (url: string) => WebSocket
}

function defaultUrl(): string {
  const { protocol, host } = globalThis.location
  return `${protocol === 'https:' ? 'wss:' : 'ws:'}//${host}/ws/live`
}

/** Opens /ws/live and keeps reconnecting with the J3 back-off until the disposer is called. */
export function openLiveSocket(onFrame: (f: LiveFrame) => void, maxFps: number, opts: LiveSocketOptions = {}): () => void {
  let stopped = false
  let attempt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let current: WebSocket | null = null

  const schedule = () => {
    if (stopped) return
    const delay = liveReconnectDelays(attempt + 1)[attempt]!
    attempt += 1
    timer = setTimeout(open, delay)
  }

  function open() {
    if (stopped) return
    let ws: WebSocket
    try {
      ws = (opts.createSocket ?? ((u) => new WebSocket(u)))(opts.url ?? defaultUrl())
    } catch {
      schedule()
      return
    }
    current = ws
    ws.binaryType = 'arraybuffer'
    let dead = false
    ws.onopen = () => {
      if (stopped || dead) return
      attempt = 0
      ws.send(JSON.stringify({ type: 'config', max_fps: maxFps, raster: true, height: true }))
    }
    ws.onmessage = (ev: MessageEvent) => {
      if (stopped || dead || !(ev.data instanceof ArrayBuffer)) return
      let frame: LiveFrame
      try {
        frame = decodeLiveFrame(ev.data)
      } catch {
        return // a malformed frame is dropped; the next one replaces it
      }
      onFrame(frame)
    }
    ws.onclose = () => {
      if (dead) return
      dead = true
      if (current === ws) current = null
      schedule()
    }
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
  }
}
