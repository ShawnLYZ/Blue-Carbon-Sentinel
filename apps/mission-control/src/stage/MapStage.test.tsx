import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'

// The real map never starts in these tests: no mapbox-gl in node, and no store wiring needed.
const state = vi.hoisted(() => ({
  current: {
    system: { config: null as { mapbox_token: string } | null },
    site: { site: null },
    ui: { page: 'command' },
  },
}))
vi.mock('react-map-gl/mapbox', () => ({ Map: () => <div data-map="real" />, Source: () => null }))
vi.mock('mapbox-gl/dist/mapbox-gl.css', () => ({}))
vi.mock('./siteLayers', () => ({ SiteLayers: () => null }))
vi.mock('../data/store', () => {
  const useAppStore = (sel: (s: typeof state.current) => unknown) => sel(state.current)
  useAppStore.getState = () => state.current
  return { useAppStore }
})

const { MapStage, fatalMapError, mapFailureReason } = await import('./MapStage')

describe('map failure decision (Review Focus 4)', () => {
  test('401/403 and network errors are fatal before the map has loaded', () => {
    expect(fatalMapError({ status: 401 }, false)).toMatch(/rejected the access token \(HTTP 401\)/)
    expect(fatalMapError({ status: 403 }, false)).toMatch(/HTTP 403/)
    expect(fatalMapError({ message: 'Failed to fetch' }, false)).toMatch(/no network/)
  })

  test('after load, tile and fetch errors are ignored', () => {
    expect(fatalMapError({ status: 401 }, true)).toBeNull()
    expect(fatalMapError({ status: 403 }, true)).toBeNull()
    expect(fatalMapError({ message: 'Failed to fetch' }, true)).toBeNull()
  })

  test('other errors are never fatal', () => {
    expect(fatalMapError({ status: 404 }, false)).toBeNull()
    expect(fatalMapError({ status: 500, message: 'boom' }, false)).toBeNull()
    expect(fatalMapError(undefined, false)).toBeNull()
    expect(mapFailureReason({ status: 200, message: 'Failed to fetch' })).toBeNull()
  })
})

describe('MapStage render', () => {
  test('missing token shows the unavailable panel, not the map', () => {
    state.current.system.config = { mapbox_token: '' }
    const html = renderToStaticMarkup(<MapStage />)
    expect(html).toMatch(/Map unavailable: no Mapbox token is configured \(set BCS_MAPBOX_PUBLIC_TOKEN in .env\)/)
    expect(html).not.toContain('data-map')
  })

  test('with a token the map is mounted', () => {
    state.current.system.config = { mapbox_token: 'pk.test' }
    const html = renderToStaticMarkup(<MapStage />)
    expect(html).toContain('data-map="real"')
    expect(html).not.toMatch(/Map unavailable/)
  })

  test('hidden (Time Travel) keeps the map mounted inside a display:none container', () => {
    state.current.system.config = { mapbox_token: 'pk.test' }
    const html = renderToStaticMarkup(<MapStage hidden />)
    expect(html).toContain('data-map="real"')
    expect(html).toMatch(/data-testid="map-stage" data-hidden="true" style="display:none"/)
    expect(renderToStaticMarkup(<MapStage />)).toMatch(/data-hidden="false"(?! style)/)
  })

  test('before the config arrives the stage is busy', () => {
    state.current.system.config = null
    expect(renderToStaticMarkup(<MapStage />)).toContain('aria-busy="true"')
  })
})
