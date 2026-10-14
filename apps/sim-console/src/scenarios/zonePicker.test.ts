import { describe, expect, test } from 'vitest'
import { cellForLabel, labelForCell, ZONE_LABELS } from './zonePicker'

describe('zone picker', () => {
  test('zone picker maps cell clicks to labels A1–E5', () => {
    expect(labelForCell(1, 2)).toBe('B3')
    expect(labelForCell(4, 4)).toBe('E5')
    expect(labelForCell(0, 0)).toBe('A1')
  })

  test('labels round-trip to cells, and the KSL- prefix is accepted', () => {
    expect(cellForLabel('B3')).toEqual({ col: 1, row: 2 })
    expect(cellForLabel('KSL-E5')).toEqual({ col: 4, row: 4 })
    expect(cellForLabel('F1')).toBeNull()
  })

  test('the picker lists 25 zones row by row', () => {
    expect(ZONE_LABELS).toHaveLength(25)
    expect(ZONE_LABELS.slice(0, 5)).toEqual(['A1', 'B1', 'C1', 'D1', 'E1'])
    expect(ZONE_LABELS[24]).toBe('E5')
  })

  test('out-of-grid cells are rejected', () => {
    expect(() => labelForCell(5, 0)).toThrow()
    expect(() => labelForCell(0, -1)).toThrow()
  })
})
