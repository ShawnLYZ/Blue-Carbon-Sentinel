// The latest capture's class map and NDVI-proxy map, decoded once per capture for the twin overlays
// (classes.png is 8-bit indexed with the F5 palette; ndvi.png is 16-bit grey, VARI mapped from [-1, 1]).
import { useEffect, useState } from 'react'
import { api } from '../data/client'
import { useSettledRev } from '../data/hooks'
import { CLASS_PALETTE } from './layers'

/** Rasters are resampled to this square size (row 0 north), enough for 100 m zones and 64 x 64 fields. */
export const RASTER_SIZE = 256

export interface CaptureRasters {
  /** Class code per pixel (0..4), RASTER_SIZE x RASTER_SIZE; null when the capture has no class map. */
  classes: Uint8Array | null
  /** VARI mapped to 0..255 per pixel; null when the capture has no NDVI-proxy map. */
  ndvi: Uint8Array | null
}

/** Nearest F5 palette entry of an RGB pixel. */
export function classOfRgb(r: number, g: number, b: number): number {
  let best = 0
  let bestD = Infinity
  for (const c of CLASS_PALETTE) {
    const d = (c.rgb[0] - r) ** 2 + (c.rgb[1] - g) ** 2 + (c.rgb[2] - b) ** 2
    if (d < bestD) {
      bestD = d
      best = c.code
    }
  }
  return best
}

async function decode(url: string): Promise<Uint8ClampedArray | null> {
  const r = await fetch(url)
  if (!r.ok) return null // seeded captures have no media; pruned media is gone
  const bmp = await createImageBitmap(await r.blob(), {
    premultiplyAlpha: 'none',
    colorSpaceConversion: 'none',
  })
  try {
    const canvas =
      typeof OffscreenCanvas !== 'undefined'
        ? new OffscreenCanvas(RASTER_SIZE, RASTER_SIZE)
        : Object.assign(document.createElement('canvas'), { width: RASTER_SIZE, height: RASTER_SIZE })
    const ctx = canvas.getContext('2d', { willReadFrequently: true }) as
      | OffscreenCanvasRenderingContext2D
      | CanvasRenderingContext2D
      | null
    if (!ctx) return null
    ctx.imageSmoothingEnabled = false // class codes must not blend
    ctx.drawImage(bmp, 0, 0, RASTER_SIZE, RASTER_SIZE)
    return ctx.getImageData(0, 0, RASTER_SIZE, RASTER_SIZE).data
  } finally {
    bmp.close()
  }
}

const cache = new Map<string, Promise<CaptureRasters>>()

/** Decodes a capture's class and NDVI-proxy maps (cached per capture; failures give nulls). */
export function loadRasters(captureId: string): Promise<CaptureRasters> {
  const hit = cache.get(captureId)
  if (hit) return hit
  const base = `/api/v1/media/captures/${encodeURIComponent(captureId)}`
  const p = Promise.all([decode(`${base}/classes`).catch(() => null), decode(`${base}/ndvi`).catch(() => null)]).then(
    ([cls, ndv]) => {
      const n = RASTER_SIZE * RASTER_SIZE
      let classes: Uint8Array | null = null
      if (cls) {
        classes = new Uint8Array(n)
        for (let i = 0; i < n; i++) classes[i] = classOfRgb(cls[4 * i]!, cls[4 * i + 1]!, cls[4 * i + 2]!)
      }
      let ndvi: Uint8Array | null = null
      if (ndv) {
        ndvi = new Uint8Array(n)
        for (let i = 0; i < n; i++) ndvi[i] = ndv[4 * i]!
      }
      return { classes, ndvi }
    },
  )
  cache.set(captureId, p)
  if (cache.size > 2 * RASTER_LOOKBACK) cache.delete(cache.keys().next().value!)
  return p
}

/** How many of the newest captures are tried for a class map (seeded captures have no media). */
export const RASTER_LOOKBACK = 5

/** The newest captures' ids, newest first, refetched when capture events settle; `undefined` while loading. */
export function useRecentCaptureIds(): string[] | undefined {
  const rev = useSettledRev('captures')
  const [ids, setIds] = useState<string[] | undefined>(undefined)
  useEffect(() => {
    let live = true
    api.GET('/api/v1/captures', { params: { query: { limit: RASTER_LOOKBACK } } }).then(
      (r) => {
        if (live && r.data) setIds(r.data.map((c) => c.id))
      },
      () => undefined,
    )
    return () => {
      live = false
    }
  }, [rev])
  return ids
}

/** The rasters of the newest capture that has a class map, or null when none of the recent ones has. */
export async function latestRasters(ids: string[]): Promise<CaptureRasters | null> {
  for (const id of ids) {
    const r = await loadRasters(id)
    if (r.classes) return r
  }
  return null
}

/** The latest class and NDVI-proxy maps; `loading` until the first lookup finishes. */
export function useLatestRasters(): { rasters: CaptureRasters | null; loading: boolean } {
  const ids = useRecentCaptureIds()
  const key = ids?.join(',')
  const [state, setState] = useState<{ key: string; rasters: CaptureRasters | null } | null>(null)
  useEffect(() => {
    if (key === undefined) return
    let live = true
    latestRasters(key ? key.split(',') : []).then(
      (r) => {
        if (live) setState({ key, rasters: r })
      },
      () => {
        if (live) setState({ key, rasters: null })
      },
    )
    return () => {
      live = false
    }
  }, [key])
  return { rasters: state?.rasters ?? null, loading: state?.key !== key }
}
