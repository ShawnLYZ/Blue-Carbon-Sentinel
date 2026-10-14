import { describe, expect, it } from 'vitest'
import type { Assessment } from '@bcs/api-types'
import { observationsByZone } from './zoneObservations'

const chip = { tier: 'rules', cached: false } as const
const base = { source: chip, observations_source: null, observations: [] }
const obs = (zone: string) => ({ kind: 'dieback' as const, confidence: 0.8, text: `thinning in ${zone}` })

const store = {
  'KSL-C3': { ...base, zone_id: 'KSL-C3', observations: [obs('C3')], observations_source: { tier: 'gemma_local', cached: false } },
  'KSL-B3': { ...base, zone_id: 'KSL-B3', observations: [obs('B3'), obs('B3')] },
  'KSL-A1': { ...base, zone_id: 'KSL-A1' },
} as unknown as Record<string, Assessment>

describe('observationsByZone', () => {
  it('keeps every zone that has observations, not just the latest one, sorted by zone', () => {
    const r = observationsByZone(store)
    expect(r.map((z) => z.zoneId)).toEqual(['KSL-B3', 'KSL-C3'])
    expect(r[0]!.observations).toHaveLength(2)
  })
  it('uses the vision chip when it differs, else the assessment chip', () => {
    const r = observationsByZone(store)
    expect(r[0]!.source.tier).toBe('rules')
    expect(r[1]!.source.tier).toBe('gemma_local')
  })
  it('is empty with no observations', () => {
    expect(observationsByZone({})).toEqual([])
  })
})
