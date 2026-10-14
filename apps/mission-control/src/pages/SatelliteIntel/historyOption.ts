import type { History } from '@bcs/api-types'

export const BASELINE_LABEL = 'AI-generated baseline — stand-in for the Sentinel-2 archive'
export const REAL_LABEL = 'Camera captures'
export const AXIS_FIRST_YEAR = 2016
export const AXIS_LAST_YEAR = 2035

export interface HistoryPoints {
  /** AI baseline as [year, canopy %]; the site mean, or one zone. */
  baseline: [number, number][]
  /** Real capture points as [fractional year, canopy %]; only 2026 on. */
  real: [number, number][]
}

function yearFraction(iso: string): number {
  const t = Date.parse(iso)
  const y = new Date(t).getUTCFullYear()
  const start = Date.UTC(y, 0, 1)
  return y + (t - start) / (Date.UTC(y + 1, 0, 1) - start)
}

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length

/** Reduces the History body to the two plotted series: for `zoneId`, or the mean over all zones when null. */
export function historyPoints(h: History, zoneId: string | null = null): HistoryPoints {
  const zones = Object.entries(h.series).filter(([id]) => zoneId === null || id === zoneId)
  const byYear = new Map<number, number[]>()
  for (const [, years] of zones) for (const y of years) byYear.set(y.year, [...(byYear.get(y.year) ?? []), y.canopy_pct])
  const baseline = [...byYear.entries()].sort((a, b) => a[0] - b[0]).map(([y, v]): [number, number] => [y, mean(v)])
  const byT = new Map<string, number[]>()
  for (const r of h.real) {
    if (zoneId !== null && r.zone_id !== zoneId) continue
    if (yearFraction(r.t) < 2026) continue
    byT.set(r.t, [...(byT.get(r.t) ?? []), r.canopy_pct])
  }
  const real = [...byT.entries()]
    .map(([t, v]): [number, number] => [yearFraction(t), mean(v)])
    .sort((a, b) => a[0] - b[0])
  return { baseline, real }
}

/** ECharts option: dashed AI baseline (labelled), solid real capture points, x 2016-2035. */
export function historyOption(p: HistoryPoints) {
  return {
    animation: false,
    grid: { left: 52, right: 16, top: 36, bottom: 32 },
    legend: { top: 0, data: [BASELINE_LABEL, REAL_LABEL], textStyle: { fontSize: 10 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value', min: AXIS_FIRST_YEAR, max: AXIS_LAST_YEAR, interval: 5, name: 'Year', nameLocation: 'middle', nameGap: 22 },
    yAxis: { type: 'value', min: 0, max: 100, name: 'Canopy cover (%)', nameLocation: 'middle', nameGap: 36 },
    series: [
      {
        name: BASELINE_LABEL,
        type: 'line',
        data: p.baseline,
        showSymbol: false,
        lineStyle: { type: 'dashed', width: 2 },
        itemStyle: { color: '#1aa7ff' },
      },
      {
        name: REAL_LABEL,
        type: 'line',
        data: p.real,
        symbolSize: 8,
        lineStyle: { type: 'solid', width: 2.5 },
        itemStyle: { color: '#3fe0d0' },
      },
    ],
  }
}
