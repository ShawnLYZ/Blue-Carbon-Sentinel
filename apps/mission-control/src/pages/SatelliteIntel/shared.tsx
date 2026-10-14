import { useEffect, useMemo, useState } from 'react'
import type { Capture, CaptureSummary, ZoneFlag } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { useSettledRev } from '../../data/hooks'
import { useAppStore } from '../../data/store'

export const MODEL_SCALE_TEXT = 'Model scale 1:500 (1 cm = 5 m)'
export const NDVI_CAPTION = 'NDVI-proxy (VARI) — RGB camera, no near-infrared; true NDVI needs Sentinel-2 B4/B8'
export const TIMELINE_LIMIT = 60

export const FLAG_TEXT: Record<ZoneFlag['kind'], string> = {
  canopy_loss: 'canopy loss',
  dieback: 'dieback',
  index_drop: 'index drop',
  discolouration: 'discolouration',
  new_growth: 'new growth',
}

export const TRIGGER_TEXT: Record<CaptureSummary['trigger'], { glyph: string; label: string }> = {
  interval: { glyph: '↻', label: 'interval capture' },
  change: { glyph: 'Δ', label: 'change capture' },
  manual: { glyph: '⊙', label: 'manual capture' },
}

export function mediaUrl(captureId: string, kind: 'image' | 'height' | 'classes' | 'ndvi'): string {
  return `/api/v1/media/captures/${encodeURIComponent(captureId)}/${kind}`
}

export function changeMapUrl(a: string, b: string): string {
  return `/api/v1/media/compare/${encodeURIComponent(a)}/${encodeURIComponent(b)}/change.png`
}

/** Zone id -> display label (e.g. KSL-B3 -> B3), from the site snapshot. */
export function useZoneLabels(): (zoneId: string) => string {
  const zones = useAppStore((s) => s.site.site?.zones)
  return useMemo(() => {
    const map = new Map((zones ?? []).map((z) => [z.id, z.label]))
    return (id: string) => map.get(id) ?? id.replace(/^[A-Z]+-/, '')
  }, [zones])
}

/** Why a media file could not be shown. */
export type MediaFailure = 'seeded' | 'pruned' | 'unavailable'

/**
 * Classifies a failed media response. Only a capture whose row has no media file at all (the
 * Ground Station answers 404 with `error.details.reason === "no_media"`, which in practice only
 * seeded test captures produce) counts as seeded; every other failure (file gone, 5xx, network) is "unavailable".
 */
export function classifyMediaFailure(status: number, body: unknown): MediaFailure {
  if (status !== 404) return 'unavailable'
  const err = (body as { error?: { code?: unknown; details?: { reason?: unknown } | null } } | null)?.error
  return err?.code === 'not_found' && err.details?.reason === 'no_media' ? 'seeded' : 'unavailable'
}

export function missingMediaText(label: string, failure: MediaFailure): string {
  if (failure === 'seeded') return `no ${label} (seeded)`
  if (failure === 'pruned') return `${label} pruned`
  return `no ${label}`
}

type MediaLoad = { src: string; url: string } | { src: string; failure: MediaFailure }

/**
 * A capture's media image, fetched as a blob so a failure can be told apart: a seeded capture with
 * no media, pruned media, or an unavailable file each get their own placeholder tile. Nothing is
 * ever substituted for the real image.
 */
export function MediaImage({
  src,
  alt,
  label,
  prefix = '',
  pruned = false,
  className,
}: {
  src: string | null
  alt: string
  /** What the file is, e.g. "image" or "NDVI-proxy map"; used in the placeholder text. */
  label: string
  prefix?: string
  /** The capture's media_state is "pruned" (known from the full capture): no request is made. */
  pruned?: boolean
  className?: string
}) {
  const [load, setLoad] = useState<MediaLoad | null>(null)
  const want = pruned ? null : src
  useEffect(() => {
    if (!want) return
    let live = true
    let url: string | null = null
    fetch(want).then(
      async (r) => {
        if (r.ok) {
          const blob = await r.blob()
          if (!live) return
          url = URL.createObjectURL(blob)
          setLoad({ src: want, url })
        } else {
          const body: unknown = await r.json().catch(() => null)
          if (live) setLoad({ src: want, failure: classifyMediaFailure(r.status, body) })
        }
      },
      () => {
        if (live) setLoad({ src: want, failure: 'unavailable' })
      },
    )
    return () => {
      live = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [want])

  const current = load && load.src === want ? load : null
  if (current && 'url' in current) {
    return <img className={className} src={current.url} alt={alt} draggable={false} />
  }
  const failure: MediaFailure | null = pruned ? 'pruned' : !src ? 'unavailable' : current ? current.failure : null
  const text = failure ? `${prefix}${missingMediaText(label, failure)}` : `${prefix}loading ${label}…`
  return (
    <span className={`media-missing ${className ?? ''}`.trim()} role="img" aria-label={text} data-failure={failure ?? 'loading'}>
      {text}
    </span>
  )
}

/** Newest-first capture summaries; refetched when capture, metric, flag or baseline events arrive. */
export function useCaptures(): { list: CaptureSummary[] | null; error: string | null } {
  const rev = useSettledRev('captures')
  const [list, setList] = useState<CaptureSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    api.GET('/api/v1/captures', { params: { query: { limit: TIMELINE_LIMIT } } }).then(
      (r) => {
        if (!live) return
        if (r.data) {
          setList(r.data)
          setError(null)
        } else setError(apiErrorText(r.error, 'Could not load captures.'))
      },
      (e: unknown) => {
        if (live) setError(networkErrorText(e))
      },
    )
    return () => {
      live = false
    }
  }, [rev])
  return { list, error }
}

export interface CaptureDetails {
  details: Record<string, Capture>
  /** Why a capture could not be loaded, by id. Failed ids are retried on the next capture event. */
  errors: Record<string, string>
}

/**
 * Full captures (zone metrics and flags) for `ids`. A capture's metrics never change, so each is
 * fetched until it loads once; a failed fetch is kept as an error and retried when the next
 * capture-related event (or resync) arrives.
 */
export function useCaptureDetails(ids: readonly string[]): CaptureDetails {
  const rev = useSettledRev('captures')
  const [details, setDetails] = useState<Record<string, Capture>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const key = ids.join(',')
  useEffect(() => {
    let live = true
    const missing = key ? key.split(',').filter((id) => !(id in details)) : []
    const fail = (id: string, message: string) => {
      if (live) setErrors((e) => ({ ...e, [id]: message }))
    }
    for (const id of missing) {
      api.GET('/api/v1/captures/{capture_id}', { params: { path: { capture_id: id } } }).then(
        (r) => {
          const cap = r.data
          if (!cap) return fail(id, apiErrorText(r.error, 'Could not load this capture.'))
          if (!live) return
          setDetails((d) => ({ ...d, [id]: cap }))
          setErrors((e) => {
            if (!(id in e)) return e
            const rest = { ...e }
            delete rest[id]
            return rest
          })
        },
        (e: unknown) => fail(id, networkErrorText(e)),
      )
    }
    return () => {
      live = false
    }
    // `details` is read only to skip known ids; depending on it would refetch in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, rev])
  return { details, errors }
}

export function fmt(v: number | null | undefined, digits = 1, unit = ''): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return `${v.toFixed(digits)}${unit ? ` ${unit}` : ''}`
}

export function signed(v: number, digits = 1): string {
  const s = v.toFixed(digits)
  return v > 0 ? `+${s}` : s.replace('-', '−')
}
