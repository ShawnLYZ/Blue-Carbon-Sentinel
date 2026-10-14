import { expect, test } from 'vitest'
import type { Node } from '@bcs/api-types'
import { OFFLINE_COLOUR, TYPE_COLOUR } from '../data/network'
import { ringsFromPins } from './CoverageRings'
import { layerSignature, pinsFromNodes } from './NodePins'
import { FRAGMENT, MAX_RINGS, createRingBuffers, createSurfaceMaterial, packRings } from './surfaceMaterial'
import { PULSE_PERIOD_MS, pulseOpacity, pulsePhase, pulseRadius, pulsingSignature } from './TaskingPulses'

const node = (id: string, node_type: Node['node_type'], status: Node['status'] = 'online', e = 100, s = 200): Node => ({
  id,
  node_type,
  source: 'simulated',
  position: { e_m: e, s_m: s, lat: 0, lng: 0, u_px: 0, v_px: 0 },
  zone_id: 'KSL-B3',
  status,
  covers: {},
  latest: null,
})

test('pins: one per active node, coloured by type, offline nodes grey', () => {
  const pins = pinsFromNodes([
    node('WQ-01', 'water_quality'),
    node('SP-01', 'soil_probe', 'offline'),
    node('TG-01', 'tide_gauge'),
    node('WQ-09', 'water_quality', 'decommissioned'),
  ])
  expect(pins.map((p) => p.id)).toEqual(['WQ-01', 'SP-01', 'TG-01'])
  expect(pins[0]!.colour).toBe(TYPE_COLOUR.water_quality)
  expect(pins[1]!.colour).toBe(OFFLINE_COLOUR)
  expect(pins[2]!.colour).toBe(TYPE_COLOUR.tide_gauge)
})

test('the layer signature ignores samples and moves only with position, type or online state', () => {
  const a = node('WQ-01', 'water_quality')
  const sampled: Node = { ...a, last_seen_at: 'now', latest: { sampled_at: 'now', readings: { ph: 7 }, health: { battery_pct: 1, rssi_dbm: -1, uptime_s: 1, fw_version: 'x' }, flags: [], late: false } }
  expect(layerSignature([sampled])).toBe(layerSignature([a]))
  expect(layerSignature([{ ...a, status: 'offline' }])).not.toBe(layerSignature([a]))
  expect(layerSignature([{ ...a, position: { ...a.position, e_m: 101 } }])).not.toBe(layerSignature([a]))
})

test('coverage rings: WQ 150 m, SP 100 m, none for the site-wide tide gauge', () => {
  const rings = ringsFromPins(pinsFromNodes([node('WQ-01', 'water_quality'), node('SP-01', 'soil_probe'), node('TG-01', 'tide_gauge')]))
  expect(rings.map((r) => r.radius)).toEqual([150, 100])
})

test('rings pack into the shader uniform arrays, capped at MAX_RINGS', () => {
  const buf = createRingBuffers()
  const many = Array.from({ length: 20 }, (_, i) => ({ e: i, s: 2 * i, radius: 150, colour: '#ff0000' }))
  expect(packRings(buf, many)).toBe(MAX_RINGS)
  expect(buf.count).toBe(16)
  expect([buf.centres[2], buf.centres[3]]).toEqual([1, 2])
  expect([buf.colours[0], buf.colours[1], buf.colours[2]]).toEqual([1, 0, 0])
  packRings(buf, many.slice(0, 2))
  expect(buf.count).toBe(2)
  expect(buf.radii[2]).toBe(0)
})

test('the surface shader declares the ring uniforms with a 16-ring #define and shares the buffers', () => {
  expect(FRAGMENT).toContain('#define MAX_RINGS 16')
  expect(FRAGMENT).toContain('uniform vec2 uRingCentres[MAX_RINGS]')
  expect(FRAGMENT).toContain('uniform float uRingRadii[MAX_RINGS]')
  const rings = createRingBuffers()
  const res = createSurfaceMaterial(new Float32Array(256 * 256), rings)
  expect(res.material.uniforms.uRingCentres.value).toBe(rings.centres)
  expect(res.material.uniforms.uRingRadii.value).toBe(rings.radii)
  res.dispose()
})

test('a pulse expands and fades over 1.5 s', () => {
  expect(PULSE_PERIOD_MS).toBe(1500)
  expect(pulsePhase(0)).toBe(0)
  expect(pulsePhase(750)).toBeCloseTo(0.5)
  expect(pulsePhase(1500)).toBe(0)
  expect(pulseRadius(0.9)).toBeGreaterThan(pulseRadius(0.1))
  expect(pulseOpacity(0.9)).toBeLessThan(pulseOpacity(0.1))
})

test('only nodes held by open tasks pulse', () => {
  const base = { zone_id: 'KSL-B3', trigger: 'manual', reason: '', duration_s: 180, created_at: '', updated_at: '', expires_at: '', commands: [], timeline: [] }
  expect(
    pulsingSignature([
      { ...base, id: 'a', status: 'active', node_ids: ['WQ-01', 'TG-01'] },
      { ...base, id: 'b', status: 'cancelled', node_ids: ['SP-01'] },
    ]),
  ).toBe('TG-01,WQ-01')
  expect(pulsingSignature([{ ...base, id: 'b', status: 'completed', node_ids: ['SP-01'] }])).toBe('')
})
