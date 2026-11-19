export type AssetClass = 'STOCK' | 'ETF' | 'WEALTH' | 'CASH'
export type Market = 'CN' | 'HK' | 'US' | 'GLOBAL'
export type ValuationType = 'MARKET' | 'FIXED_YIELD' | 'MANUAL_NAV' | 'CASH'
export type TransType = 'BUY' | 'SELL' | 'DEPOSIT' | 'WITHDRAW' | 'DIVIDEND'
export type RuleType = 'DAILY_PCT_CHANGE' | 'DAILY_GAIN' | 'DAILY_LOSS' | 'DRAWDOWN'
export type BaseCurrency = 'CNY' | 'USD'
export type UserRole = 'admin' | 'member'

export interface User {
  id: number
  username: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface Notifications {
  feishu_webhook_url: string | null
  telegram_bot_token: string | null
  telegram_chat_id: string | null
}

export interface Asset {
  asset_id: string
  name: string
  asset_class: AssetClass
  market: Market
  currency: string
  valuation_type: ValuationType
  expected_apr: string
  created_at: string
}

export interface Transaction {
  id: number
  asset_id: string
  trans_type: TransType
  trans_date: string
  price: string
  quantity: string
  fee: string
  currency: string
  notes: string | null
  created_at: string
}

export interface Snapshot {
  snapshot_date: string
  total_market_value_cny: string
  unit_nav: string
  total_shares: string
  daily_pnl_cny: string
  daily_return: string
  csi300_nav: string | null
  sp500_nav: string | null
  nasdaq_nav: string | null
  review_notes: string | null
}

export interface Holding {
  asset_id: string
  name: string
  asset_class: AssetClass
  market: Market
  currency: string
  valuation_type: ValuationType
  quantity: string
  unit_price: string
  fx_rate: string
  market_value: string
  cost_basis: string
  unrealized_pnl: string
  unrealized_pnl_pct: string | null
  day_change_pct: string | null
  weight: string
}

export interface HoldingsResponse {
  base_currency: BaseCurrency
  as_of: string
  total_value: string
  total_cost: string
  holdings: Holding[]
  allocation_by_class: Record<string, string>
  allocation_by_market: Record<string, string>
}

export interface SnapshotBrief {
  date: string
  unit_nav: string
  daily_return: string
  daily_pnl_cny: string
  total_market_value_cny: string
  cumulative_return: string
}

export interface SummaryResponse {
  base_currency: BaseCurrency
  latest: SnapshotBrief | null
  prev: SnapshotBrief | null
  snapshot_count: number
}

export interface AlertRule {
  id: number
  asset_id: string | null
  rule_type: RuleType
  threshold: string
  is_active: boolean
}

export interface MetricsSummary {
  cumulative_return: number | null
  cagr: number | null
  sharpe: number | null
  max_drawdown: number | null
  volatility: number | null
  win_rate: number | null
  alpha_vs_csi300: number | null
  beta_vs_csi300: number | null
  days: number
}

export type AdviceSlot = 'morning' | 'midday' | 'evening'

export interface HotTopic {
  topic: string
  direction: 'positive' | 'negative' | 'neutral'
  affected: string[]
  reasoning: string
  news_ref: number[]
}

export interface PortfolioImpact {
  symbol: string
  name: string
  share_pct: number | null
  stance: 'hold' | 'watch' | 'consider_add' | 'consider_reduce'
  comment: string
  news_ref: number[]
}

export interface AdvicePayload {
  market_summary: string
  hot_topics: HotTopic[]
  portfolio_impact: PortfolioImpact[]
  action_items: string[]
  next_focus: string
  risk_warnings: string[]
  disclaimer: string
}

export interface AdviceReport {
  id: number
  trade_date: string
  slot: AdviceSlot
  model: string
  prompt_version: string
  payload: AdvicePayload
  cited_article_ids: number[]
  token_usage: Record<string, number>
  created_at: string
}

export interface NewsArticle {
  id: number
  source: string
  title: string
  summary: string | null
  url: string | null
  published_at: string
}

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  id: number
  role: ChatRole
  content: string
  created_at: string
}
