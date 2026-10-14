// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, test, vi } from 'vitest'
import { MediaImage, classifyMediaFailure, missingMediaText } from './shared'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const flush = () => act(() => new Promise<void>((r) => setTimeout(r, 0)))
const envelope = (code: string, message: string, reason?: string) => ({
  error: { code, message, details: reason ? { reason } : null },
})

afterEach(() => vi.unstubAllGlobals())

test('only a capture row with no media file counts as seeded', () => {
  expect(classifyMediaFailure(404, envelope('not_found', 'any wording at all', 'no_media'))).toBe('seeded')
  // The message text is not consulted any more.
  expect(classifyMediaFailure(404, envelope('not_found', 'Capture abc has no image file.'))).toBe('unavailable')
  expect(classifyMediaFailure(404, envelope('not_found', 'The image file of capture abc is no longer stored locally.'))).toBe(
    'unavailable',
  )
  expect(classifyMediaFailure(404, envelope('not_found', 'Capture abc not found.'))).toBe('unavailable')
  expect(classifyMediaFailure(500, envelope('internal_error', 'x', 'no_media'))).toBe('unavailable')
  expect(classifyMediaFailure(404, null)).toBe('unavailable')
})

test('placeholder texts', () => {
  expect(missingMediaText('image', 'seeded')).toBe('no image (seeded)')
  expect(missingMediaText('image', 'pruned')).toBe('image pruned')
  expect(missingMediaText('change map', 'unavailable')).toBe('no change map')
})

async function render(el: React.ReactElement, response: () => Promise<Response>) {
  const fetchMock = vi.fn(response)
  vi.stubGlobal('fetch', fetchMock)
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(el))
  await flush()
  await flush()
  return { host, root, fetchMock }
}

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))

test('a seeded capture shows "no image (seeded)" and no <img>', async () => {
  const { host, root } = await render(<MediaImage src="/m/1/image" alt="x" label="image" />, () =>
    json(404, envelope('not_found', 'Capture 1 has no image file.', 'no_media')),
  )
  expect(host.textContent).toBe('no image (seeded)')
  expect(host.querySelector('img')).toBeNull()
  act(() => root.unmount())
})

test('a server error never claims to be seeded', async () => {
  const { host, root } = await render(<MediaImage src="/m/1/image" alt="x" label="image" />, () =>
    json(500, envelope('internal_error', 'boom')),
  )
  expect(host.textContent).toBe('no image')
  act(() => root.unmount())
})

test('pruned media shows "image pruned" without a request', async () => {
  const { host, root, fetchMock } = await render(<MediaImage src="/m/1/image" alt="x" label="image" pruned />, () =>
    json(200, {}),
  )
  expect(host.textContent).toBe('image pruned')
  expect(fetchMock).not.toHaveBeenCalled()
  act(() => root.unmount())
})
