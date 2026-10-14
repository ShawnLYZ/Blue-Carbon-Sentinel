// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, test } from 'vitest'
import type { ZoneMetrics } from '@bcs/api-types'
import { ZoneMetricsTable } from './ZoneMetricsTable'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const row = (zone_id: string, extra: Partial<ZoneMetrics> = {}): ZoneMetrics => ({
  zone_id,
  canopy_pct: 60,
  water_pct: 20,
  mud_pct: 15,
  other_pct: 5,
  dieback_pct: 2,
  new_growth_pct: 0,
  canopy_loss_pp: 0,
  vari_mean: 0.12,
  vari_p10: 0.05,
  vari_p90: 0.2,
  vari_drop: null,
  discolouration: null,
  flags: [],
  ...extra,
})

test('every metric is shown with its unit and flags read as words', () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() =>
    root.render(
      <ZoneMetricsTable
        metrics={[
          row('KSL-B3', { canopy_pct: 45, canopy_loss_pp: 15, flags: [{ kind: 'canopy_loss', value: 15, threshold: 10 }] }),
          row('KSL-A1'),
        ]}
        zoneLabel={(id) => id.replace('KSL-', '')}
      />,
    ),
  )
  const rows = [...host.querySelectorAll('tbody tr')]
  expect(rows.map((r) => r.querySelector('th')?.textContent)).toEqual(['A1', 'B3'])
  const b3 = rows[1]!.textContent ?? ''
  expect(b3).toContain('45.0 %')
  expect(b3).toContain('15.0 pp')
  expect(b3).toContain('0.120')
  expect(b3).toContain('—') // missing index values are a dash, never 0
  expect(host.querySelector('[data-testid="flag-badge-KSL-B3"]')?.textContent).toBe('canopy loss')
  expect(host.querySelector('[data-testid="flag-badge-KSL-A1"]')).toBeNull()
  const headers = [...host.querySelectorAll('thead th')].map((h) => h.textContent)
  expect(headers).toHaveLength(14) // zone + 12 ZoneMetrics values + flags
  act(() => root.unmount())
})
