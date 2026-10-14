import { formatMYT } from '@bcs/ui'
import type { CameraStatus } from '@bcs/api-types'
import { useAppStore } from '../data/store'

/** "CAMERA OFFLINE since hh:mm:ss (MYT)", 24 h Malaysia time (design §6, constraints). */
export function offlineBannerText(sinceIso: string): string {
  return `CAMERA OFFLINE since ${formatMYT(sinceIso, { seconds: true }).replace(/ MYT$/, '')} (MYT)`
}

export function CameraOfflineBannerView({ status }: { status: Pick<CameraStatus, 'online' | 'since'> | null }) {
  if (!status || status.online) return null
  return (
    <div className="camera-offline" role="alert">
      <span className="camera-offline__dot" aria-hidden="true" />
      {offlineBannerText(status.since)}
    </div>
  )
}

/**
 * Shown while `camera.status.online` is false (initial state from GET /camera/status, then events).
 * The map keeps the last real frame underneath; nothing is substituted for it.
 */
export function CameraOfflineBanner() {
  const status = useAppStore((s) => s.camera.status)
  return <CameraOfflineBannerView status={status} />
}
