// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Node } from '@bcs/api-types'

const post = vi.hoisted(() => vi.fn())
vi.mock('../../data/client', () => ({ api: { POST: post } }))

const { DeviceRegistrySection } = await import('./DeviceRegistrySection')
const { useAppStore } = await import('../../data/store')

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const flush = () => act(() => new Promise((r) => setTimeout(r, 0)))

const node = (id: string, source: Node['source']): Node => ({
  id,
  node_type: 'water_quality',
  source,
  position: { e_m: 1, s_m: 1, lat: 0, lng: 0, u_px: 0, v_px: 0 },
  zone_id: 'KSL-A1',
  status: 'online',
  covers: {},
  latest: null,
})

function mount() {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  act(() => root.render(<DeviceRegistrySection />))
  return { host, root }
}

function click(host: HTMLElement, text: string, within: Element | Document = host) {
  const b = [...within.querySelectorAll('button')].find((x) => x.textContent?.trim() === text)
  if (!b) throw new Error(`no button "${text}"`)
  act(() => b.click())
}

beforeEach(() => {
  post.mockReset()
  document.body.innerHTML = ''
  localStorage.clear()
  sessionStorage.clear()
})

test('every node row is labelled SIMULATED and the camera row is listed', () => {
  useAppStore.getState().setNodes([node('WQ-01', 'simulated'), node('SP-01', 'simulated')])
  const { host, root } = mount()
  const rows = host.querySelectorAll('[data-testid="registry-row"]')
  expect(rows).toHaveLength(2)
  rows.forEach((r) => expect(r.textContent).toContain('SIMULATED'))
  expect(host.querySelector('[data-testid="registry-camera"]')).not.toBeNull()
  act(() => root.unmount())
})

test('a hardware key is shown once with a copy button and never stored in the browser', async () => {
  useAppStore.getState().setNodes([node('WQ-05', 'hardware')])
  post.mockResolvedValue({ data: { key: 'k3y-secret-value' } })
  const before = JSON.stringify(useAppStore.getState())
  const { host, root } = mount()
  click(host, 'Regenerate key')
  click(host, 'Regenerate', document)
  await flush()
  expect(document.querySelector('[data-testid="key-value"]')?.textContent).toBe('k3y-secret-value')
  expect([...document.querySelectorAll('button')].some((b) => b.textContent === 'Copy')).toBe(true)
  expect(localStorage.length).toBe(0)
  expect(sessionStorage.length).toBe(0)
  expect(JSON.stringify(useAppStore.getState())).not.toContain('k3y-secret-value')
  expect(JSON.stringify(useAppStore.getState())).toBe(before)
  click(host, 'Done', document)
  expect(document.body.textContent).not.toContain('k3y-secret-value')
  act(() => root.unmount())
})

test('a simulated node shows the reprovisioned-by-simulator result and no key', async () => {
  useAppStore.getState().setNodes([node('WQ-01', 'simulated')])
  post.mockResolvedValue({ data: { key: null, reprovision: 'simulator' } })
  const { host, root } = mount()
  click(host, 'Regenerate key')
  click(host, 'Regenerate', document)
  await flush()
  expect(document.querySelector('[data-testid="key-reprovisioned"]')?.textContent).toContain('Reprovisioned by simulator')
  expect(document.querySelector('[data-testid="key-value"]')).toBeNull()
  act(() => root.unmount())
})
