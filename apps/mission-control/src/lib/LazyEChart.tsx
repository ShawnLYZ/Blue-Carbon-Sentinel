import { Suspense, lazy } from 'react'
import type { EChartProps } from '@bcs/ui/src/components/EChart'

// ECharts is large: it is loaded on first use, in its own chunk, not in the main bundle.
const Chart = lazy(() => import('@bcs/ui/src/components/EChart').then((m) => ({ default: m.EChart })))

/** `EChart` from @bcs/ui, loaded on demand. */
export function LazyEChart({ height = 220, ...rest }: EChartProps) {
  return (
    <Suspense fallback={<div className="chart-loading" style={{ height }}>loading chart…</div>}>
      <Chart height={height} {...rest} />
    </Suspense>
  )
}
