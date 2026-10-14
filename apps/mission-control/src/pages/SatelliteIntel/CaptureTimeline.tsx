import { useState } from 'react'
import { Button, formatMYTDateTime, Panel } from '@bcs/ui'
import type { Capture, CaptureSummary } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { FLAG_TEXT, MediaImage, TRIGGER_TEXT, mediaUrl } from './shared'

function qualityNote(c: CaptureSummary): string {
  const q = c.quality
  const extra = `${q.motion ? ', motion' : ''}${q.exposure_locked ? '' : ', exposure not locked'}`
  return `sharpness ${q.sharpness.toFixed(0)}, mean ${q.mean.toFixed(0)}, clipped ${q.clipped_pct.toFixed(1)} %${extra}`
}

export interface CaptureTimelineProps {
  captures: CaptureSummary[] | null
  error: string | null
  details: Record<string, Capture>
  selectedId: string | null
  onSelect: (id: string) => void
  zoneLabel: (id: string) => string
}

/** Satellite passes: thumbnails, trigger icons, change badges and quality marks (US 56, US 58). */
export function CaptureTimeline({ captures, error, details, selectedId, onSelect, zoneLabel }: CaptureTimelineProps) {
  const [busy, setBusy] = useState(false)
  const [captureError, setCaptureError] = useState<string | null>(null)

  const captureNow = () => {
    setBusy(true)
    setCaptureError(null)
    api.POST('/api/v1/captures').then(
      (r) => {
        setBusy(false)
        if (r.error) setCaptureError(apiErrorText(r.error, 'The capture failed.'))
      },
      (e: unknown) => {
        setBusy(false)
        setCaptureError(networkErrorText(e))
      },
    )
  }

  return (
    <Panel
      title="Capture timeline"
      className="sat-timeline"
      actions={
        <Button onClick={captureNow} disabled={busy} className="panel-action">
          {busy ? 'Capturing…' : 'Capture now'}
        </Button>
      }
    >
      {captureError && (
        <p className="form-error" role="alert">
          {captureError}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {captures && captures.length === 0 && <p className="page__blurb">No captures yet.</p>}
      <ol className="timeline">
        {(captures ?? []).map((c) => {
          const t = TRIGGER_TEXT[c.trigger]
          const flagged = details[c.id]?.zone_metrics.filter((z) => (z.flags ?? []).length > 0) ?? []
          return (
            <li key={c.id}>
              <button
                type="button"
                className="timeline__item"
                data-testid="capture-thumb"
                aria-pressed={c.id === selectedId}
                onClick={() => onSelect(c.id)}
              >
                <MediaImage
                  className="timeline__thumb"
                  src={mediaUrl(c.id, 'image')}
                  alt={`Capture at ${formatMYTDateTime(c.taken_at, { seconds: true })}`}
                  label="image"
                  pruned={details[c.id]?.media_state === 'pruned'}
                />
                <span className="timeline__meta">
                  <span className="timeline__time bcs-mono">
                    <span className="timeline__trigger" title={t.label} aria-label={t.label}>
                      {t.glyph}
                    </span>{' '}
                    {formatMYTDateTime(c.taken_at, { seconds: true })}
                  </span>
                  <span className="timeline__badges">
                    {c.is_baseline && <span className="badge badge--baseline">baseline</span>}
                    {!c.evidence_grade && (
                      <span className="badge badge--quality" title={qualityNote(c)}>
                        not evidence-grade
                      </span>
                    )}
                    {c.flagged && flagged.length === 0 && <span className="badge badge--flag">flagged</span>}
                    {flagged.map((z) => (
                      <span key={z.zone_id} className="badge badge--flag" data-testid="capture-flag">
                        {zoneLabel(z.zone_id)} {(z.flags ?? []).map((f) => FLAG_TEXT[f.kind]).join(', ')}
                      </span>
                    ))}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}
