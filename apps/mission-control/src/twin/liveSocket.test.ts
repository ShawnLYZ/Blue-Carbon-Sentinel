import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { openLiveSocket, liveReconnectDelays } from './liveSocket'

class FakeWs {
  static all: FakeWs[] = []
  binaryType = 'blob'
  sent: string[] = []
  closed = false
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  constructor(public url: string) {
    FakeWs.all.push(this)
  }
  send(s: string) {
    this.sent.push(s)
  }
  close() {
    if (this.closed) return
    this.closed = true
    this.onclose?.()
  }
}

function frame(seq: number): ArrayBuffer {
  const raw = new TextEncoder().encode(JSON.stringify({ seq, raster_bytes: 0, height_bytes: 0 }))
  const buf = new ArrayBuffer(12 + raw.length)
  new Uint8Array(buf).set([0x42, 0x43, 0x53, 0x4c])
  const dv = new DataView(buf)
  dv.setUint16(4, 1, true)
  dv.setUint32(8, raw.length, true)
  new Uint8Array(buf).set(raw, 12)
  return buf
}

const createSocket = (url: string) => new FakeWs(url) as unknown as WebSocket

beforeEach(() => {
  FakeWs.all = []
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

test('J3 back-off: 0.5 s doubling to a 5 s cap', () => {
  expect(liveReconnectDelays(7)).toEqual([500, 1000, 2000, 4000, 5000, 5000, 5000])
})

test('sends the client config on open and decodes binary frames', () => {
  const seqs: number[] = []
  const stop = openLiveSocket((f) => seqs.push(f.header.seq), 10, { url: 'ws://x/ws/live', createSocket })
  const ws = FakeWs.all[0]!
  expect(ws.binaryType).toBe('arraybuffer')
  ws.onopen!()
  expect(JSON.parse(ws.sent[0]!)).toEqual({ type: 'config', max_fps: 10, raster: true, height: true })
  ws.onmessage!({ data: frame(4) })
  ws.onmessage!({ data: new ArrayBuffer(3) }) // malformed frames are dropped, not fatal
  ws.onmessage!({ data: 'text' })
  expect(seqs).toEqual([4])
  stop()
})

test('reconnects on the back-off schedule and stops when disposed', () => {
  const stop = openLiveSocket(() => undefined, 10, { url: 'ws://x/ws/live', createSocket })
  const opens: number[] = []
  let t = 0
  for (const expected of [500, 1000, 2000, 4000, 5000, 5000]) {
    FakeWs.all.at(-1)!.close()
    const before = FakeWs.all.length
    vi.advanceTimersByTime(expected - 1)
    expect(FakeWs.all.length).toBe(before)
    vi.advanceTimersByTime(1)
    expect(FakeWs.all.length).toBe(before + 1)
    t += expected
    opens.push(t)
  }
  // A successful open resets the schedule.
  FakeWs.all.at(-1)!.onopen!()
  FakeWs.all.at(-1)!.close()
  vi.advanceTimersByTime(500)
  const n = FakeWs.all.length
  stop()
  expect(FakeWs.all.at(-1)!.closed).toBe(true)
  vi.advanceTimersByTime(60_000)
  expect(FakeWs.all.length).toBe(n)
})
