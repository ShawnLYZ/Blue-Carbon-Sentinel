import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DatasetComponent,
  MarkLineComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

const axis = {
  axisLine: { lineStyle: { color: '#7fa3ad' } },
  axisLabel: { color: '#7fa3ad' },
  splitLine: { lineStyle: { color: 'rgba(80,220,230,0.1)' } },
}
echarts.registerTheme('bcs-dark', {
  backgroundColor: 'transparent',
  color: ['#3fe0d0', '#1aa7ff', '#f1c40f', '#ff8c1a', '#2ecc71', '#ff3b3b'],
  textStyle: { color: '#e6f6f8', fontFamily: 'Inter, system-ui, sans-serif' },
  categoryAxis: axis,
  valueAxis: axis,
  timeAxis: axis,
  legend: { textStyle: { color: '#7fa3ad' } },
})

export interface EChartProps {
  option: EChartsCoreOption
  height?: number | string
}

export function EChart({ option, height = 220 }: EChartProps) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const c = echarts.init(el, 'bcs-dark')
    chart.current = c
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(el)
    return () => {
      ro.disconnect()
      c.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}
