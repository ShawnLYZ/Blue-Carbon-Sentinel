import { useEffect, useState } from 'react'
import { formatMYTDateTime, Panel } from '@bcs/ui'
import type { Capture, CaptureComparison, CaptureSummary } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { MediaImage, mediaUrl, signed } from './shared'

const TOP_CHANGES = 6

function CaptureSelect({
  label,
  value,
  captures,
  onChange,
}: {
  label: string
  value: string | null
  captures: CaptureSummary[]
  onChange: (id: string) => void
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {captures.map((c) => (
          <option key={c.id} value={c.id}>
            {formatMYTDateTime(c.taken_at, { seconds: true })}
            {c.is_baseline ? ' · baseline' : ''}
            {c.evidence_grade ? '' : ' · not evidence-grade'}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Before/after slider between any two captures, with the per-zone deltas (US 57). */
export function CompareSlider({
  captures,
  defaultBefore,
  defaultAfter,
  zoneLabel,
  details,
}: {
  captures: CaptureSummary[]
  /** Full captures already loaded (for media_state); missing entries are simply fetched as images. */
  details: Record<string, Capture>
  defaultBefore: string | null
  defaultAfter: string | null
  zoneLabel: (id: string) => string
}) {
  const [pickedA, setA] = useState<string | null>(null)
  const [pickedB, setB] = useState<string | null>(null)
  const [split, setSplit] = useState(50)
  const [cmp, setCmp] = useState<CaptureComparison | null>(null)
  const [error, setError] = useState<string | null>(null)

  const known = (id: string | null) => (id && captures.some((c) => c.id === id) ? id : null)
  const a = known(pickedA) ?? defaultBefore
  const b = known(pickedB) ?? defaultAfter

  useEffect(() => {
    if (!a || !b || a === b) return
    let live = true
    api.GET('/api/v1/captures/compare', { params: { query: { a, b } } }).then(
      (r) => {
        if (!live) return
        setCmp(r.data ?? null)
        setError(r.data ? null : apiErrorText(r.error, 'The comparison failed.'))
      },
      (e: unknown) => {
        if (live) setError(networkErrorText(e))
      },
    )
    return () => {
      live = false
    }
  }, [a, b])

  if (captures.length < 2) {
    return (
      <Panel title="Before / after">
        <p className="page__blurb">Needs at least two captures.</p>
      </Panel>
    )
  }

  const current = cmp && cmp.a === a && cmp.b === b ? cmp : null
  const changes = (current?.zones ?? [])
    .filter((z) => Math.abs(z.canopy_pp) >= 0.5 || Math.abs(z.dieback_pp) >= 0.5 || Math.abs(z.new_growth_pp) >= 0.5)
    .sort((x, y) => Math.abs(y.canopy_pp) - Math.abs(x.canopy_pp))
    .slice(0, TOP_CHANGES)

  return (
    <Panel title="Before / after">
      <div className="compare__pickers">
        <CaptureSelect label="Before" value={a} captures={captures} onChange={setA} />
        <CaptureSelect label="After" value={b} captures={captures} onChange={setB} />
      </div>
      <div className="compare__view" data-testid="compare-view">
        {a && <MediaImage className="compare__img" src={mediaUrl(a, 'image')} alt="Before" label="image" prefix="before: " pruned={details[a]?.media_state === 'pruned'} />}
        {b && (
          <div className="compare__after" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
            <MediaImage className="compare__img" src={mediaUrl(b, 'image')} alt="After" label="image" prefix="after: " pruned={details[b]?.media_state === 'pruned'} />
          </div>
        )}
        <div className="compare__divider" style={{ left: `${split}%` }} aria-hidden="true" />
      </div>
      <input
        className="compare__range"
        type="range"
        min={0}
        max={100}
        value={split}
        aria-label="Before/after split"
        onChange={(e) => setSplit(Number(e.target.value))}
      />
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {a === b ? (
        <p className="hint">Pick two different captures.</p>
      ) : current && changes.length === 0 ? (
        <p className="hint">No zone changed by 0.5 pp or more.</p>
      ) : (
        <ul className="compare__changes">
          {changes.map((z) => (
            <li key={z.zone_id}>
              <strong>{zoneLabel(z.zone_id)}</strong>
              <span className="bcs-mono">canopy {signed(z.canopy_pp)} pp</span>
              <span className="bcs-mono">dieback {signed(z.dieback_pp)} pp</span>
              <span className="bcs-mono">new growth {signed(z.new_growth_pp)} pp</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
