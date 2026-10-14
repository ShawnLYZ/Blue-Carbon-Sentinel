import { expect, test } from 'vitest'
import { formatMYT } from './time'

test('formatMYT converts UTC to Kuala Lumpur time', () => {
  expect(formatMYT('2026-10-16T03:04:05.123Z', { seconds: true })).toBe('11:04:05 MYT')
})

test('formatMYT omits seconds by default', () => {
  expect(formatMYT('2026-10-16T03:04:05.123Z')).toBe('11:04 MYT')
})

test('formatMYT rolls over the date at UTC+8', () => {
  expect(formatMYT('2026-10-16T17:30:00.000Z')).toBe('01:30 MYT')
})
