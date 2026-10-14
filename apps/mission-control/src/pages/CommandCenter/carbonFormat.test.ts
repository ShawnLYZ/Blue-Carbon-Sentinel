import { describe, expect, test } from 'vitest'
import { fmtTco2e } from './carbonFormat'

describe('fmtTco2e', () => {
  test('3 dp with thousands separators', () => {
    expect(fmtTco2e(0)).toBe('0.000')
    expect(fmtTco2e(1234.5)).toBe('1,234.500')
  })
  test('unknown is an em dash', () => {
    expect(fmtTco2e(null)).toBe('—')
    expect(fmtTco2e(undefined)).toBe('—')
    expect(fmtTco2e(NaN)).toBe('—')
  })
})
