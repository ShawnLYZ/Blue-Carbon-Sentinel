// Preloads everything the two Time Travel surfaces draw, once per forecast (Review Focus 5): the real
// 2026 capture (image + height), the 20 code-only future textures and 20 heights (ruling R21), the ready
// illustrations and the base capture's class map (sapling placement). Scrubbing the slider then makes no
// request at all. A future file answers 404 until the FutureRenderer wrote it (a 404 for a ready forecast
// also starts a background render, ruling R22b); missing files are retried on a bounded back-off after
// the first load (about 1, 2, 4, 8, 16 s) and when the forecast's illustration.ready events arrive (the
// terminal signal per forecast, ruling R22c), never per frame or per slider move.
// Until then the surface shows the real capture. No three.js here: this module is in the main chunk.
import { useEffect, useRef, useState } from 'react'
import type { Forecast, Illustration } from '@bcs/api-types'
import { loadRasters } from '../../twin/captureRasters'
import { FIRST_YEAR, LAST_YEAR, type Scenario } from '../../lib/interp'
import { startBackoffRetry } from '../../lib/backoffRetry'

/** Height maps are resampled to the surface grid (one texel per vertex, twin/surfaceMaterial HEIGHT_GRID). */
export const HEIGHT_SIZE = 256
/** Colour textures larger than this are downscaled when decoded (GPU memory: 2 maps x 11 textures). */
export const TEXTURE_MAX = 1024

export const YEARS: number[] = Array.from({ length: LAST_YEAR - FIRST_YEAR + 1 }, (_, i) => FIRST_YEAR + i)
export const SCENARIOS: Scenario[] = ['without', 'with']

export function futureUrl(forecastId: string, scenario: Scenario, year: number, kind: 'texture' | 'height'): string {
  return `/api/v1/media/futures/${encodeURIComponent(forecastId)}/${scenario}/${year}/${kind}`
}

export function captureUrl(captureId: string, kind: 'image' | 'height'): string {
  return `/api/v1/media/captures/${encodeURIComponent(captureId)}/${kind}`
}

const BITMAP_OPTS: ImageBitmapOptions = { imageOrientation: 'none' as ImageOrientation, premultiplyAlpha: 'none', colorSpaceConversion: 'none' }

async function fetchBlob(url: string, signal: AbortSignal): Promise<Blob | null> {
  try {
    const r = await fetch(url, { signal })
    return r.ok ? await r.blob() : null // 404: not rendered yet (or pruned); never substituted
  } catch {
    return null
  }
}

async function decodeTexture(blob: Blob): Promise<ImageBitmap | null> {
  try {
    const bmp = await createImageBitmap(blob, BITMAP_OPTS)
    if (bmp.width <= TEXTURE_MAX && bmp.height <= TEXTURE_MAX) return bmp
    const scale = TEXTURE_MAX / Math.max(bmp.width, bmp.height)
    const small = await createImageBitmap(bmp, {
      ...BITMAP_OPTS,
      resizeWidth: Math.round(bmp.width * scale),
      resizeHeight: Math.round(bmp.height * scale),
      resizeQuality: 'high',
    })
    bmp.close()
    return small
  } catch {
    return null
  }
}

/** A grey height PNG (16-bit; the browser decodes 8 bits) as Float32 0..1, HEIGHT_SIZE square, row 0 north. */
async function decodeHeight(blob: Blob): Promise<Float32Array | null> {
  try {
    const bmp = await createImageBitmap(blob, {
      ...BITMAP_OPTS,
      resizeWidth: HEIGHT_SIZE,
      resizeHeight: HEIGHT_SIZE,
      resizeQuality: 'medium',
    })
    try {
      const canvas =
        typeof OffscreenCanvas !== 'undefined'
          ? new OffscreenCanvas(HEIGHT_SIZE, HEIGHT_SIZE)
          : Object.assign(document.createElement('canvas'), { width: HEIGHT_SIZE, height: HEIGHT_SIZE })
      const ctx = canvas.getContext('2d', { willReadFrequently: true }) as
        | OffscreenCanvasRenderingContext2D
        | CanvasRenderingContext2D
        | null
      if (!ctx) return null
      ctx.drawImage(bmp, 0, 0)
      const px = ctx.getImageData(0, 0, HEIGHT_SIZE, HEIGHT_SIZE).data
      const out = new Float32Array(HEIGHT_SIZE * HEIGHT_SIZE)
      for (let i = 0; i < out.length; i++) out[i] = px[4 * i]! / 255
      return out
    } finally {
      bmp.close()
    }
  } catch {
    return null
  }
}

/** The loaded media of one forecast. Mutable (filled as files arrive); `version` in the hook says when. */
export interface FuturesMedia {
  forecastId: string
  baseCaptureId: string
  capture: ImageBitmap | null
  captureHeight: Float32Array | null
  /** Per scenario, per year (index year - 2026). */
  textures: Record<Scenario, (ImageBitmap | null)[]>
  heights: Record<Scenario, (Float32Array | null)[]>
  /** Ready illustrations' images by `${scenario}:${year}`. */
  illustrations: Map<string, ImageBitmap>
  /** Base capture class map (RASTER_SIZE square, class codes), for sapling placement; null without one. */
  classes: Uint8Array | null
}

export interface PreloadState {
  media: FuturesMedia | null
  /** Bumps whenever a file arrives (consumers re-read `media`). */
  version: number
  /** Future files still missing after their last attempt. */
  missing: number
  /** Nothing is loading and either nothing is missing or the illustrations are terminal and the retry ran. */
  settled: boolean
}

interface Job {
  url: string
  apply: (blob: Blob) => Promise<boolean>
}

/**
 * Loads a forecast's media once. `illustrations` are the forecast's rows (refetched by the page on
 * illustration.ready); `retryRev` bumps on each settled batch of this forecast's illustration.ready
 * events and retries the missing future files then.
 */
export function useFuturesMedia(forecast: Forecast | null, illustrations: Illustration[], retryRev: number): PreloadState {
  const [version, setVersion] = useState(0)
  const [media, setMedia] = useState<FuturesMedia | null>(null)
  const missingJobs = useRef<Job[]>([])
  const inflight = useRef(0)
  const [missing, setMissing] = useState(0)
  const [busy, setBusy] = useState(false)
  const [terminalRetryDone, setTerminalRetryDone] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const requested = useRef(new Set<string>())
  const forecastId = forecast?.id ?? null
  const baseCaptureId = forecast?.base_capture_id ?? null

  const terminal = illustrations.length > 0 && illustrations.every((i) => i.status !== 'pending')
  const terminalRef = useRef(terminal)
  terminalRef.current = terminal

  // One batch of jobs; the failed ones are kept for a retry.
  const runJobs = useRef<(jobs: Job[], signal: AbortSignal) => Promise<void>>(async () => undefined)
  runJobs.current = async (jobs: Job[], signal: AbortSignal) => {
    inflight.current += 1
    setBusy(true)
    const failed: Job[] = []
    await Promise.all(
      jobs.map(async (j) => {
        const blob = await fetchBlob(j.url, signal)
        if (signal.aborted) return
        const ok = blob ? await j.apply(blob) : false
        if (!ok) failed.push(j)
        else setVersion((v) => v + 1)
      }),
    )
    if (signal.aborted) return
    missingJobs.current = [...missingJobs.current, ...failed]
    setMissing(missingJobs.current.length)
    inflight.current -= 1
    if (inflight.current === 0) setBusy(false)
  }

  /** Retries in flight (their jobs are out of `missingJobs` until they settle). */
  const retrying = useRef(0)
  const retry = useRef<(afterTerminal: boolean) => Promise<void>>(async () => undefined)
  retry.current = async (afterTerminal: boolean) => {
    const ctl = abort.current
    if (!ctl) return
    const jobs = missingJobs.current
    missingJobs.current = []
    if (jobs.length === 0) {
      if (afterTerminal) setTerminalRetryDone(true)
      return
    }
    retrying.current += 1
    try {
      await runJobs.current(jobs, ctl.signal)
    } finally {
      retrying.current -= 1
    }
    if (afterTerminal && !ctl.signal.aborted) setTerminalRetryDone(true)
  }

  // Initial load, once per forecast.
  useEffect(() => {
    if (!forecastId || !baseCaptureId) {
      setMedia(null)
      return
    }
    const ctl = new AbortController()
    abort.current = ctl
    missingJobs.current = []
    inflight.current = 0
    setMissing(0)
    setTerminalRetryDone(false)
    const m: FuturesMedia = {
      forecastId,
      baseCaptureId,
      capture: null,
      captureHeight: null,
      textures: { without: YEARS.map(() => null), with: YEARS.map(() => null) },
      heights: { without: YEARS.map(() => null), with: YEARS.map(() => null) },
      illustrations: new Map(),
      classes: null,
    }
    setMedia(m)
    const jobs: Job[] = [
      {
        url: captureUrl(baseCaptureId, 'image'),
        apply: async (b) => !!(m.capture = await decodeTexture(b)),
      },
      {
        url: captureUrl(baseCaptureId, 'height'),
        apply: async (b) => !!(m.captureHeight = await decodeHeight(b)),
      },
    ]
    for (const sc of SCENARIOS)
      YEARS.forEach((y, i) => {
        jobs.push({ url: futureUrl(forecastId, sc, y, 'texture'), apply: async (b) => !!(m.textures[sc][i] = await decodeTexture(b)) })
        jobs.push({ url: futureUrl(forecastId, sc, y, 'height'), apply: async (b) => !!(m.heights[sc][i] = await decodeHeight(b)) })
      })
    requested.current = new Set()
    retrying.current = 0
    // The repaints are written before any illustration runs, so a slow NVIDIA must not hold them back
    // (Review Focus 1): files missing after the first load are retried on a bounded back-off (about
    // 1, 2, 4, 8, 16 s), never per frame or per slider move; illustration.ready stays an extra trigger.
    let cancelBackoff = () => {}
    void runJobs.current(jobs, ctl.signal).then(() => {
      if (ctl.signal.aborted) return
      cancelBackoff = startBackoffRetry({
        isMissing: () => !ctl.signal.aborted && (missingJobs.current.length > 0 || retrying.current > 0),
        retry: () => retry.current(terminalRef.current),
      })
    })
    loadRasters(baseCaptureId).then(
      (r) => {
        if (ctl.signal.aborted) return
        m.classes = r.classes
        setVersion((v) => v + 1)
      },
      () => undefined,
    )
    return () => {
      ctl.abort()
      cancelBackoff()
      abort.current = null
      // Textures made from these bitmaps are already on the GPU; close them once the scene let go.
      setTimeout(() => {
        m.capture?.close()
        for (const sc of SCENARIOS) for (const b of m.textures[sc]) b?.close()
        for (const b of m.illustrations.values()) b.close()
      }, 2000)
    }
  }, [forecastId, baseCaptureId])

  // illustration.ready for this forecast: retry the missing future files (bounded by the events).
  useEffect(() => {
    if (retryRev > 0) void retry.current(terminalRef.current)
  }, [retryRev])

  // The illustrations were already terminal (events came before the page loaded the forecast, or were
  // missed): retry the missing files once.
  useEffect(() => {
    if (terminal && !busy && missing > 0 && !terminalRetryDone) void retry.current(true)
  }, [terminal, busy, missing, terminalRetryDone])

  // Ready illustrations: each image loads once.
  useEffect(() => {
    const ctl = abort.current
    if (!media || !ctl) return
    const jobs: Job[] = []
    for (const il of illustrations) {
      const key = `${il.scenario}:${il.year}`
      if (il.forecast_id !== media.forecastId || il.status !== 'ready' || !il.url || requested.current.has(key)) continue
      requested.current.add(key)
      jobs.push({
        url: il.url,
        apply: async (b) => {
          const bmp = await decodeTexture(b)
          if (bmp) media.illustrations.set(key, bmp)
          return !!bmp
        },
      })
    }
    if (jobs.length) void runJobs.current(jobs, ctl.signal)
  }, [illustrations, media])

  const settled = !!media && !busy && (missing === 0 || (terminal && terminalRetryDone))
  return { media, version, missing, settled }
}
