import { describe, expect, test } from 'vitest'
import { attributeStress, BASE_INPUTS, classify, zoneRisks } from './scenarioRisk'
import type { Raster } from './satellite'

const raster: Raster = { width: 50, height: 50, rgb: new Uint8ClampedArray(10000), ndvi: new Float32Array(2500).fill(0.7), valid: new Uint8Array(2500).fill(1), clearPct: 100, vegetationPct: 100, meanNdvi: 0.7 }
describe('satellite-guided scenario floor', () => {
  test('matches the configured sensor stress anchors and class boundaries', () => {
    expect(attributeStress('salinity', 45)).toBe(0.6)
    expect(attributeStress('oxygen', 2)).toBe(0.6)
    expect(attributeStress('turbidity', 300)).toBe(1)
    expect([29.9, 30, 60, 80].map(classify)).toEqual(['low', 'medium', 'high', 'critical'])
  })
  test('only a selected zone changes when its local input is changed', () => {
    const zones = zoneRisks(raster, BASE_INPUTS, { B3: { ...BASE_INPUTS, salinity: 60 } }, ['ndvi', 'salinity'])
    expect(zones.find(z => z.id === 'B3')?.risk).toBe('critical')
    expect(zones.filter(z => z.risk === 'critical')).toHaveLength(1)
    expect(zones.find(z => z.id === 'B3')).toMatchObject({ col: 1, row: 2, driver: 'salinity' })
  })
  test('disabling an attribute removes its stress; isolated floors exclude other attributes', () => {
    const inputs = { ...BASE_INPUTS, salinity: 60 }
    expect(zoneRisks(raster, inputs, {}, ['ndvi'])[0]?.risk).toBe('low')
    expect(zoneRisks(raster, inputs, {}, ['ndvi', 'salinity'], 'ndvi')[0]?.risk).toBe('low')
    expect(zoneRisks(raster, inputs, {}, [])[0]?.risk).toBe('unknown')
  })
  test('clouds remain unassessed even under extreme hypothetical inputs', () => {
    const cloudy = { ...raster, valid: new Uint8Array(2500) }
    expect(zoneRisks(cloudy, { ...BASE_INPUTS, salinity: 60 }, {}, ['salinity']).every(z => z.risk === 'unknown' && z.score === null)).toBe(true)
    expect(zoneRisks(null, BASE_INPUTS, {}, ['ndvi']).every(z => z.risk === 'unknown')).toBe(true)
  })
})
