import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import type { CoverageGap, ZoneEligibility } from '@bcs/api-types'
import { EligibilityTracker } from './EligibilityTracker'
import { gapText, isNoCoverage } from './format'

const zone = (reason: string | null, ok = false): ZoneEligibility => ({
  zone_id: 'KSL-A3',
  plan_id: 'p1',
  camera: { have: 1, need: 3, ok: false },
  sensors: { healthy_s: 0, need_s: 120, ok, reason },
  confidence: { value: 0.7, need: 0.8, ok: false },
  chain: { ok: true },
  eligible: false,
})
const gap = (zone_id: string): CoverageGap => ({
  id: `gap-${zone_id}`, zone_id, node_type: 'soil_probe', e_m: 40.4, s_m: 25, lat: 0, lng: 0, u_px: 0, v_px: 0,
  newly_covered: [], reason: 'uncovered flagged zone',
})
const render = (z: ZoneEligibility, gaps: CoverageGap[]) =>
  renderToStaticMarkup(<EligibilityTracker zones={[z]} zoneLabel={(id) => id} gaps={gaps} />)

describe('no-coverage eligibility', () => {
  test('detects the reason only when the sensor rule fails', () => {
    expect(isNoCoverage(zone('no coverage').sensors)).toBe(true)
    expect(isNoCoverage(zone('node WQ-01 offline').sensors)).toBe(false)
    expect(isNoCoverage(zone(null).sensors)).toBe(false)
  })
  test('picks the suggestion of that zone only', () => {
    expect(gapText([gap('KSL-B1')], 'KSL-A3')).toBeNull()
    expect(gapText([gap('KSL-B1'), gap('KSL-A3')], 'KSL-A3')).toBe('Suggested: add a soil probe at e 40 m, s 25 m (uncovered flagged zone)')
  })
  test('card shows reason, suggestion and link', () => {
    const html = render(zone('no coverage'), [gap('KSL-A3')])
    expect(html).toContain('no coverage')
    expect(html).toContain('coverage-gap-suggestion')
    expect(html).toContain('add a soil probe')
    expect(html).toContain('href="#/network"')
  })
  test('other reasons show no gap link', () => {
    const html = render(zone('node WQ-01 offline'), [gap('KSL-A3')])
    expect(html).not.toContain('coverage-gap')
  })
})

describe('other blocking reasons', () => {
  test('the card shows the zone reason', () => {
    const html = render({ ...zone(null, true), reason: 'expected recovery unavailable: no 2026/2027 forecast canopy for the zone' }, [])
    expect(html).toContain('data-testid="eligibility-blocked"')
    expect(html).toContain('expected recovery unavailable')
  })
  test('no reason, no line', () => {
    expect(render({ ...zone(null, true), reason: null }, [])).not.toContain('eligibility-blocked')
    expect(render(zone(null, true), [])).not.toContain('eligibility-blocked')
  })
})
