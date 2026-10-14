import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import type { LedgerRecord } from '@bcs/api-types'
import { RecordDetail } from './RecordDetail'

const METHOD = 'aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified'
const record: LedgerRecord = {
  chain_index: 0,
  record_id: 'BC-2026-00001',
  type: 'projected',
  created_at: '2026-10-16T03:04:05.123Z',
  quantity_tco2e: '12.345',
  content: { method_note: METHOD, zone_ids: ['KSL-B3'] },
  canonical: '{}',
  previous_hash: '0'.repeat(64),
  hash: 'a'.repeat(64),
  link_ok: true,
}

describe('record detail', () => {
  test('shows the methodology note in the detail list, outside the canonical JSON', () => {
    const html = renderToStaticMarkup(<RecordDetail record={record} zoneLabel={(id) => id} />)
    const list = html.slice(0, html.indexOf('ledger-canonical'))
    expect(list).toContain('data-testid="record-method-note"')
    expect(list).toContain(METHOD)
  })
})
