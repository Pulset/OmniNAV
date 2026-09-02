import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import { EChart } from './EChart'
import { CLASS_LABELS, MARKET_LABELS } from '../lib/format'

const PALETTE = ['#3b82f6', '#10b981', '#f59e0b', '#a78bfa', '#f472b6', '#38bdf8']

interface Props {
  data: Record<string, string>
  by: 'class' | 'market'
}

/** 资产穿透分布环形图（按大类/市场）。 */
export function AllocationPie({ data, by }: Props) {
  const option = useMemo<EChartsOption>(() => {
    const labels = by === 'class' ? CLASS_LABELS : MARKET_LABELS
    const items = Object.entries(data)
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: '{b}: {d}%',
      },
      legend: { bottom: 0, textStyle: { color: '#94a3b8', fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
      series: [
        {
          type: 'pie',
          radius: ['45%', '70%'],
          center: ['50%', '44%'],
          itemStyle: { borderColor: '#0f172a', borderWidth: 2, borderRadius: 4 },
          label: { show: false },
          data: items.map(([k, v], i) => ({
            name: labels[k] ?? k,
            value: parseFloat(v),
            itemStyle: { color: PALETTE[i % PALETTE.length] },
          })),
        },
      ],
    }
  }, [data, by])

  return (
    <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
      <h3 className="mb-1 text-sm font-medium text-slate-300">
        {by === 'class' ? '资产大类分布' : '市场分布'}
      </h3>
      <div className="h-64">
        <EChart option={option} />
      </div>
    </div>
  )
}
