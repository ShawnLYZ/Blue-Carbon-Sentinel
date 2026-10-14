import { expect, test } from 'vitest'
import { siteBounds, terrainBaseMetres } from './terrainBase'

const box = { west: 101.0, east: 101.01, north: 3.4, south: 3.39 }

test('terrain base is the highest of the corners and centre plus 0.5 m', () => {
  const seen: [number, number][] = []
  const heights = [1, 2, 7.5, 3, 4]
  const map = { queryTerrainElevation: (p: [number, number]) => (seen.push(p), heights[seen.length - 1]!) }
  expect(terrainBaseMetres(map, box)).toBeCloseTo(8)
  expect(seen).toContainEqual([101.005, 3.395])
  expect(seen).toHaveLength(5)
})

test('no terrain loaded gives 0.5 m', () => {
  expect(terrainBaseMetres({ queryTerrainElevation: () => null }, box)).toBe(0.5)
})

test('site bounds come from the GeoJSON ring', () => {
  const ring = [[101, 3.4], [101.01, 3.4], [101.01, 3.39], [101, 3.39], [101, 3.4]]
  expect(siteBounds({ bounds: { type: 'Polygon', coordinates: [ring] } })).toEqual(box)
})
