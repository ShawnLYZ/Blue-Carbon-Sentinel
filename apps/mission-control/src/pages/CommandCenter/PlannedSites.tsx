// Site markers of the Command Center (design §7, §26): Kuala Selangor is live, the planned sites are not yet
// monitored. A marker opens the rationale card. DOM buttons, so they work without the WebGL globe.
import { Chip, Panel } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { markerTestId, selectSite, toggleSite, useSiteSelection } from '../../data/siteSelection'
import { FlyIn } from './FlyIn'

export const PLANNED_STATUS = 'planned — not yet monitored'

export function PlannedSites() {
  const site = useAppStore((s) => s.site.site)
  const open = useSiteSelection((s) => s.selected)
  const mapMounted = useSiteSelection((s) => s.mapMounted)
  const planned = site?.planned_sites ?? []
  const chosen = planned.find((p) => p.id === open) ?? null
  return (
    <Panel title="Sites">
      <div className="site-markers" role="group" aria-label="Sites">
        <button type="button" className="site-marker site-marker--live" data-testid={markerTestId('KSL', 'list', mapMounted)} onClick={() => selectSite(null)} title="Monitored live">
          <span className="site-marker__dot" aria-hidden="true" />
          {site?.name ?? 'Kuala Selangor'} <span className="hint">live</span>
        </button>
        {planned.map((p) => (
          <button
            key={p.id}
            type="button"
            className="site-marker"
            data-testid={markerTestId(p.id, 'list', mapMounted)}
            aria-pressed={p.id === open}
            title={`${p.name}: ${PLANNED_STATUS}`}
            onClick={() => toggleSite(p.id)}
          >
            <span className="site-marker__dot" aria-hidden="true" />
            {p.name} <span className="hint">planned</span>
          </button>
        ))}
      </div>
      {chosen && (
        <article className="site-card" data-testid="site-card" aria-label={chosen.name}>
          <header className="site-card__head">
            <strong>{chosen.name}</strong>
            <button type="button" className="link-button" aria-label="Close site card" onClick={() => selectSite(null)}>
              ✕
            </button>
          </header>
          <div className="hint">{chosen.region}</div>
          <Chip color="#8a97a8">{PLANNED_STATUS}</Chip>
          <p>{chosen.rationale}</p>
        </article>
      )}
      <div className="site-markers__fly">
        <FlyIn />
      </div>
    </Panel>
  )
}
