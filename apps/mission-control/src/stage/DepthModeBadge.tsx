import { useAppStore } from '../data/store'
import { useLiveMode } from '../twin/liveFeed'

export const DEPTH_MODE_LABELS = { depth: 'Depth AI', fallback: 'Colour-class fallback' } as const

/** Which reality-layer mode produced the surface: the newest frame's header, else the system status. */
export function DepthModeBadge() {
  const frameMode = useLiveMode()
  const statusMode = useAppStore((s) => s.system.status?.depth?.mode)
  const mode = frameMode ?? (statusMode === 'depth' || statusMode === 'fallback' ? statusMode : null)
  if (!mode) return null
  return (
    <span className="bcs-chip depth-badge" data-mode={mode} title="Reality-layer height source">
      {DEPTH_MODE_LABELS[mode]}
    </span>
  )
}
