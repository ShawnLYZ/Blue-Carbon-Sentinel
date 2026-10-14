import { describe, expect, test } from 'vitest'
import { COLUMN_MAX_M, columnHeight, columnScale } from './columnMath'

describe('carbon columns', () => {
  test('the largest zone fills the cap and others are proportional', () => {
    const s = columnScale([10, 5, 2.5])
    expect(columnHeight(10, s)).toBe(COLUMN_MAX_M)
    expect(columnHeight(5, s)).toBeCloseTo(30)
  })
  test('height is capped at 60 m and never negative', () => {
    expect(columnHeight(1000, 1)).toBe(60)
    expect(columnHeight(-3, 1)).toBe(0)
    expect(columnHeight(NaN, 1)).toBe(0)
  })
  test('scale falls back to 1 with no stock', () => {
    expect(columnScale([])).toBe(1)
    expect(columnScale([0, 0])).toBe(1)
  })
})
