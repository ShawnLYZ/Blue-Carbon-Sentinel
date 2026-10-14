import { describe, expect, test } from 'vitest'
import { capturesText, chainText, clock, confidenceText, sensorText, tco2e } from './format'

describe('ledger formats', () => {
  test('captures', () => expect(capturesText({ have: 2, need: 3, ok: false })).toBe('2/3 captures'))
  test('clock', () => {
    expect(clock(80)).toBe('1:20')
    expect(clock(120)).toBe('2:00')
    expect(clock(0)).toBe('0:00')
    expect(clock(-3)).toBe('0:00')
    expect(clock(59.6)).toBe('1:00')
  })
  test('sensors', () => expect(sensorText({ healthy_s: 80, need_s: 120, ok: false })).toBe('1:20 / 2:00 healthy'))
  test('confidence', () => {
    expect(confidenceText({ value: 0.83, need: 0.8, ok: true })).toBe('0.83 ≥ 0.80 ✓')
    expect(confidenceText({ value: 0.724, need: 0.8, ok: false })).toBe('0.72 < 0.80 ✗')
  })
  test('confidence never rounds across the threshold', () => {
    expect(confidenceText({ value: 0.7996, need: 0.8, ok: false })).toBe('0.79 < 0.80 ✗')
    expect(confidenceText({ value: 0.8, need: 0.8, ok: true })).toBe('0.80 ≥ 0.80 ✓')
    expect(confidenceText({ value: 0.29, need: 0.8, ok: false })).toBe('0.29 < 0.80 ✗')
    expect(confidenceText({ value: 0.999, need: 0.8, ok: true })).toBe('0.99 ≥ 0.80 ✓')
  })
  test('chain', () => {
    expect(chainText({ ok: true })).toBe('chain ✓')
    expect(chainText({ ok: false })).toBe('chain ✗')
  })
  test('tco2e', () => {
    expect(tco2e('1234.5')).toBe('1,234.500 tCO₂e')
    expect(tco2e(0)).toBe('0.000 tCO₂e')
  })
})
