import { useMemo, useState } from 'react'
import type { EChartsOption } from 'echarts'
import type { Snapshot } from '../api/types'
import { fmtPct, pnlColor } from '../lib/format'
import { EChart } from './EChart'

const RANGES = [
  { key: '1M', months: 1 },
  { key: '3M', months: 3 },
  { key: '6M', months: 6 },
  { key: '1Y', months: 12 },
  { key: 'ALL', months: Infinity },
] as const

const SERIES = [
  { key: 'unit_nav' as const, name: '组合净值', color: '#3b82f6' },
  { key: 'csi300_nav' as const, name: '沪深300', color: '#f59e0b' },
  { key: 'sp500_nav' as const, name: '标普500', color: '#a78bfa' },
  { key: 'nasdaq_nav' as const, name: '纳斯达克', color: '#f472b6' },
]

interface Props {
  snapshots: Snapshot[]
}

/** 组合净值 vs 沪深300 vs 标普500 归一化曲线（起点 1.0），图例带区间累计涨幅。 */
export function NavChart({ snapshots }: Props) {
  const [range, setRange] = useState<(typeof RANGES)[number]['key']>('ALL')

  const { option, returns } = useMemo(() => {
    const months = RANGES.find((r) => r.key === range)!.months

    // 区间口径与主流行情 App 一致：起点 = 最新快照日往前 N 个日历月，
    // 基准价取「不晚于该日」的最近一条快照（前收语义），避免吞掉起点的当日涨跌。
    let baseSnap: Snapshot | undefined
    let window = snapshots
    if (snapshots.length && months !== Infinity) {
      const latest = snapshots[snapshots.length - 1].snapshot_date
      const cut = new Date(latest + 'T00:00:00')
      cut.setMonth(cut.getMonth() - months)
      const cutoff = `${cut.getFullYear()}-${String(cut.getMonth() + 1).padStart(2, '0')}-${String(cut.getDate()).padStart(2, '0')}`
      const i0 = snapshots.findIndex((s) => s.snapshot_date > cutoff)
      baseSnap = i0 > 0 ? snapshots[i0 - 1] : undefined
      window = i0 >= 0 ? snapshots.slice(i0) : snapshots
    }

    const dates = window.map((s) => s.snapshot_date)
    const seriesData = SERIES.map((s) =>
      window.map((x) => (x[s.key] === null ? null : parseFloat(x[s.key] as string))),
    )

    // 区间累计涨幅：末值 / 基准值（基准快照缺该序列时回退窗口内首个非空值）
    const pct = (
      key: (typeof SERIES)[number]['key'],
    ): number | null => {
      const baseVal =
        baseSnap && baseSnap[key] !== null ? parseFloat(baseSnap[key] as string) : null
      const vals = seriesData[SERIES.findIndex((s) => s.key === key)]
      const first = baseVal ?? vals.find((v) => v !== null) ?? null
      const last = [...vals].reverse().find((v) => v !== null) ?? null
      return first && last && first !== 0 ? last / first - 1 : null
    }

    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: '#1e293b', borderColor: '#334155', textStyle: { color: '#e2e8f0', fontSize: 12 } },
      grid: { left: 50, right: 20, top: 16, bottom: 48 },
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
      series: SERIES.map((s, i) => ({
        name: s.name,
        type: 'line' as const,
        data: seriesData[i],
        showSymbol: false,
        lineStyle: { width: s.key === 'unit_nav' ? 2 : 1.2, color: s.color },
        itemStyle: { color: s.color },
        emphasis: { focus: 'series' },
      })),
    }

    return {
      option,
      returns: SERIES.map((s) => ({ name: s.name, color: s.color, pct: pct(s.key) })),
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
      <div className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {returns.map((r) => (
          <span key={r.name} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: r.color }} />
            <span className="text-slate-400">{r.name}</span>
            <span className={'tabular-nums ' + pnlColor(r.pct)}>{fmtPct(r.pct)}</span>
          </span>
        ))}
      </div>
      <div className="h-80">
        <EChart option={option} />
      </div>
    </div>
  )
}
