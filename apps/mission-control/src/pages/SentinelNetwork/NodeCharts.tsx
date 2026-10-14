import { useEffect, useMemo, useState } from 'react'
import { Panel, SimulatedBadge, formatMYT } from '@bcs/ui'
import { LazyEChart as EChart } from '../../lib/LazyEChart'
import type { Node, TelemetryPoint } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { TELEMETRY_WINDOW_MS, useAppStore } from '../../data/store'
import { TYPE_PARAMS, paramMeta } from '../../data/network'

const EMPTY: TelemetryPoint[] = []

/** HTTP history and live samples merged by time (a live sample replaces nothing; duplicates drop). */
export function mergeSeries(history: TelemetryPoint[], live: TelemetryPoint[]): TelemetryPoint[] {
  const byT = new Map<string, TelemetryPoint>()
  for (const p of history) byT.set(p.t, p)
  for (const p of live) byT.set(p.t, p)
  return [...byT.values()].sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0))
}

const GRID_H = 64
const GRID_GAP = 30
const TOP = 26

/** One stacked grid per reading, sharing a 15-minute MYT time axis; each y axis carries its unit. */
export function chartOption(params: string[], points: TelemetryPoint[], endMs: number) {
  const start = endMs - TELEMETRY_WINDOW_MS
  const grids = params.map((_, i) => ({ left: 52, right: 14, top: TOP + i * (GRID_H + GRID_GAP), height: GRID_H }))
  const timeLabel = (v: number) => formatMYT(new Date(v).toISOString()).replace(' MYT', '')
  return {
    animation: false,
    grid: grids,
    tooltip: {
      trigger: 'axis',
      formatter: (items: { seriesName: string; value: [number, number]; seriesIndex: number }[]) => {
        if (!items.length) return ''
        const t = formatMYT(new Date(items[0]!.value[0]).toISOString(), { seconds: true })
        return [t, ...items.map((it) => {
          const m = paramMeta(params[it.seriesIndex]!)
          return `${m.label}: ${it.value[1].toFixed(m.dp)} ${m.unit}`
        })].join('<br/>')
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: params.map((_, i) => ({
      type: 'time',
      gridIndex: i,
      min: start,
      max: endMs,
      axisLabel: { show: i === params.length - 1, formatter: timeLabel, hideOverlap: true },
      splitLine: { show: false },
    })),
    yAxis: params.map((p, i) => {
      const m = paramMeta(p)
      return {
        type: 'value',
        gridIndex: i,
        scale: true,
        name: `${m.label} (${m.unit})`,
        nameLocation: 'end',
        nameGap: 8,
        nameTextStyle: { align: 'left', color: '#9fc4cc', fontSize: 11 },
        splitNumber: 2,
        axisLabel: { fontSize: 10 },
      }
    }),
    series: params.map((p, i) => ({
      name: paramMeta(p).label,
      type: 'line',
      xAxisIndex: i,
      yAxisIndex: i,
      showSymbol: points.length < 40, // a lone sample is otherwise invisible
      connectNulls: false,
      lineStyle: { width: 1.5 },
      data: points.filter((pt) => pt.readings[p] !== undefined).map((pt) => [Date.parse(pt.t), pt.readings[p]]),
    })),
  }
}

export function chartHeight(n: number): number {
  return TOP + n * (GRID_H + GRID_GAP) + 4
}

/** The selected node's readings over the last 15 minutes: HTTP history plus live samples (design §26). */
export function NodeCharts({ node }: { node: Node }) {
  const live = useAppStore((s) => s.nodes.telemetry[node.id] ?? EMPTY)
  const [history, setHistory] = useState<TelemetryPoint[]>(EMPTY)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setHistory(EMPTY)
    setError(null)
    const to = new Date()
    const from = new Date(to.getTime() - TELEMETRY_WINDOW_MS)
    api
      .GET('/api/v1/nodes/{node_id}/telemetry', {
        params: { path: { node_id: node.id }, query: { from: from.toISOString(), to: to.toISOString(), max_points: 500 } },
      })
      .then(
        (r) => {
          if (!alive) return
          if (r.data) setHistory(r.data.points)
          else setError(apiErrorText(r.error, 'Could not load the telemetry history.'))
        },
        (e: unknown) => alive && setError(networkErrorText(e)),
      )
    return () => {
      alive = false
    }
  }, [node.id])

  const params = TYPE_PARAMS[node.node_type]
  const points = useMemo(() => mergeSeries(history, live), [history, live])
  const option = useMemo(() => {
    const last = points.length ? Date.parse(points[points.length - 1]!.t) : Date.now()
    return chartOption(params, points, Math.max(last, Date.now() - 5000))
  }, [params, points])

  return (
    <Panel title={`${node.id} · last 15 minutes`} actions={<SimulatedBadge />}>
      <div data-testid="node-charts" data-points={points.length}>
        <EChart option={option} height={chartHeight(params.length)} />
      </div>
      {points.length === 0 && !error && <p className="hint">No samples in the last 15 minutes yet.</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Panel>
  )
}
