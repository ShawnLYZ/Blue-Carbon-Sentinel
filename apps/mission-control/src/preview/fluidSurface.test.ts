import { expect, test } from 'vitest'
import { organicCrownGeometry } from '../twin/mangroveGeometry'
import { BASE_INPUTS, zoneRisks } from './scenarioRisk'
import { extentWeight, fluidRiskPixels, smoothRisk } from './fluidSurface'

test('risk blends continuously across the old square boundaries', () => {
  const zones = zoneRisks(null, BASE_INPUTS, {}, []).map((z, i) => ({ ...z, score: i % 2 ? 80 : 0 }))
  const a = smoothRisk(99.99, 150, zones)!, b = smoothRisk(100.01, 150, zones)!
  expect(Math.abs(a - b)).toBeLessThan(0.1)
  expect(a).toBeGreaterThan(0)
  expect(a).toBeLessThan(80)
  expect(smoothRisk(50, 50, zones)).toBe(0)
})
test('missing observations are grey and the display crop fades without changing coordinates', () => {
  const data = fluidRiskPixels([], null, true, 8)
  expect(data).toHaveLength(8 * 8 * 4)
  expect(extentWeight(0, 250)).toBe(0)
  expect(extentWeight(250, 250)).toBe(1)
  expect(smoothRisk(100, 100, [])).toBeNull()
})
test('broadleaf crown geometry includes normals and vertex shading and disposes cleanly', () => {
  const g = organicCrownGeometry()
  expect(g.getAttribute('position').count).toBeGreaterThan(100)
  expect(g.getAttribute('normal').count).toBe(g.getAttribute('position').count)
  expect(g.getAttribute('color').count).toBe(g.getAttribute('position').count)
  g.computeBoundingBox()
  expect(g.boundingBox!.max.x - g.boundingBox!.min.x).toBeGreaterThan(2)
  g.dispose()
})
