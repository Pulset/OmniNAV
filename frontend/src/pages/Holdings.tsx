import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HoldingsResponse } from '../api/types'
import { AllocationPie } from '../components/AllocationPie'
import {
  CLASS_LABELS,
  MARKET_LABELS,
  fmtNumber,
  fmtPct,
  pnlColor,
} from '../lib/format'
import { useSettings } from '../store/settings'

export function Holdings() {
  const { baseCurrency } = useSettings()
  const [data, setData] = useState<HoldingsResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<HoldingsResponse>(`/portfolio/holdings?base=${baseCurrency}`)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [baseCurrency])

  if (error) {
    return (
      <div className="rounded-lg border border-loss/40 bg-loss/10 p-3 text-sm text-loss">
        {error}
      </div>
    )
  }

  const holdings = data?.holdings ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">持仓穿透</h1>
        <span className="text-xs text-slate-500">
          总市值 {fmtNumber(data?.total_value)} {baseCurrency}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <AllocationPie data={data?.allocation_by_class ?? {}} by="class" />
        <AllocationPie data={data?.allocation_by_market ?? {}} by="market" />
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-card-bg">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              <th className="px-4 py-3">标的</th>
              <th className="px-4 py-3">类别</th>
              <th className="px-4 py-3 text-right">数量</th>
              <th className="px-4 py-3 text-right">单价</th>
              <th className="px-4 py-3 text-right">市值</th>
              <th className="px-4 py-3 text-right">成本</th>
              <th className="px-4 py-3 text-right">浮动盈亏</th>
              <th className="px-4 py-3 text-right">当日</th>
              <th className="px-4 py-3 text-right">占比</th>
            </tr>
          </thead>
          <tbody>
            {holdings.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-10 text-center text-xs text-slate-600">
                  暂无持仓，请先在「流水」页录入交易
                </td>
              </tr>
            )}
            {holdings.map((h) => (
              <tr key={h.asset_id} className="border-b border-slate-800/50 last:border-0">
                <td className="px-4 py-2.5">
                  <div className="font-medium text-slate-200">{h.name}</div>
                  <div className="text-[10px] text-slate-500">
                    {h.asset_id} · {h.currency}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-slate-400">
                  {CLASS_LABELS[h.asset_class]}/{MARKET_LABELS[h.market]}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(h.quantity)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(h.unit_price, 4)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(h.market_value)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">
                  {fmtNumber(h.cost_basis)}
                </td>
                <td className={'px-4 py-2.5 text-right tabular-nums ' + pnlColor(h.unrealized_pnl)}>
                  <div>{fmtNumber(h.unrealized_pnl)}</div>
                  <div className="text-[10px]">{fmtPct(h.unrealized_pnl_pct)}</div>
                </td>
                <td className={'px-4 py-2.5 text-right tabular-nums ' + pnlColor(h.day_change_pct)}>
                  {fmtPct(h.day_change_pct)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">
                  {fmtPct(h.weight, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
