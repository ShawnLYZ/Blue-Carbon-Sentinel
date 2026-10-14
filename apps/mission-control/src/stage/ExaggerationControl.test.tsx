// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const patch = vi.hoisted(() => vi.fn())
vi.mock('../data/client', () => ({ api: { PATCH: patch } }))

const { ExaggerationControl, PERSIST_DEBOUNCE_MS, createExaggerationSaver } = await import('./ExaggerationControl')
const { useAppStore } = await import('../data/store')

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const flushPromises = () => new Promise((r) => setTimeout(r, 0))

beforeEach(() => {
  patch.mockReset()
  patch.mockResolvedValue({ data: { vertical_exaggeration: 1 } })
  useAppStore.getState().setExaggeration(1)
})
afterEach(() => vi.useRealTimers())

test('the save is debounced and sends only the last value', () => {
  vi.useFakeTimers()
  const sent: number[] = []
  const saver = createExaggerationSaver({ patch: async (v) => (sent.push(v), {}), onError: () => undefined })
  saver.schedule(1.5)
  saver.schedule(2)
  vi.advanceTimersByTime(PERSIST_DEBOUNCE_MS - 1)
  expect(sent).toEqual([])
  vi.advanceTimersByTime(1)
  expect(sent).toEqual([2])
})

test('an HTTP error response (openapi-fetch resolves with error) is surfaced', async () => {
  const errors: string[] = []
  const saver = createExaggerationSaver({
    patch: async () => ({ error: { error: { code: 'validation_error', message: 'vertical_exaggeration must be <= 3' } } }),
    onError: (m) => errors.push(m),
  })
  saver.schedule(2)
  saver.flush()
  await flushPromises()
  expect(errors).toEqual(['vertical_exaggeration must be <= 3'])
})

test('a network failure is surfaced too', async () => {
  const errors: string[] = []
  const saver = createExaggerationSaver({ patch: () => Promise.reject(new Error('Failed to fetch')), onError: (m) => errors.push(m) })
  saver.schedule(2)
  saver.flush()
  await flushPromises()
  expect(errors).toEqual(['Failed to fetch'])
})

function mountControl() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const root = createRoot(el)
  act(() => root.render(<ExaggerationControl />))
  const input = el.querySelector('input[type="range"]') as HTMLInputElement
  const setValue = (v: string) =>
    act(() => {
      // React tracks the value property; set it through the native setter so onChange fires.
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, v)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  return { el, root, setValue }
}

test('unmounting with a pending save flushes the PATCH instead of dropping it', () => {
  vi.useFakeTimers()
  const { root, setValue } = mountControl()
  setValue('2.5')
  expect(useAppStore.getState().twin.exaggeration).toBe(2.5)
  expect(patch).not.toHaveBeenCalled()
  act(() => root.unmount()) // e.g. navigating to a non-site page within the debounce
  expect(patch).toHaveBeenCalledTimes(1)
  expect(patch).toHaveBeenCalledWith('/api/v1/system/settings', { body: { vertical_exaggeration: 2.5 } })
  vi.advanceTimersByTime(PERSIST_DEBOUNCE_MS * 2)
  expect(patch).toHaveBeenCalledTimes(1)
})

test('the control shows a failed save', async () => {
  patch.mockResolvedValue({ error: { error: { code: 'internal', message: 'settings store unavailable' } } })
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  const { el, root, setValue } = mountControl()
  setValue('2')
  await act(async () => {
    await new Promise((r) => setTimeout(r, PERSIST_DEBOUNCE_MS + 20))
  })
  expect(el.textContent).toContain('Not saved: settings store unavailable')
  expect(warn).toHaveBeenCalled()
  act(() => root.unmount())
  warn.mockRestore()
})
