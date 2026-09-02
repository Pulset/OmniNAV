import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { HoldingsResponse, Snapshot, SummaryResponse } from '../api/types'
import { MetricCard } from '../components/MetricCard'
import { NavChart } from '../components/NavChart'
import { AllocationPie } from '../components/AllocationPie'
import { fmtNumber, fmtPct, pnlColor } from '../lib/format'
import { useSettings } from '../store/settings'

export function Dashboard() {
  const { baseCurrency } = useSettings()
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [holdings, setHoldings] = useState<HoldingsResponse | null>(null)
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [s, h, snaps] = await Promise.all([
        api.get<SummaryResponse>('/portfolio/summary'),
        api.get<HoldingsResponse>(`/portfolio/holdings?base=${baseCurrency}`),
        api.get<Snapshot[]>('/snapshots'),
      ])
      setSummary(s)
      setHoldings(h)
      setSnapshots(snaps)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseCurrency])

  const latest = summary?.latest
  const movers = [...(holdings?.holdings ?? [])]
    .filter((h) => h.day_change_pct !== null)
    .sort((a, b) => parseFloat(b.day_change_pct!) - parseFloat(a.day_change_pct!))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">总览</h1>
        <button
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 transition-colors hover:text-slate-200"
        >
          <RefreshCw className={'h-3.5 w-3.5 ' + (loading ? 'animate-spin' : '')} />
          刷新
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-loss/40 bg-loss/10 p-3 text-sm text-loss">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="单位净值"
          value={latest ? fmtNumber(latest.unit_nav, 4) : '—'}
          sub={latest ? latest.date : '暂无快照'}
        />
        <MetricCard
          label="当日涨跌"
          value={latest ? fmtPct(latest.daily_return) : '—'}
          valueClassName={pnlColor(latest?.daily_return)}
          sub={latest ? `当日盈亏 ${fmtNumber(latest.daily_pnl_cny)} CNY` : undefined}
        />
        <MetricCard
          label="累计收益"
          value={latest ? fmtPct(latest.cumulative_return) : '—'}
          valueClassName={pnlColor(latest?.cumulative_return)}
          sub={`快照天数 ${summary?.snapshot_count ?? 0}`}
        />
        <MetricCard
          label={`总资产 (${baseCurrency})`}
          value={holdings ? fmtNumber(holdings.total_value) : '—'}
          sub={holdings ? `总成本 ${fmtNumber(holdings.total_cost)}` : undefined}
        />
      </div>

      <NavChart snapshots={snapshots} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <AllocationPie data={holdings?.allocation_by_class ?? {}} by="class" />
        <AllocationPie data={holdings?.allocation_by_market ?? {}} by="market" />

        <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-300">当日涨跌榜</h3>
          <div className="space-y-1.5">
            {movers.length === 0 && (
              <div className="py-8 text-center text-xs text-slate-600">暂无行情数据</div>
            )}
            {movers.slice(0, 8).map((h) => (
              <div key={h.asset_id} className="flex items-center justify-between text-sm">
                <span className="truncate text-slate-300">{h.name}</span>
                <span className={'tabular-nums ' + pnlColor(h.day_change_pct)}>
                  {fmtPct(h.day_change_pct)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
