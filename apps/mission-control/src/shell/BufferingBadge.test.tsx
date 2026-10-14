// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, test } from 'vitest'
import type { SystemStatus } from '@bcs/api-types'
import { BufferingBadge } from './BufferingBadge'
import { cloudChipValue } from './cloudSync'
import { useAppStore } from '../data/store'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Sync = SystemStatus['sync']
const sync = (state: Sync['state'], queue: number): Sync => ({ state, queue, media_queue: 0, lag_s: null, last_success_at: null })

function render(s: Sync): string {
  useAppStore.getState().setStatus({ sync: s } as unknown as SystemStatus)
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  act(() => root.render(<BufferingBadge />))
  const text = host.textContent ?? ''
  act(() => root.unmount())
  host.remove()
  return text
}

afterEach(() => useAppStore.setState((s) => ({ system: { ...s.system, status: null } })))

test('the badge shows only in the offline state (three consecutive failures, H6)', () => {
  expect(render(sync('online', 0))).toBe('')
  expect(render(sync('buffering', 4))).toBe('') // ordinary unsent work is not an outage
  expect(render(sync('offline', 4))).toBe('Buffering offline (4 queued)')
})

test('the cloud chip names the sync state', () => {
  expect(cloudChipValue(undefined)).toBe('—')
  expect(cloudChipValue('online')).toBe('Online')
  expect(cloudChipValue('buffering')).toBe('Buffering')
  expect(cloudChipValue('offline')).toBe('Offline')
})
