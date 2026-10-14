// Uncertainty bands (US 149): low, central and high runs of the forecast for one scenario, with the
// selected year marked. ECharts loads on demand (lib/LazyEChart), outside the main bundle.
import { useMemo, useState } from 'react'
import type { Forecast, YearPoint } from '@bcs/api-types'
import { LazyEChart } from '../../lib/LazyEChart'
import type { Scenario } from '../../lib/interp'

type Metric = 'cover' | 'stock' | 'additional'

const METRICS: Record<Metric, { label: string; unit: string; pick: (p: YearPoint) => [number, number, number] }> = {
  cover: { label: 'Cover', unit: '%', pick: (p) => [p.canopy.low * 100, p.canopy.central * 100, p.canopy.high * 100] },
  stock: { label: 'Carbon stock (standing)', unit: 'tCO₂e', pick: (p) => [p.stock_tco2e.low, p.stock_tco2e.central, p.stock_tco2e.high] },
  additional: {
    label: 'Additional since 2026',
    unit: 'tCO₂e',
    pick: (p) => [p.additional_tco2e.low, p.additional_tco2e.central, p.additional_tco2e.high],
  },
}

export function bandsOption(points: YearPoint[], metric: Metric, year: number) {
  const m = METRICS[metric]
  const rows = points.map((p) => {
    const [a, c, b] = m.pick(p)
    return { year: p.year, lo: Math.min(a, b), hi: Math.max(a, b), c }
  })
  return {
    animation: false,
    grid: { left: 48, right: 12, top: 10, bottom: 22 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v.toFixed(1)} ${m.unit}` },
    xAxis: { type: 'value', min: points[0]?.year ?? 2026, max: points[points.length - 1]?.year ?? 2035, interval: 1, axisLabel: { formatter: (v: number) => String(v) } },
    yAxis: { type: 'value', scale: true, name: m.unit, nameGap: 6, nameTextStyle: { fontSize: 10 } },
    series: [
      { name: 'Low', type: 'line', stack: 'band', symbol: 'none', lineStyle: { opacity: 0 }, data: rows.map((r) => [r.year, r.lo]) },
      {
        name: 'High',
        type: 'line',
        stack: 'band',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0.22 },
        tooltip: { valueFormatter: () => '' },
        data: rows.map((r) => [r.year, r.hi - r.lo]),
      },
      {
        name: 'Central',
        type: 'line',
        symbol: 'none',
        data: rows.map((r) => [r.year, r.c]),
        markLine: { symbol: 'none', silent: true, label: { show: false }, lineStyle: { type: 'dashed' }, data: [{ xAxis: year }] },
      },
    ],
  }
}

export function BandsChart({ forecast, scenario, year }: { forecast: Forecast | null; scenario: Scenario; year: number }) {
  const [metric, setMetric] = useState<Metric>('cover')
  const points = forecast?.scenarios[scenario].site
  const option = useMemo(() => (points?.length ? bandsOption(points, metric, year) : null), [points, metric, year])
  if (!option) return null
  return (
    <div className="tt-bands">
      <div className="tt-bands__head">
        <span className="hint">Low · central · high</span>
        <select aria-label={`Band metric (${scenario})`} value={metric} onChange={(e) => setMetric(e.target.value as Metric)}>
          {(Object.keys(METRICS) as Metric[]).map((k) => (
            <option key={k} value={k}>
              {METRICS[k].label}
            </option>
          ))}
        </select>
      </div>
      <LazyEChart option={option} height={150} />
    </div>
  )
}
