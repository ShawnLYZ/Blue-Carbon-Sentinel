import { describe, expect, test } from 'vitest'
import { BASE_INPUTS, attributeStress, zoneRisks } from './scenarioRisk'
import { paintSurface } from './surfacePaint'
import { exampleLayerData, registeredSiteMatches } from './layerData'
import { KSL, type Raster } from './satellite'

const raster: Raster = { width: 50, height: 50, rgb: new Uint8ClampedArray(10000), ndvi: new Float32Array(2500).fill(0.7), valid: new Uint8Array(2500).fill(1), classes: new Uint8Array(2500).fill(4), clearPct: 100, vegetationPct: 100, meanNdvi: 0.7 }
const zones = zoneRisks(raster, BASE_INPUTS, {}, ['ndvi'])
describe('restored surface and connected layers', () => {
  test('uses genuine satellite scene classes without claiming clouds are vegetation', () => {
    const classes = new Uint8Array(raster.classes!)
    classes[0] = 6; classes[1] = 9; classes[2] = 5
    const result = paintSurface({ ...raster, classes }, zones, 'classes', null, [], false)!
    expect([...result.rgb.slice(0, 12)]).toEqual([30, 100, 200, 255, 55, 65, 77, 255, 139, 101, 60, 255])
    expect(result.ndvi).toBe(raster.ndvi)
  })
  test('missing sensor readings remain grey instead of using scenario values', () => {
    const live = paintSurface(raster, zones, 'salinity', null, [], true)!
    const scenario = paintSurface(raster, zones, 'salinity', null, [], false)!
    expect([...live.rgb.slice(0, 4)]).toEqual([55, 65, 77, 255])
    expect([...scenario.rgb.slice(0, 4)]).not.toEqual([...live.rgb.slice(0, 4)])
  })
  test('pH and porewater salinity use configured stress anchors', () => {
    expect(attributeStress('ph', 6.5)).toBe(0.6)
    expect(attributeStress('ph', 7.8)).toBe(0)
    expect(attributeStress('soilSalinity', 60)).toBe(0.6)
    expect(attributeStress('soilMoisture', 0)).toBe(1)
    expect(attributeStress('soilMoisture', 60)).toBe(0)
  })
  test('never overlays another registered site on a custom satellite location', () => {
    expect(registeredSiteMatches(KSL, { lat: KSL.lat, lng: KSL.lng })).toBe(true)
    expect(registeredSiteMatches({ ...KSL, lat: 4 }, { lat: KSL.lat, lng: KSL.lng })).toBe(false)
    expect(registeredSiteMatches(KSL, null)).toBe(false)
  })
  test('example network and carbon are explicitly separated from observed data', () => {
    const data = exampleLayerData()
    expect(data.examples).toBe(true)
    expect(data.pins.every(p => p.source === 'EXAMPLE')).toBe(true)
    expect(Object.keys(data.carbon)).toHaveLength(25)
    expect(data.pulsing.every(id => data.pins.some(p => p.id === id))).toBe(true)
  })
})
