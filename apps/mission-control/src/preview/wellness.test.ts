import { expect, test } from 'vitest'
import { ATTRIBUTES, BASE_INPUTS, zoneRisks } from './scenarioRisk'
import { wellnessSummary } from './wellness'
import type { Raster } from './satellite'
const raster: Raster = { width: 50, height: 50, rgb: new Uint8ClampedArray(10000), ndvi: new Float32Array(2500).fill(0.7), valid: new Uint8Array(2500).fill(1), clearPct: 100, vegetationPct: 100, meanNdvi: 0.7 }
test('tile summary reports observed percentages and separates units from stress scores', () => {
  const zone = zoneRisks(raster, BASE_INPUTS, {}, [...ATTRIBUTES])[0]!
  const summary = wellnessSummary(zone, ATTRIBUTES, raster)
  expect(summary).toMatchObject({ clearPct: 100, vegetationPct: 100, score: 0, risk: 'low' })
  expect(summary.rows.find(r => r.key === 'ph')).toMatchObject({ value: '7.8 pH', pct: 0, source: 'Scenario' })
  expect(summary.rows.find(r => r.key === 'ndvi')?.source).toBe('Satellite')
})
test('a local pH change produces a specific concern without affecting another tile', () => {
  const zones = zoneRisks(raster, BASE_INPUTS, { C3: { ...BASE_INPUTS, ph: 9.5 } }, [...ATTRIBUTES])
  const bad = wellnessSummary(zones.find(z => z.id === 'C3')!, ATTRIBUTES, raster)
  const good = wellnessSummary(zones.find(z => z.id === 'B3')!, ATTRIBUTES, raster)
  expect(bad.score).toBe(100)
  expect(bad.concern).toContain('pH falls outside')
  expect(good.score).toBe(0)
})
test('missing data and disabled attributes never produce a reassuring health percentage', () => {
  const zone = zoneRisks(null, BASE_INPUTS, {}, ['ph'])[0]!
  const summary = wellnessSummary(zone, ['ph'], null)
  expect(summary.score).toBeNull()
  expect(summary.risk).toBe('unknown')
  expect(summary.concern).toContain('unassessed')
  expect(summary.rows.find(r => r.key === 'salinity')).toMatchObject({ enabled: false, pct: null })
})
