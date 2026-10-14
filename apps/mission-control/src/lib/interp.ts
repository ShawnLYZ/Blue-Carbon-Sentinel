// Year interpolation for Time Travel (M5). The forecast has yearly keyframes 2026..2035; the slider
// moves continuously, so numbers interpolate linearly between integer years and the surface blends two
// textures and two height maps. Pure: no network, no three.js.
import type { Band, YearPoint } from '@bcs/api-types'

export const FIRST_YEAR = 2026
export const LAST_YEAR = 2035
/** Illustrated keyframes (FLUX, 2030 and 2035; 2026 is the real capture). */
export const KEYFRAMES = [2026, 2030, 2035] as const

export type Scenario = 'without' | 'with'
export type RiskClass = YearPoint['risk_class']
export const RISK_CLASSES: RiskClass[] = ['low', 'medium', 'high', 'critical']

const BAND_KEYS = ['canopy', 'health', 'land', 'stock_tco2e', 'seq_tco2e', 'additional_tco2e'] as const

function clampYear(y: number): number {
  return Math.min(LAST_YEAR, Math.max(FIRST_YEAR, y))
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function lerpBand(a: Band, b: Band, t: number): Band {
  return { low: lerp(a.low, b.low, t), central: lerp(a.central, b.central, t), high: lerp(a.high, b.high, t) }
}

/** Optional per-zone extras the store keeps (ruling R6); the API may or may not pass them through. */
export type YearPointExtra = YearPoint & { cohort_fraction?: number; sigma?: Band }

/**
 * Linear interpolation between integer years for every band value. Years outside the series clamp to
 * its ends; the risk class (categorical) is the nearest keyframe's. The series must be sorted by year.
 */
export function interpYear(series: YearPoint[], year: number): YearPoint {
  if (series.length === 0) throw new Error('interpYear needs at least one keyframe')
  const first = series[0]!
  const last = series[series.length - 1]!
  const y = Math.min(last.year, Math.max(first.year, year))
  let i = 0
  while (i < series.length - 2 && series[i + 1]!.year <= y) i += 1
  const a = series[i]!
  const b = series[Math.min(i + 1, series.length - 1)]!
  const span = b.year - a.year
  const t = span > 0 ? Math.min(1, Math.max(0, (y - a.year) / span)) : 0
  const out = { year: y, risk_class: t < 0.5 ? a.risk_class : b.risk_class } as YearPointExtra
  for (const k of BAND_KEYS) out[k] = lerpBand(a[k], b[k], t)
  const ca = (a as YearPointExtra).cohort_fraction
  const cb = (b as YearPointExtra).cohort_fraction
  if (typeof ca === 'number' && typeof cb === 'number') out.cohort_fraction = lerp(ca, cb, t)
  return out
}

export interface Blend {
  from: number
  to: number
  t: number
}

/** Keyframe segment of `year`: 2026-2030 blends the real capture toward 2030, 2030-2035 blends 2030 toward 2035. */
export function textureBlend(year: number): Blend {
  const y = clampYear(year)
  if (y <= 2030) return { from: 2026, to: 2030, t: (y - 2026) / 4 }
  return { from: 2030, to: 2035, t: (y - 2030) / 5 }
}

/** One colour source of the surface: the real capture, a code-only repaint year, or an illustration. */
export type ColourSource = { kind: 'capture' } | { kind: 'repaint'; year: number } | { kind: 'illustration'; year: number }

/** Ready illustrations as `${scenario}:${year}` keys (their images are loaded). */
export type IllustrationKeys = ReadonlySet<string>

export interface FrameSources {
  colour: { from: ColourSource; to: ColourSource; t: number }
  /** Heights always blend the two neighbouring yearly height maps. */
  height: Blend
  /** True when a ready illustration is visible in this year's blend ("AI-illustrated" badge). */
  illustrated: boolean
}

function repaint(year: number): ColourSource {
  return year === FIRST_YEAR ? { kind: 'capture' } : { kind: 'repaint', year }
}

/**
 * What the surface of `scenario` shows at `year`. Without ready illustrations it blends the two
 * neighbouring yearly code-only repaints (2026 is the real capture). When the keyframe at the end of
 * the year's segment (textureBlend) has a ready illustration, it blends the keyframes instead, as the
 * spec says (2026 real -> 2030 -> 2035), using the illustration where ready and the repaint otherwise.
 */
export function frameSources(year: number, scenario: Scenario, ready: IllustrationKeys): FrameSources {
  const y = clampYear(year)
  const i = Math.min(Math.floor(y), LAST_YEAR - 1)
  const height: Blend = { from: i, to: i + 1, t: y - i }
  const seg = textureBlend(y)
  const has = (k: number) => ready.has(`${scenario}:${k}`)
  const key = (k: number): ColourSource => (k !== FIRST_YEAR && has(k) ? { kind: 'illustration', year: k } : repaint(k))
  let colour: FrameSources['colour']
  if (has(seg.to) || (seg.from !== FIRST_YEAR && has(seg.from))) colour = { from: key(seg.from), to: key(seg.to), t: seg.t }
  else colour = { from: repaint(i), to: repaint(i + 1), t: height.t }
  const illustrated =
    (colour.to.kind === 'illustration' && colour.t > 0) || (colour.from.kind === 'illustration' && colour.t < 1)
  return { colour, height, illustrated }
}

/** Zones per risk class at the nearest keyframe to `year`. */
export function riskDistribution(zones: Record<string, YearPoint[]>, year: number): Record<RiskClass, number> {
  const out: Record<RiskClass, number> = { low: 0, medium: 0, high: 0, critical: 0 }
  for (const series of Object.values(zones)) {
    if (series.length === 0) continue
    out[interpYear(series, year).risk_class] += 1
  }
  return out
}
