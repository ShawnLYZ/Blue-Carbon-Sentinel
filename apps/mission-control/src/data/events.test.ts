import { expect, test, vi } from 'vitest'
import { backoffDelays, startResync, type SocketLike } from './events'

class FakeSocket implements SocketLike {
  onmessage: ((ev: { data: string }) => void) | null = null
  emit(e: { id: string; at: string }) {
    this.onmessage?.({ data: JSON.stringify({ v: 1, type: 'x', data: {}, ...e }) })
  }
}
const flush = () => new Promise((r) => setTimeout(r, 0))

test('events client applies buffered events newer than the snapshot after resync', async () => {
  const applied: string[] = []
  const ws = new FakeSocket()
  const fetchSnapshot = vi.fn().mockResolvedValue({ at: '2026-10-16T03:00:00.000Z' })
  startResync(ws, fetchSnapshot, (e) => applied.push(e.id))
  ws.emit({ id: 'old', at: '2026-10-16T02:59:59.000Z' })
  ws.emit({ id: 'new', at: '2026-10-16T03:00:01.000Z' })
  await flush()
  expect(applied).toEqual(['new'])
})

test('events arriving after the snapshot is applied pass straight through', async () => {
  const applied: string[] = []
  const ws = new FakeSocket()
  startResync(ws, async () => ({ at: '2026-10-16T03:00:00.000Z' }), (e) => applied.push(e.id))
  await flush()
  ws.emit({ id: 'live', at: '2026-10-16T03:00:05.000Z' })
  expect(applied).toEqual(['live'])
})

test('reconnect back-off caps at 5 s', () => {
  expect(backoffDelays(8)).toEqual([500, 1000, 2000, 4000, 5000, 5000, 5000, 5000])
})
