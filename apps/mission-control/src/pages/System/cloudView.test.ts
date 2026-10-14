import { expect, test } from 'vitest'
import { DB_WARN_BYTES, lagText, pausedText, usageLine } from './cloudView'

test('usageLine shows megabytes against the limit and warns at the limit', () => {
  expect(usageLine(13_000_000, DB_WARN_BYTES)).toEqual({ text: '13 MB of 400 MB', level: 'ok' })
  expect(usageLine(450_000_000, DB_WARN_BYTES).level).toBe('warn')
  expect(usageLine(2_500_000, 800_000_000).text).toBe('2.5 MB of 800 MB')
})

test('unknown sizes say unknown instead of zero', () => {
  expect(usageLine(null, DB_WARN_BYTES)).toEqual({ text: 'unknown', level: 'unknown' })
  expect(usageLine(undefined, DB_WARN_BYTES).level).toBe('unknown')
})

test('lag and paused text', () => {
  expect(lagText(0.84)).toBe('0.8 s')
  expect(lagText(null)).toBe('not measured')
  expect(pausedText(null)).toBe('unknown')
  expect(pausedText(true)).toContain('paused')
  expect(pausedText(false)).toBe('running')
})
