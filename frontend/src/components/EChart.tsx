import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

interface Props {
  option: EChartsOption
  className?: string
  onEvents?: Record<string, (params: unknown) => void>
}

/** ECharts 轻封装：init/setOption/resize/销毁。 */
export function EChart({ option, className, onEvents }: Props) {
  const elRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!elRef.current) return
    const chart = echarts.init(elRef.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(elRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.setOption(option, { notMerge: true })
    if (onEvents) {
      for (const [event, handler] of Object.entries(onEvents)) {
        chart.on(event, handler as never)
      }
    }
  }, [option, onEvents])

  return <div ref={elRef} className={className ?? 'h-full w-full'} />
}
