import { describe, expect, it } from 'vitest'
import { cooldownLeftS, keyStateText } from './aiStatusView'

const now = Date.parse('2026-10-12T02:00:00Z')

describe('cooldown text', () => {
  it('rounds up the seconds left', () => {
    expect(cooldownLeftS('2026-10-12T02:01:05Z', now)).toBe(65)
    expect(cooldownLeftS('2026-10-12T02:00:00.4Z', now)).toBe(1)
  })
  it('is zero when over, missing or invalid', () => {
    expect(cooldownLeftS('2026-10-12T01:59:00Z', now)).toBe(0)
    expect(cooldownLeftS(null, now)).toBe(0)
    expect(cooldownLeftS('nope', now)).toBe(0)
  })
  it('shows ok or minutes:seconds', () => {
    expect(keyStateText('ok', null, now)).toBe('ok')
    expect(keyStateText('cooldown', '2026-10-12T02:01:05Z', now)).toBe('cooldown 1:05')
    expect(keyStateText('cooldown', '2026-10-12T01:00:00Z', now)).toBe('ok')
  })
})
