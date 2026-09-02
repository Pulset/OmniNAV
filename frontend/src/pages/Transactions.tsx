import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Asset, Transaction, TransType } from '../api/types'
import { TRANS_COLORS, TRANS_LABELS, fmtNumber } from '../lib/format'

const TRANS_TYPES: TransType[] = ['BUY', 'SELL', 'DEPOSIT', 'WITHDRAW', 'DIVIDEND']
const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-brand-primary'

export function Transactions() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [txns, setTxns] = useState<Transaction[]>([])
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  const [form, setForm] = useState({
    asset_id: '',
    trans_type: 'BUY' as TransType,
    trans_date: new Date().toISOString().slice(0, 10),
    price: '',
    quantity: '',
    fee: '',
    notes: '',
  })

  const load = async () => {
    const [a, t] = await Promise.all([
      api.get<Asset[]>('/assets'),
      api.get<Transaction[]>('/transactions'),
    ])
    setAssets(a)
    setTxns(t)
  }

  useEffect(() => {
    void load()
  }, [])

  const selected = assets.find((a) => a.asset_id === form.asset_id)

  const submit = async () => {
    setSaving(true)
    setMsg(null)
    try {
      await api.post('/transactions', {
        asset_id: form.asset_id,
        trans_type: form.trans_type,
        trans_date: form.trans_date,
        price: parseFloat(form.price),
        quantity: parseFloat(form.quantity),
        fee: form.fee ? parseFloat(form.fee) : 0,
        currency: selected?.currency ?? 'CNY',
        notes: form.notes || null,
      })
      setMsg({ ok: true, text: '录入成功' })
      setForm((f) => ({ ...f, price: '', quantity: '', fee: '', notes: '' }))
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: number) => {
    try {
      await api.delete(`/transactions/${id}`)
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">交易流水</h1>

      <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
        <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-300">
          <Plus className="h-4 w-4" /> 录入交易
        </h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div>
            <label className="mb-1 block text-xs text-slate-500">资产</label>
            <select
              className={inputCls}
              value={form.asset_id}
              onChange={(e) => setForm({ ...form, asset_id: e.target.value })}
            >
              <option value="">选择资产…</option>
              {assets.map((a) => (
                <option key={a.asset_id} value={a.asset_id}>
                  {a.name} ({a.asset_id})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">类型</label>
            <select
              className={inputCls}
              value={form.trans_type}
              onChange={(e) =>
                setForm({ ...form, trans_type: e.target.value as TransType })
              }
            >
              {TRANS_TYPES.map((t) => (
                <option key={t} value={t}>
                  {TRANS_LABELS[t]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">日期</label>
            <input
              type="date"
              className={inputCls}
              value={form.trans_date}
              onChange={(e) => setForm({ ...form, trans_date: e.target.value })}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">
              价格/净值 {selected ? `(${selected.currency})` : ''}
            </label>
            <input
              type="number"
              step="any"
              className={inputCls}
              value={form.price}
              onChange={(e) => setForm({ ...form, price: e.target.value })}
              placeholder="0.00"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">数量/份额</label>
            <input
              type="number"
              step="any"
              className={inputCls}
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              placeholder="0"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">手续费</label>
            <input
              type="number"
              step="any"
              className={inputCls}
              value={form.fee}
              onChange={(e) => setForm({ ...form, fee: e.target.value })}
              placeholder="0"
            />
          </div>
          <div className="col-span-2">
            <label className="mb-1 block text-xs text-slate-500">备注</label>
            <input
              className={inputCls}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="选填"
            />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            disabled={!form.asset_id || !form.price || !form.quantity || saving}
            onClick={() => void submit()}
            className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
          >
            {saving ? '保存中…' : '保存'}
          </button>
          {msg && (
            <span className={'text-xs ' + (msg.ok ? 'text-profit' : 'text-loss')}>
              {msg.text}
            </span>
          )}
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-600">
          买入即视为外部资金流入（自动增发份额）；若资金来自已跟踪的现金资产，
          请同时录一笔该现金的「出金」，两笔流水自动抵消，不影响净值。
        </p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-card-bg">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              <th className="px-4 py-3">日期</th>
              <th className="px-4 py-3">类型</th>
              <th className="px-4 py-3">资产</th>
              <th className="px-4 py-3 text-right">价格</th>
              <th className="px-4 py-3 text-right">数量</th>
              <th className="px-4 py-3 text-right">金额</th>
              <th className="px-4 py-3 text-right">手续费</th>
              <th className="px-4 py-3">备注</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {txns.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-10 text-center text-xs text-slate-600">
                  暂无流水
                </td>
              </tr>
            )}
            {txns.map((t) => (
              <tr key={t.id} className="border-b border-slate-800/50 last:border-0">
                <td className="px-4 py-2.5 text-slate-400">{t.trans_date}</td>
                <td className={'px-4 py-2.5 font-medium ' + (TRANS_COLORS[t.trans_type] ?? '')}>
                  {TRANS_LABELS[t.trans_type]}
                </td>
                <td className="px-4 py-2.5">
                  <span className="text-slate-200">{t.asset_id}</span>
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(t.price, 4)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(t.quantity)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                  {fmtNumber(parseFloat(t.price) * parseFloat(t.quantity))}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                  {fmtNumber(t.fee)}
                </td>
                <td className="max-w-40 truncate px-4 py-2.5 text-xs text-slate-500">
                  {t.notes ?? ''}
                </td>
                <td className="px-2 py-2.5">
                  <button
                    onClick={() => void remove(t.id)}
                    className="rounded p-1 text-slate-600 transition-colors hover:text-loss"
                    title="删除"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
