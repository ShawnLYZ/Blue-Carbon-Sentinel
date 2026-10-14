import type { ZoneMetrics } from '@bcs/api-types'
import { FLAG_TEXT, fmt } from './shared'

/** Every ZoneMetrics field of one capture, with units (US 52). */
export function ZoneMetricsTable({ metrics, zoneLabel }: { metrics: ZoneMetrics[]; zoneLabel: (id: string) => string }) {
  const rows = [...metrics].sort((a, b) => zoneLabel(a.zone_id).localeCompare(zoneLabel(b.zone_id)))
  return (
    <div className="metrics-table__wrap">
      <table className="metrics-table">
        <thead>
          <tr>
            <th scope="col">Zone</th>
            <th scope="col">Canopy %</th>
            <th scope="col">Canopy loss pp</th>
            <th scope="col">Water %</th>
            <th scope="col">Mud %</th>
            <th scope="col">Other %</th>
            <th scope="col">Dieback %</th>
            <th scope="col">New growth %</th>
            <th scope="col">VARI mean (index)</th>
            <th scope="col">VARI p10 (index)</th>
            <th scope="col">VARI p90 (index)</th>
            <th scope="col">VARI drop (index)</th>
            <th scope="col">Discolouration (index)</th>
            <th scope="col">Flags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => {
            const flags = m.flags ?? []
            return (
              <tr key={m.zone_id} data-flagged={flags.length > 0}>
                <th scope="row">{zoneLabel(m.zone_id)}</th>
                <td>{fmt(m.canopy_pct, 1, '%')}</td>
                <td>{fmt(m.canopy_loss_pp, 1, 'pp')}</td>
                <td>{fmt(m.water_pct, 1, '%')}</td>
                <td>{fmt(m.mud_pct, 1, '%')}</td>
                <td>{fmt(m.other_pct, 1, '%')}</td>
                <td>{fmt(m.dieback_pct, 1, '%')}</td>
                <td>{fmt(m.new_growth_pct, 1, '%')}</td>
                <td>{fmt(m.vari_mean, 3)}</td>
                <td>{fmt(m.vari_p10, 3)}</td>
                <td>{fmt(m.vari_p90, 3)}</td>
                <td>{fmt(m.vari_drop, 3)}</td>
                <td>{fmt(m.discolouration, 3)}</td>
                <td>
                  {flags.length > 0 && (
                    <span
                      className="badge badge--flag"
                      data-testid={`flag-badge-${m.zone_id}`}
                      title={flags.map((f) => `${FLAG_TEXT[f.kind]}: ${f.value.toFixed(2)} (threshold ${f.threshold})`).join('; ')}
                    >
                      {flags.map((f) => FLAG_TEXT[f.kind]).join(', ')}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
