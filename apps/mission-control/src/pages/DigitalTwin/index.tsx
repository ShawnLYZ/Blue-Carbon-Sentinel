// Digital Twin (design §26): free orbit over the site (site-orbit preset) with the layer panel, a zone
// grid (each cell a DOM twin of the zone's 3D hit target, so zones can be picked without WebGL) and the
// zone card of the selected zone. The map layers themselves are mounted by MapStage (twin/TwinLayers).
import { useEffect } from 'react'
import { Panel, riskColor } from '@bcs/ui'
import { refreshZoneSummaries } from '../../data/live'
import { useSettledRev } from '../../data/hooks'
import { useAppStore } from '../../data/store'
import { LayerPanel } from './LayerPanel'
import { ZoneCard } from './ZoneCard'

function ZoneGrid() {
  const zones = useAppStore((s) => s.site.site?.zones)
  const byZone = useAppStore((s) => s.assessments.byZone)
  const selected = useAppStore((s) => s.ui.selectedZoneId)
  const selectZone = useAppStore((s) => s.selectZone)
  const sorted = [...(zones ?? [])].sort((a, b) => a.row - b.row || a.col - b.col)
  return (
    <Panel title="Zones">
      {sorted.length === 0 ? (
        <p className="hint">Loading the site…</p>
      ) : (
        <div className="zone-picker twin-zones" role="group" aria-label="Zones">
          {sorted.map((z) => {
            const a = byZone[z.id]
            return (
              <button
                key={z.id}
                type="button"
                className="zone-picker__cell"
                data-testid={`zone-hit-${z.id}`}
                aria-pressed={z.id === selected}
                title={a ? `${z.id}: ${a.risk_class} risk (${a.risk_score.toFixed(0)})` : `${z.id}: not assessed`}
                style={a ? { borderColor: riskColor(a.risk_class), boxShadow: `inset 0 -3px 0 ${riskColor(a.risk_class)}` } : undefined}
                onClick={() => selectZone(z.id === selected ? null : z.id)}
              >
                {z.label}
              </button>
            )
          })}
        </div>
      )}
    </Panel>
  )
}

export function DigitalTwin() {
  const zones = useAppStore((s) => s.site.site?.zones)
  const selected = useAppStore((s) => s.ui.selectedZoneId)
  const selectZone = useAppStore((s) => s.selectZone)
  const rev = useSettledRev('captures')
  const zone = zones?.find((z) => z.id === selected) ?? null

  // Zone metrics (tree scale and tint) follow capture events.
  useEffect(() => {
    refreshZoneSummaries().catch(() => undefined)
  }, [rev])

  return (
    <div className="twin-page">
      <div className="twin-page__col twin-page__left">
        <h1 className="page__title">Digital Twin</h1>
        <LayerPanel />
        <ZoneGrid />
      </div>
      <div className="twin-page__col twin-page__right">
        {zone ? (
          <ZoneCard key={zone.id} zone={zone} onClose={() => selectZone(null)} />
        ) : (
          <p className="hint twin-page__hint">Click a zone on the twin or in the zone grid for its card.</p>
        )}
      </div>
    </div>
  )
}
