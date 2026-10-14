import { memo, useMemo } from 'react'
import { EChart } from '@bcs/ui/src/components/EChart'
import type { Point } from '../data/store'

/** A minimal 2-minute line: no axes, no grid, no tooltip, no animation. */
export const Sparkline = memo(function Sparkline({ points, height = 26 }: { points: Point[] | undefined; height?: number }) {
  const option = useMemo(
    () => ({
      animation: false,
      grid: { left: 0, right: 0, top: 2, bottom: 2 },
      xAxis: { type: 'value', show: false, min: 'dataMin', max: 'dataMax' },
      yAxis: { type: 'value', show: false, scale: true },
      series: [
        {
          type: 'line',
          data: points ?? [],
          showSymbol: false,
          silent: true,
          lineStyle: { width: 1.5, color: '#3fe0d0' },
          areaStyle: { color: 'rgba(63, 224, 208, 0.12)' },
        },
      ],
    }),
    [points],
  )
  return (
    <div className="sparkline" aria-hidden="true">
      <EChart option={option} height={height} />
    </div>
  )
})
