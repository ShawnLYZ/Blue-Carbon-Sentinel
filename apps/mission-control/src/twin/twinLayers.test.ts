import { describe, expect, test } from 'vitest'
import type { Alert, Assessment, Node } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { alertMarkers } from './AlertMarkers'
import { fieldPoints, fieldTextureData } from './FieldOverlay'
import { activeOverlay, fieldLegend, layerChanges, layerOn } from './layers'
import { tileHeight } from './RiskTiles'
import { createSurfaceState, surfaceVisible, OVERLAY_FIELD } from './surfaceMaterial'
import { DIEBACK_CANOPY, HEALTHY_CANOPY, treeCanopyColour, treeScale } from './Trees'

describe('layer state', () => {
  test('defaults: reality, grid, risk and the network layers on; overlays and carbon off', () => {
    for (const k of ['reality', 'grid', 'risk', 'nodes', 'coverage', 'tasking', 'trees', 'alerts']) expect(layerOn({}, k)).toBe(true)
    for (const k of ['ndvi', 'classes', 'water:turbidity_ntu', 'carbon']) expect(layerOn({}, k)).toBe(false)
    expect(layerOn({ grid: false }, 'grid')).toBe(false)
  })

  test('switching an overlay on turns the other overlays off; other layers are independent', () => {
    const ch = layerChanges('water:turbidity_ntu', true)
    expect(ch['water:turbidity_ntu']).toBe(true)
    expect(ch.ndvi).toBe(false)
    expect(ch['soil:soil_moisture_pct']).toBe(false)
    expect(layerChanges('trees', true)).toEqual({ trees: true })
    expect(layerChanges('ndvi', false)).toEqual({ ndvi: false })
    expect(activeOverlay({ ...ch })).toBe('water:turbidity_ntu')
    expect(activeOverlay({})).toBeNull()
  })

  test('field legends carry the reading unit', () => {
    expect(fieldLegend('water:turbidity_ntu')).toMatchObject({ label: 'Turbidity', unit: 'NTU', min: 0, max: 200 })
    expect(fieldLegend('soil:porewater_salinity_psu').unit).toBe('PSU')
  })
})

const node = (id: string, type: Node['node_type'], e: number, s: number, readings: Record<string, number>, status: Node['status'] = 'online') =>
  ({
    id,
    node_type: type,
    status,
    position: { e_m: e, s_m: s, lat: 0, lng: 0, u_px: 0, v_px: 0 },
    latest: { sampled_at: '2026-10-12T00:00:00Z', readings, health: {}, flags: [], late: false },
  }) as unknown as Node

describe('fields', () => {
  test('field points use online nodes of the layer type with the reading', () => {
    const nodes = [
      node('WQ-01', 'water_quality', 10, 20, { turbidity_ntu: 40 }),
      node('WQ-02', 'water_quality', 30, 40, { turbidity_ntu: 60 }, 'offline'),
      node('SP-01', 'soil_probe', 50, 60, { soil_moisture_pct: 70 }),
    ]
    expect(fieldPoints(nodes, 'water:turbidity_ntu')).toEqual([{ e: 10, s: 20, v: 40 }])
    expect(fieldPoints(nodes, 'soil:soil_moisture_pct')).toEqual([{ e: 50, s: 60, v: 70 }])
    expect(fieldPoints(nodes, 'water:ph')).toEqual([])
  })

  test('field texture: value in range to R, NaN transparent', () => {
    const out = new Uint8Array(12)
    fieldTextureData(new Float32Array([0, 100, Number.NaN]), 0, 200, out)
    expect([...out]).toEqual([0, 0, 0, 255, 128, 0, 0, 255, 0, 0, 0, 0])
  })
})

describe('surface visibility', () => {
  test('without a live frame the surface still draws overlays, the grid and rings', () => {
    const st = createSurfaceState()
    expect(surfaceVisible(st, false)).toBe(false)
    st.grid = true
    expect(surfaceVisible(st, false)).toBe(true)
    st.grid = false
    st.overlay = { mode: OVERLAY_FIELD, texture: null, opacity: 1 }
    expect(surfaceVisible(st, false)).toBe(true)
  })

  test('the raster needs heights and the reality layer', () => {
    const st = createSurfaceState()
    st.hasHeights = true
    expect(surfaceVisible(st, true)).toBe(true)
    st.reality = false
    expect(surfaceVisible(st, true)).toBe(false)
  })
})

test('trees scale with canopy cover and turn brown at 15 % dieback', () => {
  expect(treeScale(undefined)).toBe(1)
  expect(treeScale({ canopy_pct: 0 })).toBeCloseTo(0.6)
  expect(treeScale({ canopy_pct: 100 })).toBeCloseTo(1.4)
  expect(treeCanopyColour({ dieback_pct: 14.9 })).toBe(HEALTHY_CANOPY)
  expect(treeCanopyColour({ dieback_pct: 15 })).toBe(DIEBACK_CANOPY)
})

test('risk columns rise with the risk score', () => {
  expect(tileHeight(90, false)).toBe(tileHeight(10, false))
  expect(tileHeight(100, true)).toBeGreaterThan(tileHeight(50, true))
})

test('alert markers: unacknowledged only, node alerts on the node, the worst severity wins', () => {
  const zones = [{ id: 'KSL-B3', label: 'B3', col: 1, row: 2 }]
  const nodes = [{ id: 'WQ-01', position: { e_m: 120, s_m: 230 } }] as Node[]
  const a = (id: string, sev: Alert['severity'], zone: string | null, nodeId: string | null, ack: string | null = null) =>
    ({ id, severity: sev, zone_id: zone, node_id: nodeId, acknowledged_at: ack, message: id }) as Alert
  const ms = alertMarkers(
    [a('1', 'warning', 'KSL-B3', null), a('2', 'critical', 'KSL-B3', null), a('3', 'info', 'KSL-B3', 'WQ-01'), a('4', 'critical', 'KSL-B3', null, 'x')],
    zones,
    nodes,
  )
  expect(ms).toHaveLength(2)
  expect(ms.find((m) => m.key === 'zone:KSL-B3')).toMatchObject({ severity: 'critical', count: 2, e: 150, s: 250 })
  expect(ms.find((m) => m.key === 'node:WQ-01')).toMatchObject({ severity: 'info', count: 1, e: 120, s: 230 })
})

test('assessment slice keeps the newest per zone, whatever the arrival order', () => {
  const as = (id: string, zone: string, at: string) => ({ id, zone_id: zone, at }) as Assessment
  const st = useAppStore.getState()
  st.setAssessments([as('a', 'KSL-B3', '2026-10-12T00:00:05Z'), as('b', 'KSL-B3', '2026-10-12T00:00:01Z'), as('c', 'KSL-A1', '2026-10-12T00:00:00Z')])
  expect(useAppStore.getState().assessments.byZone['KSL-B3']!.id).toBe('a')
  st.upsertAssessment(as('old', 'KSL-B3', '2026-10-12T00:00:02Z'))
  expect(useAppStore.getState().assessments.byZone['KSL-B3']!.id).toBe('a')
  st.upsertAssessment(as('new', 'KSL-B3', '2026-10-12T00:00:09Z'))
  expect(useAppStore.getState().assessments.byZone['KSL-B3']!.id).toBe('new')
  st.setAssessments([])
  expect(useAppStore.getState().assessments.byZone).toEqual({})
})
