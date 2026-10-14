import { useEffect, useRef, useState } from 'react'
import { Button, Panel } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { TreeCount, TreeMarkers } from './TreeMarkers'

/** The Console polls the latest site raster about once per second (addendum I2). */
export const LIVE_POLL_MS = 1000
const RASTER = 512
const GRID = 5

export const CAMERA_OFFLINE_PICKER_TEXT = 'Four-corner calibration needs a live camera frame; the camera is offline.'

/**
 * Polls /media/live/latest.jpg while the camera is online. Each frame is fetched as a blob, so the
 * previous real frame stays on screen until the next one has arrived. While the camera is offline
 * it is fetched once (the Ground Station keeps the last real raster, or answers 404) and then
 * stays frozen; nothing is substituted.
 */
function useLiveRaster(online: boolean): string | null {
  const [url, setUrl] = useState<string | null>(null)
  const latest = useRef<string | null>(null)
  latest.current = url
  useEffect(
    () => () => {
      if (latest.current) URL.revokeObjectURL(latest.current)
    },
    [],
  )
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const r = await fetch('/api/v1/media/live/latest.jpg', { cache: 'no-store' })
        if (r.ok && !stopped) {
          const next = URL.createObjectURL(await r.blob())
          if (stopped) URL.revokeObjectURL(next)
          else
            setUrl((prev) => {
              if (prev) URL.revokeObjectURL(prev)
              return next
            })
        }
      } catch {
        // network hiccup: keep the last frame and try again on the next tick
      }
      if (!stopped && online) timer = setTimeout(tick, LIVE_POLL_MS)
    }
    void tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [online])
  return url
}

/** Live north-up site raster with the zone grid of the active calibration drawn over it. */
export function LiveView({ onCalibrate }: { onCalibrate: () => void }) {
  const online = useAppStore((s) => s.camera.status?.online ?? false)
  const zones = useAppStore((s) => s.site.site?.zones)
  const frame = useLiveRaster(online)
  const cell = RASTER / GRID

  return (
    <Panel title="Live view">
      <div className="live-view" data-testid="live-view" data-online={online}>
        {frame ? (
          <img className="live-view__img" src={frame} alt="Live site raster, north up" draggable={false} />
        ) : (
          <span className="media-missing live-view__img live-view__empty">{online ? 'waiting for the first frame…' : 'no live frame: the camera is offline'}</span>
        )}
        <svg className="live-view__overlay" viewBox={`0 0 ${RASTER} ${RASTER}`} aria-hidden="true">
          {Array.from({ length: GRID + 1 }, (_, i) => (
            <g key={i}>
              <line x1={i * cell} y1={0} x2={i * cell} y2={RASTER} />
              <line x1={0} y1={i * cell} x2={RASTER} y2={i * cell} />
            </g>
          ))}
          {(zones ?? []).map((z) => (
            <text key={z.id} x={(z.col + 0.5) * cell} y={(z.row + 0.5) * cell}>
              {z.label}
            </text>
          ))}
          <TreeMarkers />
          <text className="live-view__north" x={RASTER - 18} y={30}>
            N↑
          </text>
        </svg>
        {frame && !online && <span className="live-view__frozen">frozen: last real frame</span>}
      </div>
      <div className="row-actions">
        <Button onClick={onCalibrate} disabled={!online}>
          Four-corner calibration…
        </Button>
        <TreeCount />
        <span className="hint">Overlay: zone grid of the active calibration, north up.</span>
      </div>
      {!online && <p className="hint">{CAMERA_OFFLINE_PICKER_TEXT}</p>}
    </Panel>
  )
}
