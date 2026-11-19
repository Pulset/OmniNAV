import { useCallback, useEffect, useMemo, useState } from 'react'
import { ExternalLink, Flame, Lightbulb, ListChecks, Newspaper, RefreshCw, ShieldAlert, Wallet } from 'lucide-react'
import { api } from '../api/client'
import type { AdviceReport, AdviceSlot, HotTopic, NewsArticle, PortfolioImpact } from '../api/types'
import { cn } from '../lib/format'

const SLOTS: Array<{ key: AdviceSlot; label: string; hint: string }> = [
  { key: 'morning', label: '盘前参考', hint: '每日 08:45 · 隔夜消息 + 今日主线' },
  { key: 'midday', label: '午间速递', hint: '交易日 11:45 · 上午复盘 + 午后策略' },
  { key: 'evening', label: '晚间内参', hint: '交易日 21:30 · 全天复盘 + 明日前瞻' },
]

const DIRECTION_LABELS: Record<HotTopic['direction'], string> = {
  positive: '利多',
  negative: '利空',
  neutral: '中性',
}
const DIRECTION_CLS: Record<HotTopic['direction'], string> = {
  positive: 'bg-profit/10 text-profit',
  negative: 'bg-loss/10 text-loss',
  neutral: 'bg-slate-700/40 text-slate-300',
}
const STANCE_LABELS: Record<PortfolioImpact['stance'], string> = {
  hold: '持有观望',
  watch: '密切观察',
  consider_add: '可考虑加仓',
  consider_reduce: '可考虑减持',
}
const STANCE_CLS: Record<PortfolioImpact['stance'], string> = {
  hold: 'bg-slate-700/40 text-slate-300',
  watch: 'bg-brand-primary/10 text-brand-primary',
  consider_add: 'bg-profit/10 text-profit',
  consider_reduce: 'bg-loss/10 text-loss',
}

function Badge({ text, cls }: { text: string; cls: string }) {
  return (
    <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium', cls)}>
      {text}
    </span>
  )
}

function NewsRefs({
  refs,
  news,
  onOpen,
}: {
  refs: number[]
  news: Map<number, NewsArticle>
  onOpen: (id: number) => void
}) {
  if (!refs.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {refs.map((id) => {
        const n = news.get(id)
        return (
          <button
            key={id}
            onClick={() => n && onOpen(id)}
            title={n?.title ?? `新闻 #${id}（已过期不可见）`}
            className="max-w-[280px] truncate rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-400 transition-colors hover:bg-slate-700 hover:text-slate-200"
          >
            #{id} {n ? n.title : '（原文不可见）'}
          </button>
        )
      })}
    </div>
  )
}

export function Advice() {
  const [slot, setSlot] = useState<AdviceSlot>('morning')
  const [history, setHistory] = useState<AdviceReport[]>([])
  const [viewingId, setViewingId] = useState<number | null>(null)
  const [newsByDate, setNewsByDate] = useState<Map<string, NewsArticle[]>>(new Map())
  const [openNewsId, setOpenNewsId] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const reports = await api.get<AdviceReport[]>('/advice?days=90')
      setHistory(reports)
      setViewingId(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const slotHistory = useMemo(() => history.filter((r) => r.slot === slot), [history, slot])
  const report = useMemo(
    () => slotHistory.find((r) => r.id === viewingId) ?? slotHistory[0] ?? null,
    [slotHistory, viewingId],
  )

  // 内参所属交易日的新闻池（供引用溯源），按日期缓存
  useEffect(() => {
    if (!report || newsByDate.has(report.trade_date)) return
    api
      .get<NewsArticle[]>(`/advice/news?d=${report.trade_date}`)
      .then((list) => setNewsByDate((prev) => new Map(prev).set(report.trade_date, list)))
      .catch(() => setNewsByDate((prev) => new Map(prev).set(report.trade_date, [])))
  }, [report, newsByDate])

  const newsMap = useMemo(() => {
    const m = new Map<number, NewsArticle>()
    for (const n of newsByDate.get(report?.trade_date ?? '') ?? []) m.set(n.id, n)
    return m
  }, [newsByDate, report?.trade_date])

  const generate = async () => {
    setGenerating(true)
    setError('')
    try {
      const created = await api.post<AdviceReport>('/advice/generate', { slot })
      await load()
      setViewingId(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGenerating(false)
    }
  }

  const p = report?.payload
  const slotMeta = SLOTS.find((s) => s.key === slot)!

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">AI 投资内参</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            基于当日新闻与你的持仓生成 · {slotMeta.hint}
          </p>
        </div>
        <button
          onClick={generate}
          disabled={generating}
          className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-primary/85 disabled:opacity-50"
        >
          <RefreshCw className={cn('h-4 w-4', generating && 'animate-spin')} />
          {generating ? '生成中…' : '立即生成本时点'}
        </button>
      </div>

      {/* 时点 Tab */}
      <div className="grid grid-cols-3 gap-2">
        {SLOTS.map((s) => (
          <button
            key={s.key}
            onClick={() => { setSlot(s.key); setViewingId(null); setOpenNewsId(null) }}
            className={cn(
              'rounded-xl border px-3 py-2 text-sm transition-colors',
              slot === s.key
                ? 'border-brand-primary/50 bg-brand-primary/10 text-brand-primary'
                : 'border-slate-800 bg-card-bg text-slate-400 hover:text-slate-200',
            )}
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-loss/30 bg-loss/10 px-3 py-2 text-sm text-loss">{error}</div>
      )}

      {!report && !generating && (
        <div className="rounded-xl border border-dashed border-slate-800 bg-card-bg p-8 text-center text-sm text-slate-500">
          本时点暂无内参。定时任务每日自动生成，也可点击右上角「立即生成本时点」。
        </div>
      )}

      {report && p && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {/* 内参正文 */}
          <div className="space-y-4 xl:col-span-2">
            <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                <span>
                  {report.trade_date} 【{slotMeta.label}】 · {report.model} · 生成于{' '}
                  {new Date(report.created_at).toLocaleString('zh-CN', { hour12: false })}
                </span>
                <span>{report.cited_article_ids.length} 条引用</span>
              </div>
              <p className="mt-2 leading-relaxed text-slate-200">{p.market_summary || '—'}</p>
            </div>

            {p.hot_topics.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
                <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
                  <Flame className="h-4 w-4 text-amber-400" /> 热点解读
                </h2>
                <ul className="space-y-3">
                  {p.hot_topics.map((t, i) => (
                    <li key={i} className="rounded-lg bg-slate-900/40 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-slate-200">{t.topic}</span>
                        <Badge text={DIRECTION_LABELS[t.direction]} cls={DIRECTION_CLS[t.direction]} />
                        {t.affected.map((a) => (
                          <span key={a} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-400">
                            {a}
                          </span>
                        ))}
                      </div>
                      {t.reasoning && (
                        <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{t.reasoning}</p>
                      )}
                      <NewsRefs refs={t.news_ref} news={newsMap} onOpen={setOpenNewsId} />
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {p.portfolio_impact.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
                <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
                  <Wallet className="h-4 w-4 text-brand-primary" /> 持仓影响
                </h2>
                <ul className="space-y-3">
                  {p.portfolio_impact.map((h, i) => (
                    <li key={i} className="rounded-lg bg-slate-900/40 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-slate-200">
                          {h.name || h.symbol}
                        </span>
                        {h.share_pct != null && (
                          <span className="text-xs text-slate-500">占比 {h.share_pct.toFixed(1)}%</span>
                        )}
                        <Badge text={STANCE_LABELS[h.stance]} cls={STANCE_CLS[h.stance]} />
                      </div>
                      {h.comment && (
                        <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{h.comment}</p>
                      )}
                      <NewsRefs refs={h.news_ref} news={newsMap} onOpen={setOpenNewsId} />
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {p.action_items.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
                <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
                  <ListChecks className="h-4 w-4 text-profit" /> 操作参考
                </h2>
                <ul className="list-inside list-disc space-y-1.5 text-sm text-slate-300">
                  {p.action_items.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            )}

            {(p.next_focus || p.risk_warnings.length > 0) && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {p.next_focus && (
                  <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
                    <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                      <Lightbulb className="h-4 w-4 text-amber-400" /> 后续关注
                    </h2>
                    <p className="text-sm leading-relaxed text-slate-300">{p.next_focus}</p>
                  </div>
                )}
                {p.risk_warnings.length > 0 && (
                  <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
                    <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                      <ShieldAlert className="h-4 w-4 text-loss" /> 风险提示
                    </h2>
                    <ul className="list-inside list-disc space-y-1 text-sm text-slate-400">
                      {p.risk_warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <p className="text-center text-xs text-slate-600">{p.disclaimer}</p>
          </div>

          {/* 右栏：引用新闻详情 + 历史 */}
          <div className="space-y-4">
            {openNewsId != null && newsMap.get(openNewsId) && (
              <div className="rounded-xl border border-brand-primary/30 bg-card-bg p-4">
                <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                  <Newspaper className="h-4 w-4 text-brand-primary" /> 引用原文 #{openNewsId}
                </h2>
                <p className="text-sm font-medium text-slate-200">{newsMap.get(openNewsId)!.title}</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {newsMap.get(openNewsId)!.source} ·{' '}
                  {new Date(newsMap.get(openNewsId)!.published_at).toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                  })}
                </p>
                {newsMap.get(openNewsId)!.summary && (
                  <p className="mt-2 text-sm leading-relaxed text-slate-400">
                    {newsMap.get(openNewsId)!.summary}
                  </p>
                )}
                {newsMap.get(openNewsId)!.url && (
                  <a
                    href={newsMap.get(openNewsId)!.url!}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-1 text-xs text-brand-primary hover:underline"
                  >
                    查看原文 <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            )}

            <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
              <h2 className="mb-2 text-sm font-semibold">本时点历史（近 90 天）</h2>
              <ul className="max-h-[420px] space-y-1.5 overflow-y-auto">
                {slotHistory.map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => { setViewingId(r.id); setOpenNewsId(null) }}
                      className={cn(
                        'w-full rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                        r.id === report.id
                          ? 'bg-brand-primary/10 text-brand-primary'
                          : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <span>{r.trade_date}</span>
                        <span className="text-[11px] text-slate-500">
                          {new Date(r.created_at).toLocaleTimeString('zh-CN', {
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: false,
                          })}
                        </span>
                      </div>
                      <div className="mt-0.5 truncate text-xs text-slate-500">
                        {r.payload.market_summary}
                      </div>
                    </button>
                  </li>
                ))}
                {slotHistory.length === 0 && (
                  <li className="py-4 text-center text-xs text-slate-600">暂无记录</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
