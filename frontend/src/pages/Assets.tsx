import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2, X } from 'lucide-react'
import { api } from '../api/client'
import type { Asset, AssetClass, Market, ValuationType } from '../api/types'
import {
  CLASS_LABELS,
  MARKET_LABELS,
  VALUATION_LABELS,
  fmtPct,
} from '../lib/format'

const ASSET_CLASSES: AssetClass[] = ['STOCK', 'ETF', 'WEALTH', 'CASH']
const MARKETS: Market[] = ['CN', 'HK', 'US', 'GLOBAL']
const CURRENCIES = ['CNY', 'USD', 'HKD'] as const
const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-brand-primary disabled:opacity-50'

/** 类别 → 可选估值方式（CASH 类只能 CASH 估值，非 CASH 不能用 CASH 估值） */
function valuationOptions(cls: AssetClass): ValuationType[] {
  return cls === 'CASH'
    ? ['CASH']
    : ['MARKET', 'FIXED_YIELD', 'MANUAL_NAV']
}

const emptyForm = {
  asset_id: '',
  name: '',
  asset_class: 'ETF' as AssetClass,
  market: 'CN' as Market,
  currency: 'CNY',
  valuation_type: 'MARKET' as ValuationType,
  expected_apr: '0',
}

export function Assets() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(emptyForm)
  // 编辑模式下后端仅允许改 name / expected_apr，其余字段锁定
  const [editingId, setEditingId] = useState<string | null>(null)

  const load = async () => {
    setAssets(await api.get<Asset[]>('/assets'))
  }

  useEffect(() => {
    void load()
  }, [])

  const setClass = (asset_class: AssetClass) => {
    const opts = valuationOptions(asset_class)
    setForm((f) => ({
      ...f,
      asset_class,
      valuation_type: opts.includes(f.valuation_type) ? f.valuation_type : opts[0],
    }))
  }

  const startEdit = (a: Asset) => {
    setEditingId(a.asset_id)
    setMsg(null)
    setForm({
      asset_id: a.asset_id,
      name: a.name,
      asset_class: a.asset_class,
      market: a.market,
      currency: a.currency,
      valuation_type: a.valuation_type,
      expected_apr: String(a.expected_apr),
    })
  }

  const resetForm = () => {
    setEditingId(null)
    setForm(emptyForm)
  }

  const submit = async () => {
    setSaving(true)
    setMsg(null)
    try {
      if (editingId) {
        await api.put(`/assets/${editingId}`, {
          name: form.name,
          expected_apr: parseFloat(form.expected_apr),
        })
        setMsg({ ok: true, text: '资产已更新' })
      } else {
        await api.post('/assets', {
          asset_id: form.asset_id.trim(),
          name: form.name,
          asset_class: form.asset_class,
          market: form.market,
          currency: form.currency,
          valuation_type: form.valuation_type,
          expected_apr: parseFloat(form.expected_apr) || 0,
        })
        setMsg({ ok: true, text: '资产已创建' })
      }
      resetForm()
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setSaving(false)
    }
  }

  const remove = async (assetId: string) => {
    try {
      await api.delete(`/assets/${assetId}`)
      if (editingId === assetId) resetForm()
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  const canSubmit =
    !saving &&
    form.name.trim() !== '' &&
    (editingId !== null || form.asset_id.trim() !== '')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">资产标的</h1>

      <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
        <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-300">
          {editingId ? (
            <>
              <Pencil className="h-4 w-4" /> 编辑资产
              <span className="text-brand-primary">{editingId}</span>
            </>
          ) : (
            <>
              <Plus className="h-4 w-4" /> 新增资产
            </>
          )}
        </h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div>
            <label className="mb-1 block text-xs text-slate-500">资产代码</label>
            <input
              className={inputCls}
              value={form.asset_id}
              onChange={(e) => setForm({ ...form, asset_id: e.target.value })}
              placeholder="如 510300"
              disabled={editingId !== null}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">名称</label>
            <input
              className={inputCls}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="如 沪深300ETF"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">类别</label>
            <select
              className={inputCls}
              value={form.asset_class}
              onChange={(e) => setClass(e.target.value as AssetClass)}
              disabled={editingId !== null}
            >
              {ASSET_CLASSES.map((c) => (
                <option key={c} value={c}>
                  {CLASS_LABELS[c]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">市场</label>
            <select
              className={inputCls}
              value={form.market}
              onChange={(e) => setForm({ ...form, market: e.target.value as Market })}
              disabled={editingId !== null}
            >
              {MARKETS.map((m) => (
                <option key={m} value={m}>
                  {MARKET_LABELS[m]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">币种</label>
            <select
              className={inputCls}
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
              disabled={editingId !== null}
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">估值方式</label>
            <select
              className={inputCls}
              value={form.valuation_type}
              onChange={(e) =>
                setForm({ ...form, valuation_type: e.target.value as ValuationType })
              }
              disabled={editingId !== null}
            >
              {valuationOptions(form.asset_class).map((v) => (
                <option key={v} value={v}>
                  {VALUATION_LABELS[v]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">
              预期年化{form.valuation_type === 'FIXED_YIELD' && '（必填，如 0.03 = 3%）'}
            </label>
            <input
              type="number"
              step="any"
              min="0"
              className={inputCls}
              value={form.expected_apr}
              onChange={(e) => setForm({ ...form, expected_apr: e.target.value })}
              placeholder="0"
              disabled={editingId === null && form.valuation_type !== 'FIXED_YIELD'}
            />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            disabled={!canSubmit}
            onClick={() => void submit()}
            className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
          >
            {saving ? '保存中…' : editingId ? '保存修改' : '创建'}
          </button>
          {editingId && (
            <button
              onClick={resetForm}
              className="flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 transition-colors hover:text-slate-200"
            >
              <X className="h-3.5 w-3.5" /> 取消
            </button>
          )}
          {msg && (
            <span className={'text-xs ' + (msg.ok ? 'text-profit' : 'text-loss')}>
              {msg.text}
            </span>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-card-bg">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              <th className="px-4 py-3">代码</th>
              <th className="px-4 py-3">名称</th>
              <th className="px-4 py-3">类别</th>
              <th className="px-4 py-3">市场</th>
              <th className="px-4 py-3">币种</th>
              <th className="px-4 py-3">估值方式</th>
              <th className="px-4 py-3 text-right">预期年化</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {assets.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-xs text-slate-600">
                  暂无资产，请在上方创建
                </td>
              </tr>
            )}
            {assets.map((a) => (
              <tr key={a.asset_id} className="border-b border-slate-800/50 last:border-0">
                <td className="px-4 py-2.5 font-mono text-slate-300">{a.asset_id}</td>
                <td className="px-4 py-2.5 text-slate-200">{a.name}</td>
                <td className="px-4 py-2.5 text-slate-400">{CLASS_LABELS[a.asset_class] ?? a.asset_class}</td>
                <td className="px-4 py-2.5 text-slate-400">{MARKET_LABELS[a.market] ?? a.market}</td>
                <td className="px-4 py-2.5 text-slate-400">{a.currency}</td>
                <td className="px-4 py-2.5 text-slate-400">{VALUATION_LABELS[a.valuation_type] ?? a.valuation_type}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">
                  {a.valuation_type === 'FIXED_YIELD' ? fmtPct(a.expected_apr) : '—'}
                </td>
                <td className="px-2 py-2.5">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => startEdit(a)}
                      className="rounded p-1 text-slate-600 transition-colors hover:text-brand-primary"
                      title="编辑"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => void remove(a.asset_id)}
                      className="rounded p-1 text-slate-600 transition-colors hover:text-loss"
                      title="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
