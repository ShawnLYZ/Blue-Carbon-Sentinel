import { formatMYTDateTime, Panel } from '@bcs/ui'
import type { Capture, CaptureSummary } from '@bcs/api-types'
import { MediaImage, NDVI_CAPTION, changeMapUrl, mediaUrl } from './shared'
import { ZoneMetricsTable } from './ZoneMetricsTable'

export interface NdviPanelProps {
  /** The capture being inspected (summary from the timeline). */
  capture: CaptureSummary | null
  /** Its full record (zone metrics); null while loading. */
  detail: Capture | null
  /** Why the full record could not be loaded (retried on the next capture event). */
  detailError: string | null
  baseline: CaptureSummary | null
  zoneLabel: (id: string) => string
}

/** NDVI-proxy map, change map against the baseline, and the zone metrics table (US 49-52). */
export function NdviPanel({ capture, detail, detailError, baseline, zoneLabel }: NdviPanelProps) {
  const when = capture ? formatMYTDateTime(capture.taken_at, { seconds: true }) : null
  const vsBaseline = capture && baseline && baseline.id !== capture.id ? baseline : null
  return (
    <Panel title="Vegetation and change" className="sat-ndvi">
      {!capture ? (
        <p className="page__blurb">No capture selected.</p>
      ) : (
        <>
          <p className="hint">
            Capture <span className="bcs-mono">{when}</span>
            {capture.is_baseline ? ' (baseline)' : ''}
          </p>
          <div className="map-pair">
            <figure className="map-figure">
              <MediaImage
                className="map-figure__img"
                src={mediaUrl(capture.id, 'ndvi')}
                alt="NDVI-proxy map"
                label="NDVI-proxy map"
                pruned={detail?.id === capture.id && detail.media_state === 'pruned'}
              />
              <figcaption className="ndvi-caption">{NDVI_CAPTION}</figcaption>
            </figure>
            <figure className="map-figure">
              {vsBaseline ? (
                <MediaImage
                  className="map-figure__img"
                  src={changeMapUrl(vsBaseline.id, capture.id)}
                  alt="Change map against the baseline"
                  label="change map"
                />
              ) : (
                <span className="media-missing map-figure__img">
                  {baseline ? 'this capture is the baseline' : 'no baseline yet'}
                </span>
              )}
              <figcaption>Change map against the baseline</figcaption>
            </figure>
          </div>
          {detail && detail.id === capture.id ? (
            <ZoneMetricsTable metrics={detail.zone_metrics} zoneLabel={zoneLabel} />
          ) : detailError ? (
            <p className="form-error" role="alert">
              Zone metrics unavailable: {detailError} It is retried on the next capture event.
            </p>
          ) : (
            <p className="hint">Loading zone metrics…</p>
          )}
        </>
      )}
    </Panel>
  )
}
