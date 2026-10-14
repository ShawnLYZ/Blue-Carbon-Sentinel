import { describe, expect, test } from 'vitest'
import { PAGES, pageForHash, pageForKey, hashForPage } from './router'

describe('router (addendum I6)', () => {
  test('hash routes map to pages and keys 0–7', () => {
    expect(pageForHash('#/twin')).toBe('twin')
    expect(pageForKey('4')).toBe('twin')
    expect(pageForKey('0')).toBe('about')
  })

  test('every route, key and title from I6', () => {
    const rows = [
      ['#/command', 'command', '1', 'Command Center'],
      ['#/satellite', 'satellite', '2', 'Satellite Intelligence'],
      ['#/network', 'network', '3', 'Sentinel Network'],
      ['#/twin', 'twin', '4', 'Digital Twin'],
      ['#/time-travel', 'time-travel', '5', 'Time Travel & Restoration'],
      ['#/ledger', 'ledger', '6', 'Carbon Ledger'],
      ['#/system', 'system', '7', 'System'],
      ['#/about', 'about', '0', 'About'],
    ] as const
    for (const [hash, page, key, title] of rows) {
      expect(pageForHash(hash)).toBe(page)
      expect(pageForKey(key)).toBe(page)
      expect(hashForPage(page)).toBe(hash)
      expect(PAGES[page].title).toBe(title)
    }
  })

  test('unknown hashes fall back to the command center; unknown keys do nothing', () => {
    expect(pageForHash('')).toBe('command')
    expect(pageForHash('#/nope')).toBe('command')
    expect(pageForKey('8')).toBeNull()
    expect(pageForKey('x')).toBeNull()
  })
})
