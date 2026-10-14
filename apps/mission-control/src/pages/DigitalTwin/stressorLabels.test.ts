import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'
import { STRESSOR_LABELS } from './ZoneCard'

/** The stressor keys of an assessment: the weight keys of config/risk.yaml (the engine's STRESSORS). */
function stressorKeys(): string[] {
  const text = readFileSync(new URL('../../../../../config/risk.yaml', import.meta.url), 'utf-8')
  const block = text.split(/\r?\n/).slice(1 + text.split(/\r?\n/).findIndex((l) => l.startsWith('weights:')))
  const keys: string[] = []
  for (const line of block) {
    const m = /^ {2}([a-z_]+):/.exec(line)
    if (!m) break
    keys.push(m[1])
  }
  return keys
}

describe('zone card stressor labels', () => {
  test('every backend stressor key has a label', () => {
    const keys = stressorKeys()
    expect(keys).toContain('porewater_salinity')
    expect(Object.keys(STRESSOR_LABELS).sort()).toEqual([...keys].sort())
    expect(STRESSOR_LABELS.porewater_salinity).toBe('Porewater salinity')
  })
})
