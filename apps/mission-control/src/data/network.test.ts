import { beforeEach, expect, test, vi } from 'vitest'
import type { Node, Task } from '@bcs/api-types'

vi.mock('./client', () => ({ api: { GET: vi.fn().mockResolvedValue({}) } }))

const { applyEvent } = await import('./live')
const { TELEMETRY_WINDOW_MS, appendPoint, useAppStore } = await import('./store')
const { heldNodes } = await import('./network')

function node(id: string, extra: Partial<Node> = {}): Node {
  return {
    id,
    node_type: 'water_quality',
    source: 'simulated',
    position: { e_m: 262.5, s_m: 262.5, lat: 3.3, lng: 101.2, u_px: 268.8, v_px: 268.8 },
    zone_id: 'KSL-C3',
    status: 'online',
    mode: 'baseline',
    interval_s: 30,
    fw_version: 'sim-1.0.0',
    last_seen_at: null,
    covers: { water: ['KSL-C3'], soil: [] },
    latest: null,
    ...extra,
  }
}

function task(id: string, extra: Partial<Task> = {}): Task {
  return {
    id,
    zone_id: 'KSL-B3',
    node_ids: ['WQ-01', 'TG-01'],
    status: 'issued',
    trigger: 'manual',
    reason: 'manual task for KSL-B3',
    duration_s: 180,
    created_at: '2026-10-16T03:00:00.000Z',
    updated_at: '2026-10-16T03:00:00.000Z',
    expires_at: '2026-10-16T03:03:00.000Z',
    cancelled_by: null,
    commands: [],
    timeline: [],
    ...extra,
  }
}

const ev = (type: string, data: unknown, at = '2026-10-16T03:00:01.000Z') => ({ v: 1 as const, type, id: `${type}-${at}`, at, data })

beforeEach(() => {
  const st = useAppStore.getState()
  st.setNodes([node('WQ-01'), node('SP-01', { node_type: 'soil_probe' })])
  st.setTasks([])
  useAppStore.setState({ nodes: { ...useAppStore.getState().nodes, telemetry: {}, rev: {} } })
})

test('node.telemetry updates latest values, last seen and the live buffer, but never the position', () => {
  const before = useAppStore.getState().nodes.items[0]!.position
  applyEvent(
    ev('node.telemetry', {
      node_id: 'WQ-01',
      sampled_at: '2026-10-16T03:00:00.500Z',
      mode: 'investigation',
      readings: { turbidity_ntu: 42 },
      health: { battery_pct: 88, rssi_dbm: -61, uptime_s: 10, fw_version: 'sim-1.0.0' },
      flags: [],
      late: false,
      source: 'simulated',
      replay: false,
    }),
  )
  const s = useAppStore.getState()
  const n = s.nodes.items.find((x) => x.id === 'WQ-01')!
  expect(n.latest?.readings.turbidity_ntu).toBe(42)
  expect(n.latest?.health.battery_pct).toBe(88)
  expect(n.mode).toBe('investigation')
  expect(n.last_seen_at).toBe('2026-10-16T03:00:01.000Z')
  expect(n.position).toBe(before)
  expect(s.nodes.telemetry['WQ-01']).toHaveLength(1)
  expect(s.nodes.rev['WQ-01']).toBe(1)
})

test('node.status marks a node offline', () => {
  applyEvent(ev('node.status', { node_id: 'SP-01', state: 'offline', mode: null, interval_s: null, at: 'x', reason: 'last will' }))
  expect(useAppStore.getState().nodes.items.find((x) => x.id === 'SP-01')!.status).toBe('offline')
})

test('task.updated upserts newest first and never goes back to an older version', () => {
  applyEvent(ev('task.updated', task('t1')))
  applyEvent(ev('task.updated', task('t2', { created_at: '2026-10-16T03:01:00.000Z', updated_at: '2026-10-16T03:01:00.000Z' })))
  applyEvent(ev('task.updated', task('t1', { status: 'active', updated_at: '2026-10-16T03:00:02.000Z' })))
  applyEvent(ev('task.updated', task('t1', { status: 'issued', updated_at: '2026-10-16T03:00:01.000Z' })))
  const items = useAppStore.getState().tasks.items
  expect(items.map((t) => t.id)).toEqual(['t2', 't1'])
  expect(items[1]!.status).toBe('active')
})

test('coverage.updated replaces the coverage snapshot', () => {
  applyEvent(ev('coverage.updated', { zones: [{ zone_id: 'KSL-A1', covered: false, water: [], soil: [] }], gaps: [] }))
  expect(useAppStore.getState().coverage.coverage?.zones).toHaveLength(1)
})

test('the live buffer keeps time order, drops duplicates and keeps only the last 15 minutes', () => {
  const p = (t: string) => ({ t, mode: 'baseline', late: false, readings: { ph: 7 } })
  let buf = appendPoint(undefined, p('2026-10-16T03:00:00.000Z'))
  buf = appendPoint(buf, p('2026-10-16T02:59:30.000Z'))
  buf = appendPoint(buf, p('2026-10-16T03:00:00.000Z'))
  expect(buf.map((x) => x.t)).toEqual(['2026-10-16T02:59:30.000Z', '2026-10-16T03:00:00.000Z'])
  const late = new Date(Date.parse('2026-10-16T03:00:00.000Z') + TELEMETRY_WINDOW_MS).toISOString()
  buf = appendPoint(buf, p(late))
  expect(buf.map((x) => x.t)).toEqual(['2026-10-16T03:00:00.000Z', late])
})

test('released and never-acknowledged nodes drop out of a task', () => {
  const t = task('t', {
    node_ids: ['WQ-01', 'WQ-02', 'TG-01'],
    commands: [
      { id: 'c1', node_id: 'WQ-01', type: 'set_mode', params: {}, issued_at: 'x', ack_status: 'accepted', retries: 0 },
      { id: 'c2', node_id: 'WQ-02', type: 'set_mode', params: {}, issued_at: 'x', ack_status: 'released', retries: 0 },
      { id: 'c3', node_id: 'TG-01', type: 'set_mode', params: {}, issued_at: 'x', ack_status: 'no_ack', retries: 1 },
    ],
  })
  expect(heldNodes(t)).toEqual(['WQ-01'])
})

test('an older (late, out-of-order or replayed) sample never rolls latest, mode or last seen back', () => {
  const sample = (sampled_at: string, mode: string, turbidity: number, replay = false) => ({
    node_id: 'WQ-01',
    sampled_at,
    mode,
    readings: { turbidity_ntu: turbidity },
    health: { battery_pct: 90, rssi_dbm: -60, uptime_s: 1, fw_version: 'sim-1.0.0' },
    flags: [],
    late: false,
    source: 'simulated' as const,
    replay,
  })
  applyEvent(ev('node.telemetry', sample('2026-10-16T03:00:10.000Z', 'investigation', 50), '2026-10-16T03:00:11.000Z'))
  applyEvent(ev('node.telemetry', sample('2026-10-16T02:58:00.000Z', 'baseline', 5, true), '2026-10-16T03:00:12.000Z'))
  applyEvent(ev('node.telemetry', sample('2026-10-16T03:00:05.000Z', 'baseline', 7), '2026-10-16T03:00:13.000Z'))
  let n = useAppStore.getState().nodes.items.find((x) => x.id === 'WQ-01')!
  expect(n.latest?.sampled_at).toBe('2026-10-16T03:00:10.000Z')
  expect(n.latest?.readings.turbidity_ntu).toBe(50)
  expect(n.mode).toBe('investigation')
  expect(n.last_seen_at).toBe('2026-10-16T03:00:11.000Z')
  // The older samples still reach the chart buffer, in time order, with the replay mark kept.
  const buf = useAppStore.getState().nodes.telemetry['WQ-01']!
  expect(buf.map((p) => p.t)).toEqual(['2026-10-16T02:58:00.000Z', '2026-10-16T03:00:05.000Z', '2026-10-16T03:00:10.000Z'])
  expect(buf[0]!.replay).toBe(true)
  // An equal or newer sample does update.
  applyEvent(ev('node.telemetry', sample('2026-10-16T03:00:12.000Z', 'investigation', 60), '2026-10-16T03:00:14.000Z'))
  n = useAppStore.getState().nodes.items.find((x) => x.id === 'WQ-01')!
  expect(n.latest?.readings.turbidity_ntu).toBe(60)
  expect(n.last_seen_at).toBe('2026-10-16T03:00:14.000Z')
})

test('the packet view merges stored and live samples newest first and keeps the replay mark', async () => {
  const { packetRows } = await import('../pages/SentinelNetwork/NodeDrawer')
  const p = (t: string, replay?: boolean) => ({ t, mode: 'baseline', late: false, readings: { ph: 7 }, ...(replay ? { replay } : {}) })
  const rows = packetRows([p('2026-10-16T03:00:00.000Z'), p('2026-10-16T03:00:30.000Z')], [p('2026-10-16T03:00:30.000Z', true), p('2026-10-16T03:01:00.000Z')], 10)
  expect(rows.map((r) => r.t)).toEqual(['2026-10-16T03:01:00.000Z', '2026-10-16T03:00:30.000Z', '2026-10-16T03:00:00.000Z'])
  expect(rows[1]!.replay).toBe(true)
})
