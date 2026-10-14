import { useHasLiveFrame } from './liveFeed'

/**
 * Test hook for the reality surface (e2e): `data-has-frame` is "true" once a real /ws/live frame has
 * arrived. It lives in the DOM, outside the WebGL canvas and without three.js, so it renders even
 * when Mapbox or WebGL cannot start.
 */
export function RealitySurfaceTextureHook() {
  const has = useHasLiveFrame()
  return <span data-testid="reality-surface-texture" data-has-frame={has ? 'true' : 'false'} hidden />
}
