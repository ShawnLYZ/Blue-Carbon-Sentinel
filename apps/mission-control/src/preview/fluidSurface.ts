import { Color } from 'three'
import { RISK_PALETTE, type RiskZone } from './scenarioRisk'
import type { Raster } from './satellite'

export function extentWeight(e: number, s: number): number {
  // A soft display crop, not an inferred coastline or surveyed habitat boundary.
  const d = Math.min(e, s, 500 - e, 500 - s)
  const t = Math.max(0, Math.min(1, d / 34))
  return t * t * (3 - 2 * t)
}
export function smoothRisk(e: number, s: number, zones: RiskZone[]): number | null {
  let sum = 0, weights = 0
  for (const z of zones) {
    if (z.score === null) continue
    const d2 = (e - (z.col * 100 + 50)) ** 2 + (s - (z.row * 100 + 50)) ** 2
    if (d2 < 0.01) return z.score
    const w = Math.exp(-d2 / (2 * 60 ** 2))
    sum += z.score * w; weights += w
  }
  return weights > 1e-8 ? sum / weights : null
}
export function riskRamp(score: number): Color {
  const stops = [new Color(RISK_PALETTE.low), new Color(RISK_PALETTE.medium), new Color(RISK_PALETTE.high), new Color(RISK_PALETTE.critical)]
  if (score >= 80) return stops[3]!.clone()
  const limits = [0, 30, 60, 80]
  const i = score < 30 ? 0 : score < 60 ? 1 : 2
  return stops[i]!.clone().lerp(stops[i + 1]!, Math.max(0, (score - limits[i]!) / (limits[i + 1]! - limits[i]!)))
}
export function fluidRiskPixels(zones: RiskZone[], raster: Raster | null, contours: boolean, size = 128): Uint8ClampedArray {
  const out = new Uint8ClampedArray(size * size * 4)
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const e = (x + 0.5) / size * 500, s = (y + 0.5) / size * 500
    const i = y * size + x
    const ri = raster ? Math.min(raster.height - 1, Math.floor(s / 500 * raster.height)) * raster.width + Math.min(raster.width - 1, Math.floor(e / 500 * raster.width)) : 0
    const v = !raster || !raster.valid[ri] ? null : smoothRisk(e, s, zones)
    const c = v === null ? new Color(RISK_PALETTE.unknown) : riskRamp(v)
    const contour = contours && v !== null && [30, 60, 80].some(level => Math.abs(v - level) < 0.65)
    if (contour) c.lerp(new Color('#e5f6e6'), 0.65)
    // Canvas values are sRGB; use hex conversion rather than writing linear RGB as byte data.
    const hex = c.getHex()
    out.set([hex >> 16 & 255, hex >> 8 & 255, hex & 255, Math.round(extentWeight(e, s) * 190)], i * 4)
  }
  return out
}
