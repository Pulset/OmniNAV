import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function fmtNumber(v: string | number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtPct(v: string | number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${(n * 100).toFixed(digits)}%`
}

/** 数值正负着色（涨绿跌红） */
export function pnlColor(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return 'text-slate-400'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (Number.isNaN(n) || n === 0) return 'text-slate-400'
  return n > 0 ? 'text-profit' : 'text-loss'
}

export const CLASS_LABELS: Record<string, string> = {
  STOCK: '股票',
  ETF: '基金/ETF',
  WEALTH: '银行理财',
  CASH: '现金',
}

export const MARKET_LABELS: Record<string, string> = {
  CN: 'A股',
  HK: '港股',
  US: '美股',
  GLOBAL: '全球',
}

export const TRANS_LABELS: Record<string, string> = {
  BUY: '买入',
  SELL: '卖出',
  DEPOSIT: '入金',
  WITHDRAW: '出金',
  DIVIDEND: '分红',
}

export const TRANS_COLORS: Record<string, string> = {
  BUY: 'text-brand-primary',
  SELL: 'text-amber-400',
  DEPOSIT: 'text-profit',
  WITHDRAW: 'text-orange-400',
  DIVIDEND: 'text-violet-400',
}
