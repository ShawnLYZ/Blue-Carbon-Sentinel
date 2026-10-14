import { useEffect } from 'react'
import { RealitySurfaceTextureHook } from '../twin/RealitySurfaceHook'
import { acquireLiveFeed } from '../twin/liveFeed'
import { CameraOfflineBanner } from './CameraOfflineBanner'
import { DepthModeBadge } from './DepthModeBadge'
import { ExaggerationControl } from './ExaggerationControl'
import { PAGE_PRESETS } from './presets'

/** Pages whose camera looks at the site (and therefore at the live surface). */
export function isSitePage(page: string): boolean {
  const preset = PAGE_PRESETS[page]
  return preset !== undefined && preset !== 'globe'
}

/**
 * Overlay on the map stage, independent of Mapbox and WebGL: the camera-offline banner, the depth
 * mode badge, the exaggeration control and the surface test hook. It holds the live feed open on the
 * site pages, so the last real frame is kept even when the map cannot start.
 */
export function StageHud({ page }: { page: string }) {
  const site = isSitePage(page)

  useEffect(() => (site ? acquireLiveFeed() : undefined), [site])

  return (
    <div className="stage-hud">
      <CameraOfflineBanner />
      <RealitySurfaceTextureHook />
      {site && (
        <div className="stage-hud__corner">
          <DepthModeBadge />
          <ExaggerationControl />
        </div>
      )}
    </div>
  )
}
