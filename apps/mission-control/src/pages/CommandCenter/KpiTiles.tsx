// Command Center KPI tiles (design §26). Each tile states its unit and carries a tooltip naming its source.
import type { ReactNode } from 'react'
import { riskColor, type RiskClass } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { useCarbonSummary } from '../../data/carbon'
import { fmtTco2e } from './carbonFormat'
import { activeRisks, mangroveHealthPct, nodesOnline, waterQualityStatus } from './kpis'

export const WQ_WORDS: Record<RiskClass, string> = { low: 'Good', medium: 'Watch', high: 'Poor', critical: 'Critical' }

function Tile({ id, label, unit, tip, children }: { id: string; label: string; unit?: string; tip: string; children: ReactNode }) {
  return (
    <div className="kpi" data-testid={`kpi-${id}`} title={tip}>
      <span className="kpi__label">{label}</span>
      <span className="kpi__value bcs-mono">{children}</span>
      {unit && <span className="kpi__unit">{unit}</span>}
    </div>
  )
}

export function KpiTiles() {
  const status = useAppStore((s) => s.system.status)
  const nodes = useAppStore((s) => s.nodes.items)
  const metrics = useAppStore((s) => s.zones.metrics)
  const assessments = useAppStore((s) => s.assessments.byZone)
  const bands = useAppStore((s) => s.bands.parameters)
  const limits = useAppStore((s) => s.bands.classLimits)

  const carbon = useCarbonSummary((s) => s.summary)
  const camera = status?.components.find((c) => c.id === 'camera')
  const cameraText = !camera ? '—' : camera.status === 'ok' ? 'Live' : camera.status === 'warn' ? 'Degraded' : camera.status === 'off' ? 'Offline' : 'Down'
  const net = nodesOnline(nodes)
  const health = mangroveHealthPct(Object.values(metrics))
  const risks = activeRisks(Object.values(assessments))
  const wq = waterQualityStatus(nodes, bands, limits)

  return (
    <div className="kpis" role="group" aria-label="Key figures">
      <Tile id="camera" label="Camera" tip="Overhead camera link: frames arriving from the Ground Station camera service.">
        {cameraText}
      </Tile>
      <Tile id="network" label="Sentinel Network" unit="nodes online" tip="Registered Sentinel Nodes reporting online, from the node registry and live node status events.">
        {net.total === 0 ? '—' : `${net.online}/${net.total}`}
      </Tile>
      <Tile
        id="health"
        label="Mangrove health"
        unit="% of baseline"
        tip="Canopy-weighted mean of the NDVI-proxy (VARI from the RGB camera) relative to each zone's baseline VARI. A proxy, not true NDVI."
      >
        {health === null ? '—' : health.toFixed(0)}
      </Tile>
      <Tile id="risks" label="Active risks" unit="zones high or critical" tip={`Zones whose latest fusion assessment is high or critical (risk score ${limits ? `${limits.medium} and above` : 'above the medium limit'}).`}>
        {Object.keys(assessments).length === 0 ? '—' : risks}
      </Tile>
      <Tile id="water" label="Water quality" tip="Worst stressor class across the latest readings of the online water-quality nodes, from the configured parameter bands.">
        {wq === null ? (
          '—'
        ) : (
          <span style={{ color: riskColor(wq) }}>
            <span className="kpi__dot" style={{ background: riskColor(wq) }} aria-hidden="true" />
            {WQ_WORDS[wq]}
          </span>
        )}
      </Tile>
      <Tile id="carbon-stock" label="Carbon stock" unit="tCO₂e" tip="Standing blue-carbon stock of the monitored zones (GET /carbon/summary). Not a credit quantity.">
        {fmtTco2e(carbon?.stock_tco2e)}
      </Tile>
      <Tile id="verified" label="Verified demo credits" unit="tCO₂e" tip="Sum of Verified ledger records. Demo credits only, not certified or tradable.">
        {fmtTco2e(carbon?.verified_tco2e)}
      </Tile>
    </div>
  )
}
