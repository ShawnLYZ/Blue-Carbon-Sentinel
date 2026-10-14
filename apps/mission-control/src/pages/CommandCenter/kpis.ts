// Command Center KPI arithmetic (design §26), kept free of React and the store so it can be unit-tested.
import type { Node } from '@bcs/api-types'
import type { RiskClass } from '@bcs/ui'

/** Per-zone input of the health KPI: canopy share and the NDVI-proxy (VARI) now and its drop since baseline. */
export interface HealthZone {
  canopy_pct: number
  vari_mean?: number | null
  /** baseline vari minus current vari (ZoneMetrics.vari_drop); null without a baseline. */
  vari_drop?: number | null
}

/**
 * Mangrove health: the canopy-weighted mean of VARI relative to the baseline VARI (each zone's ratio is
 * clamped to 0..1), as a percentage. Zones without a baseline or a positive baseline are skipped.
 * `null` when no zone qualifies.
 */
export function mangroveHealthPct(zones: HealthZone[]): number | null {
  let weighted = 0
  let weight = 0
  for (const z of zones) {
    if (z.vari_mean == null || z.vari_drop == null || z.canopy_pct <= 0) continue
    const baseline = z.vari_mean + z.vari_drop
    if (!(baseline > 0)) continue
    weighted += z.canopy_pct * Math.min(1, Math.max(0, z.vari_mean / baseline))
    weight += z.canopy_pct
  }
  return weight > 0 ? (weighted / weight) * 100 : null
}

/** Zones whose latest assessment is high or critical. */
export function activeRisks(assessments: { risk_class: RiskClass }[]): number {
  return assessments.filter((a) => a.risk_class === 'high' || a.risk_class === 'critical').length
}

/** Decommissioned nodes are not part of the network. */
export function nodesOnline(nodes: Pick<Node, 'status'>[]): { online: number; total: number } {
  const live = nodes.filter((n) => n.status !== 'decommissioned')
  return { online: live.filter((n) => n.status === 'online').length, total: live.length }
}

/** GET /system/bands, reduced to what the arithmetic needs: parameter key -> (value, stress) breakpoints. */
export type BandsConfig = Record<string, { breakpoints: [number, number][] | number[][] }>

function stressOf(value: number, points: number[][]): number {
  const pts = [...points].sort((a, b) => a[0]! - b[0]!)
  if (pts.length === 0) return 0
  if (value <= pts[0]![0]!) return pts[0]![1]!
  for (let i = 1; i < pts.length; i += 1) {
    const [x0, y0] = pts[i - 1]!
    const [x1, y1] = pts[i]!
    if (value <= x1!) return y0! + ((y1! - y0!) * (value - x0!)) / (x1! - x0!)
  }
  return pts[pts.length - 1]![1]!
}

/** Upper limits of low / medium / high on the 0-100 scale (config/risk.yaml class_limits); above is critical. */
export interface ClassLimits {
  low: number
  medium: number
  high: number
}

/** The risk class of a stress (0-1) on the zone-score scale: stress x 100 against the configured limits. */
export function classOfStress(stress: number, limits: ClassLimits): RiskClass {
  const s = Math.round(stress * 1e8) / 1e6 // absorbs float noise at the class limits
  return s < limits.low ? 'low' : s < limits.medium ? 'medium' : s < limits.high ? 'high' : 'critical'
}

/**
 * The class of the worst water-quality stressor over the latest readings of the online WQ nodes, using the
 * configured stress breakpoints. `null` when there is no band configuration or no reading to judge.
 */
export function waterQualityStatus(nodes: Node[], bands: BandsConfig | null, limits: ClassLimits | null): RiskClass | null {
  if (!bands || !limits) return null
  let worst: number | null = null
  for (const n of nodes) {
    if (n.node_type !== 'water_quality' || n.status !== 'online' || !n.latest) continue
    for (const [param, value] of Object.entries(n.latest.readings)) {
      const band = bands[param]
      if (!band || !Number.isFinite(value)) continue
      const s = stressOf(value, band.breakpoints)
      worst = worst === null ? s : Math.max(worst, s)
    }
  }
  return worst === null ? null : classOfStress(worst, limits)
}
