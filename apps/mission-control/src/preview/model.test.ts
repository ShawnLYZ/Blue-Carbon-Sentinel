import { describe, expect, test } from 'vitest'
import { buildTrees, DEFAULT_ENV, environmentShape } from './model'
import { bounds, KSL, reflectance, vegetationIndex, type Raster } from './satellite'

describe('satellite observation validity', () => {
  test('applies Sentinel reflectance offsets before calculating NDVI', () => {
    const asset = { href: '', 'raster:bands': [{ scale: 0.0001, offset: -0.1, nodata: 0 }] }
    expect(vegetationIndex(reflectance(2000, asset), reflectance(6000, asset), 4)).toBeCloseTo(2 / 3)
    expect(reflectance(0, asset)).toBeNull()
  })
  test('clouds, cloud shadows, water and missing pixels never become vegetation', () => {
    for (const scl of [0, 1, 2, 3, 6, 7, 8, 9, 10, 11]) expect(vegetationIndex(0.1, 0.6, scl)).toBeNull()
    expect(vegetationIndex(null, 0.6, 4)).toBeNull()
    expect(vegetationIndex(0, 0, 4)).toBeNull()
    expect(vegetationIndex(-0.1, 0.6, 4)).toBeNull()
  })
  test('study area remains centred on the requested coordinates', () => {
    const b = bounds(KSL)
    expect((b[0] + b[2]) / 2).toBeCloseTo(KSL.lng)
    expect((b[1] + b[3]) / 2).toBeCloseTo(KSL.lat)
  })
})
describe('procedural mangrove scenarios', () => {
  const raster: Raster = { width: 2, height: 2, rgb: new Uint8ClampedArray(16), valid: new Uint8Array([1, 0, 0, 0]), ndvi: new Float32Array([0.7, NaN, NaN, NaN]), clearPct: 25, vegetationPct: 25, meanNdvi: 0.7 }
  test('trees stay on usable vegetated pixels; fully cloudy sites generate no trees', () => {
    const trees = buildTrees(raster, DEFAULT_ENV)
    expect(trees.length).toBeGreaterThan(0)
    expect(trees.every(t => t.x < 0 && t.z < 0)).toBe(true)
    expect(buildTrees({ ...raster, valid: new Uint8Array(4) }, DEFAULT_ENV)).toHaveLength(0)
  })
  test('scenario is repeatable and higher stress reduces illustrative height', () => {
    expect(buildTrees(raster, DEFAULT_ENV)).toEqual(buildTrees(raster, DEFAULT_ENV))
    expect(environmentShape({ ...DEFAULT_ENV, salinity: 60, inundation: 100 }).height).toBeLessThan(environmentShape(DEFAULT_ENV).height)
    expect(environmentShape({ ...DEFAULT_ENV, age: 1 }).height).toBeLessThan(environmentShape(DEFAULT_ENV).height)
  })
})
