import { useMemo, useState } from 'react'
import type { EChartsOption } from 'echarts'
import type { Snapshot } from '../api/types'
import { EChart } from './EChart'

const RANGES = [
  { key: '1M', days: 30 },
  { key: '3M', days: 90 },
  { key: '6M', days: 180 },
  { key: '1Y', days: 365 },
  { key: 'ALL', days: Infinity },
] as const

interface Props {
  snapshots: Snapshot[]
}

/** 组合净值 vs 沪深300 vs 标普500 归一化曲线（起点 1.0）。 */
export function NavChart({ snapshots }: Props) {
  const [range, setRange] = useState<(typeof RANGES)[number]['key']>('ALL')

  const option = useMemo<EChartsOption>(() => {
    const days = RANGES.find((r) => r.key === range)!.days
    const filtered =
      days === Infinity
        ? snapshots
        : snapshots.slice(Math.max(0, snapshots.length - days))

    const dates = filtered.map((s) => s.snapshot_date)
    const mk = (key: 'unit_nav' | 'csi300_nav' | 'sp500_nav') =>
      filtered.map((s) => (s[key] === null ? null : parseFloat(s[key] as string)))

    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: '#1e293b', borderColor: '#334155', textStyle: { color: '#e2e8f0', fontSize: 12 } },
      legend: {
        data: ['组合净值', '沪深300', '标普500'],
        textStyle: { color: '#94a3b8', fontSize: 12 },
        top: 0,
      },
      grid: { left: 50, right: 20, top: 36, bottom: 48 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#64748b', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#64748b', fontSize: 11, formatter: (v: number) => v.toFixed(2) },
      },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 8, borderColor: '#334155', backgroundColor: '#0f172a' }],
      series: [
        { name: '组合净值', type: 'line', data: mk('unit_nav'), showSymbol: false, lineWidth: 2, lineStyle: { width: 2, color: '#3b82f6' }, itemStyle: { color: '#3b82f6' }, emphasis: { focus: 'series' } },
        { name: '沪深300', type: 'line', data: mk('csi300_nav'), showSymbol: false, lineStyle: { width: 1.2, color: '#f59e0b' }, itemStyle: { color: '#f59e0b' }, emphasis: { focus: 'series' } },
        { name: '标普500', type: 'line', data: mk('sp500_nav'), showSymbol: false, lineStyle: { width: 1.2, color: '#a78bfa' }, itemStyle: { color: '#a78bfa' }, emphasis: { focus: 'series' } },
      ],
    }
  }, [snapshots, range])

  return (
    <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-300">净值曲线 · 对标基准</h3>
        <div className="flex gap-1">
          {RANGES.map(({ key }) => (
            <button
              key={key}
              onClick={() => setRange(key)}
              className={
                'rounded px-2 py-0.5 text-[11px] transition-colors ' +
                (range === key
                  ? 'bg-brand-primary/20 text-brand-primary'
                  : 'text-slate-500 hover:text-slate-300')
              }
            >
              {key}
            </button>
          ))}
        </div>
      </div>
      <div className="h-80">
        <EChart option={option} />
      </div>
    </div>
  )
}
