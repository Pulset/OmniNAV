import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import { api } from '../api/client'
import type { MetricsSummary, Snapshot } from '../api/types'
import { fmtNumber, fmtPct, pnlColor } from '../lib/format'

function metric(v: number | null | undefined, digits = 2, asPct = true): string {
  if (v === null || v === undefined) return '—'
  return asPct ? fmtPct(v, digits) : v.toFixed(digits)
}

export function Review() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null)
  const [selected, setSelected] = useState<Snapshot | null>(null)
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    const [snaps, m] = await Promise.all([
      api.get<Snapshot[]>('/snapshots'),
      api.get<MetricsSummary>('/metrics/summary'),
    ])
    setSnapshots([...snaps].reverse())
    setMetrics(m)
    setSelected((prev) => (prev ? snaps.find((s) => s.snapshot_date === prev.snapshot_date) ?? null : null))
  }

  useEffect(() => {
    void load()
  }, [])

  const openNote = (s: Snapshot) => {
    setSelected(s)
    setNote(s.review_notes ?? '')
    setMsg('')
  }

  const saveNote = async () => {
    if (!selected) return
    setSaving(true)
    try {
      await api.patch(`/snapshots/${selected.snapshot_date}`, { review_notes: note })
      setMsg('已保存')
      await load()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const cards: Array<[string, string, string?]> = [
    ['累计收益', metric(metrics?.cumulative_return), pnlColor(metrics?.cumulative_return)],
    ['年化收益 (CAGR)', metric(metrics?.cagr), pnlColor(metrics?.cagr)],
    ['最大回撤', metric(metrics?.max_drawdown), 'text-loss'],
    ['夏普比率', metric(metrics?.sharpe, 2, false)],
    ['年化波动率', metric(metrics?.volatility)],
    ['胜率(日)', metric(metrics?.win_rate)],
    ['Alpha vs 沪深300', metric(metrics?.alpha_vs_csi300), pnlColor(metrics?.alpha_vs_csi300)],
    ['Beta vs 沪深300', metric(metrics?.beta_vs_csi300, 2, false)],
  ]

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">复盘日记与指标</h1>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        {cards.map(([label, value, cls]) => (
          <div key={label} className="rounded-xl border border-slate-800 bg-card-bg p-3">
            <div className="text-[11px] text-slate-500">{label}</div>
            <div className={'mt-1 text-lg font-semibold tabular-nums ' + (cls ?? '')}>
              {value}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-card-bg lg:col-span-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-3">日期</th>
                <th className="px-4 py-3 text-right">净值</th>
                <th className="px-4 py-3 text-right">涨跌</th>
                <th className="px-4 py-3 text-right">总资产(CNY)</th>
                <th className="px-4 py-3">日记</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-xs text-slate-600">
                    暂无快照，等待每日 06:00 终局清算
                  </td>
                </tr>
              )}
              {snapshots.map((s) => (
                <tr
                  key={s.snapshot_date}
                  className={
                    'cursor-pointer border-b border-slate-800/50 transition-colors last:border-0 hover:bg-slate-800/40 ' +
                    (selected?.snapshot_date === s.snapshot_date ? 'bg-brand-primary/10' : '')
                  }
                  onClick={() => openNote(s)}
                >
                  <td className="px-4 py-2.5 text-slate-300">{s.snapshot_date}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(s.unit_nav, 4)}</td>
                  <td className={'px-4 py-2.5 text-right tabular-nums ' + pnlColor(s.daily_return)}>
                    {fmtPct(s.daily_return)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">
                    {fmtNumber(s.total_market_value_cny)}
                  </td>
                  <td className="max-w-48 truncate px-4 py-2.5 text-xs text-slate-500">
                    {s.review_notes ? '📝 ' + s.review_notes : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-300">
            复盘笔记 {selected ? `· ${selected.snapshot_date}` : ''}
          </h3>
          {selected ? (
            <>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={12}
                placeholder="记录当天的市场观察、操作反思与再平衡计划…"
                className="w-full resize-none rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm text-slate-200 outline-none focus:border-brand-primary"
              />
              <div className="mt-2 flex items-center gap-3">
                <button
                  onClick={() => void saveNote()}
                  disabled={saving}
                  className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                >
                  <Save className="h-3.5 w-3.5" />
                  {saving ? '保存中…' : '保存'}
                </button>
                {msg && <span className="text-xs text-profit">{msg}</span>}
              </div>
              <p className="mt-2 text-[11px] text-slate-600">
                保存后，笔记将随当日复盘卡片一并推送。
              </p>
            </>
          ) : (
            <div className="py-16 text-center text-xs text-slate-600">
              点击左侧任一天快照编写日记
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
