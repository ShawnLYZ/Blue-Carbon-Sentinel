import { expect, test } from 'vitest'
import { idwGrid, maskFromClasses } from './idw'

test('idw honours mask and weights by distance', () => {
  const mask = new Uint8Array(64 * 64).fill(1); mask[0] = 0
  const g = idwGrid([{ e: 0, s: 0, v: 10 }, { e: 500, s: 500, v: 20 }], mask)
  expect(Number.isNaN(g[0])).toBe(true); expect(g[64 * 64 - 1]).toBeCloseTo(20, 0); expect(g[32 * 64 + 32]).toBeGreaterThan(14)
})

test('idw with no points is all NaN, and one point fills the mask with its value', () => {
  const mask = new Uint8Array(64 * 64).fill(1)
  expect(idwGrid([], mask).every((v) => Number.isNaN(v))).toBe(true)
  const g = idwGrid([{ e: 120, s: 300, v: 7.5 }], mask)
  expect(g.every((v) => v === 7.5)).toBe(true)
})

test('idw grid row 0 is the north edge (s = 0) and column 0 the west edge (e = 0)', () => {
  const mask = new Uint8Array(16 * 16).fill(1)
  const g = idwGrid([{ e: 0, s: 0, v: 0 }, { e: 500, s: 0, v: 100 }, { e: 0, s: 500, v: 50 }], mask, 16)
  expect(g[15]).toBeGreaterThan(80) // NE cell near the 100 point
  expect(g[15 * 16]).toBeGreaterThan(40) // SW cell near the 50 point
  expect(g[15 * 16]).toBeLessThan(60)
})

test('class masks keep water (code 2) or land (canopy, mud, other) cells', () => {
  // 2 x 2 class raster: canopy, water / mud, unclassified
  const classes = new Uint8Array([1, 2, 3, 0])
  expect([...maskFromClasses(classes, 2, 'water', 2)]).toEqual([0, 1, 0, 0])
  expect([...maskFromClasses(classes, 2, 'land', 2)]).toEqual([1, 0, 1, 0])
})
