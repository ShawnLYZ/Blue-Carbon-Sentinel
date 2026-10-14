import { useMemo } from 'react'
import { Panel, SourceChip } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { useZoneLabels } from './shared'
import { KIND_ICON, observationsByZone } from './zoneObservations'

/** VisionAnalyst observations per zone (from each zone's newest assessment): kind icon, confidence, text, source chip. */
export function Observations() {
  const assessments = useAppStore((s) => s.assessments.byZone)
  const zoneLabel = useZoneLabels()
  const zones = useMemo(() => observationsByZone(assessments), [assessments])
  const total = zones.reduce((n, z) => n + z.observations.length, 0)
  return (
    <Panel title="AI observations">
      <div data-testid="observations" data-count={total}>
        {zones.length === 0 ? (
          <p className="hint">No AI observations yet. They appear when a flagged zone is analysed on a camera capture.</p>
        ) : (
          zones.map((z) => (
            <section key={z.zoneId} className="obs-zone" data-testid={`observations-${z.zoneId}`}>
              <h3 className="obs-zone__title">
                {zoneLabel(z.zoneId)} <SourceChip tier={z.source.tier} model={z.source.model} cached={z.source.cached} />
              </h3>
              <ul className="obs-list">
                {z.observations.map((o, i) => (
                  <li key={i} className="obs-item" data-kind={o.kind}>
                    <span className="obs-item__icon" role="img" aria-label={o.kind.replace('_', ' ')}>
                      {KIND_ICON[o.kind] ?? '?'}
                    </span>
                    <span className="obs-item__text">{o.text}</span>
                    <span className="bcs-mono obs-item__conf" title="Confidence">
                      {Math.round(o.confidence * 100)}%
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </Panel>
  )
}
