import type { ReactNode } from 'react'
import { cn } from '../lib/format'

interface Props {
  label: string
  value: string
  sub?: ReactNode
  valueClassName?: string
}

export function MetricCard({ label, value, sub, valueClassName }: Props) {
  return (
    <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={cn('mt-1.5 truncate text-xl font-semibold tabular-nums sm:text-2xl', valueClassName)}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
    </div>
  )
}
