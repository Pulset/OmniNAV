import { useEffect, useState } from 'react'
import { Play, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { AlertRule, Asset, RuleType } from '../api/types'

const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-brand-primary'

export function Settings() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [rules, setRules] = useState<AlertRule[]>([])
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const [ruleForm, setRuleForm] = useState({
    rule_type: 'DAILY_PCT_CHANGE' as RuleType,
    asset_id: '',
    threshold: '0.05',
  })
  const [navForm, setNavForm] = useState({
    asset_id: '',
    nav_date: new Date().toISOString().slice(0, 10),
    nav: '',
  })
  const [running, setRunning] = useState('')

  const load = async () => {
    const [a, r] = await Promise.all([
      api.get<Asset[]>('/assets'),
      api.get<AlertRule[]>('/alert-rules'),
    ])
    setAssets(a)
    setRules(r)
  }

  useEffect(() => {
    void load()
  }, [])

  const addRule = async () => {
    try {
      await api.post('/alert-rules', {
        rule_type: ruleForm.rule_type,
        asset_id: ruleForm.rule_type === 'DAILY_PCT_CHANGE' ? ruleForm.asset_id : null,
        threshold: parseFloat(ruleForm.threshold),
      })
      setMsg({ ok: true, text: '规则已添加' })
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  const toggleRule = async (r: AlertRule) => {
    await api.put(`/alert-rules/${r.id}`, { is_active: !r.is_active })
    await load()
  }

  const removeRule = async (id: number) => {
    await api.delete(`/alert-rules/${id}`)
    await load()
  }

  const saveNav = async () => {
    try {
      await api.post(`/market/manual-nav/${navForm.asset_id}`, {
        nav_date: navForm.nav_date,
        nav: parseFloat(navForm.nav),
      })
      setMsg({ ok: true, text: '净值已更新，次日清算生效' })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  const runJob = async (job: string, targetDate?: string) => {
    setRunning(job)
    setMsg(null)
    try {
      const qs = targetDate ? `?target_date=${targetDate}` : ''
      await api.post(`/market/jobs/run/${job}${qs}`)
      setMsg({ ok: true, text: `${job} 执行完成` })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setRunning('')
    }
  }

  // 本月最后一个工作日（月报手动触发时跳过「最后交易日」自检）
  const lastTradingDayOfMonth = () => {
    const last = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0)
    while (last.getDay() === 0 || last.getDay() === 6) last.setDate(last.getDate() - 1)
    const m = String(last.getMonth() + 1).padStart(2, '0')
    const d = String(last.getDate()).padStart(2, '0')
    return `${last.getFullYear()}-${m}-${d}`
  }

  const manualNavAssets = assets.filter((a) => a.valuation_type === 'MANUAL_NAV')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">设置</h1>
      {msg && (
        <div
          className={
            'rounded-lg border p-3 text-sm ' +
            (msg.ok
              ? 'border-profit/40 bg-profit/10 text-profit'
              : 'border-loss/40 bg-loss/10 text-loss')
          }
        >
          {msg.text}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-300">
            <Plus className="h-4 w-4" /> 告警规则
          </h3>
          <div className="grid grid-cols-3 gap-2">
            <select
              className={inputCls}
              value={ruleForm.rule_type}
              onChange={(e) =>
                setRuleForm({ ...ruleForm, rule_type: e.target.value as RuleType })
              }
            >
              <option value="DAILY_PCT_CHANGE">单日涨跌幅</option>
              <option value="DRAWDOWN">组合回撤</option>
            </select>
            {ruleForm.rule_type === 'DAILY_PCT_CHANGE' ? (
              <select
                className={inputCls}
                value={ruleForm.asset_id}
                onChange={(e) => setRuleForm({ ...ruleForm, asset_id: e.target.value })}
              >
                <option value="">选择资产…</option>
                {assets.map((a) => (
                  <option key={a.asset_id} value={a.asset_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            ) : (
              <div className="flex items-center justify-center rounded-lg border border-dashed border-slate-700 text-xs text-slate-600">
                作用于组合整体
              </div>
            )}
            <div className="flex gap-2">
              <input
                type="number"
                step="0.01"
                className={inputCls}
                value={ruleForm.threshold}
                onChange={(e) => setRuleForm({ ...ruleForm, threshold: e.target.value })}
                placeholder="0.05"
              />
              <button
                onClick={() => void addRule()}
                disabled={
                  !ruleForm.threshold ||
                  (ruleForm.rule_type === 'DAILY_PCT_CHANGE' && !ruleForm.asset_id)
                }
                className="shrink-0 rounded-lg bg-brand-primary px-3 text-sm font-medium text-white disabled:opacity-40"
              >
                添加
              </button>
            </div>
          </div>

          <div className="mt-3 space-y-1.5">
            {rules.length === 0 && (
              <div className="py-6 text-center text-xs text-slate-600">暂无规则</div>
            )}
            {rules.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between rounded-lg border border-slate-800 px-3 py-2 text-sm"
              >
                <div>
                  <span className="text-slate-300">
                    {r.rule_type === 'DAILY_PCT_CHANGE'
                      ? `${r.asset_id} 单日 ±${(parseFloat(r.threshold) * 100).toFixed(1)}%`
                      : `组合回撤 ≥ ${(parseFloat(r.threshold) * 100).toFixed(1)}%`}
                  </span>
                  <span
                    className={
                      'ml-2 text-[10px] ' + (r.is_active ? 'text-profit' : 'text-slate-600')
                    }
                  >
                    {r.is_active ? '生效中' : '已停用'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void toggleRule(r)}
                    className="text-xs text-slate-500 hover:text-slate-300"
                  >
                    {r.is_active ? '停用' : '启用'}
                  </button>
                  <button
                    onClick={() => void removeRule(r.id)}
                    className="rounded p-1 text-slate-600 hover:text-loss"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
            <h3 className="mb-3 text-sm font-medium text-slate-300">
              净值型理财 · 手动更新净值
            </h3>
            {manualNavAssets.length === 0 ? (
              <div className="py-4 text-center text-xs text-slate-600">
                暂无 MANUAL_NAV 估值类型的资产
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                <select
                  className={inputCls}
                  value={navForm.asset_id}
                  onChange={(e) => setNavForm({ ...navForm, asset_id: e.target.value })}
                >
                  <option value="">选择资产…</option>
                  {manualNavAssets.map((a) => (
                    <option key={a.asset_id} value={a.asset_id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <input
                  type="date"
                  className={inputCls}
                  value={navForm.nav_date}
                  onChange={(e) => setNavForm({ ...navForm, nav_date: e.target.value })}
                />
                <div className="flex gap-2">
                  <input
                    type="number"
                    step="any"
                    className={inputCls}
                    value={navForm.nav}
                    onChange={(e) => setNavForm({ ...navForm, nav: e.target.value })}
                    placeholder="单位净值"
                  />
                  <button
                    onClick={() => void saveNav()}
                    disabled={!navForm.asset_id || !navForm.nav}
                    className="shrink-0 rounded-lg bg-brand-primary px-3 text-sm font-medium text-white disabled:opacity-40"
                  >
                    保存
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
            <h3 className="mb-1 text-sm font-medium text-slate-300">运维 · 手动触发 Job</h3>
            <p className="mb-3 text-[11px] text-slate-600">
              与定时调度等价，用于调试与补算（清算请传目标日期，默认昨日）。
            </p>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  ['eod_settlement', '06:00 终局清算', undefined],
                  ['evening_brief', '22:00 A股简报', undefined],
                  ['intraday_monitor', '盘中监控', undefined],
                  ['monthly_report', '月度报告', lastTradingDayOfMonth()],
                ] as [string, string, string | undefined][]
              ).map(([job, label, targetDate]) => (
                <button
                  key={job}
                  onClick={() => void runJob(job, targetDate)}
                  disabled={!!running}
                  className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 transition-colors hover:border-brand-primary hover:text-brand-primary disabled:opacity-40"
                >
                  <Play className="h-3 w-3" />
                  {running === job ? '执行中…' : label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
