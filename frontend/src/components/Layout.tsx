import {
  BookOpen,
  Layers,
  LayoutDashboard,
  LogOut,
  ReceiptText,
  Settings2,
  TrendingUp,
  Users,
  Wallet,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { User } from '../api/types'
import { cn } from '../lib/format'
import { useSettings } from '../store/settings'

const NAV_ITEMS = [
  { key: 'dashboard', label: '总览', icon: LayoutDashboard },
  { key: 'assets', label: '资产', icon: Layers },
  { key: 'holdings', label: '持仓', icon: Wallet },
  { key: 'transactions', label: '流水', icon: ReceiptText },
  { key: 'review', label: '复盘', icon: BookOpen },
  { key: 'settings', label: '设置', icon: Settings2 },
] as const

const ADMIN_NAV_ITEMS = [{ key: 'users', label: '用户', icon: Users }] as const

export type PageKey =
  | (typeof NAV_ITEMS)[number]['key']
  | (typeof ADMIN_NAV_ITEMS)[number]['key']

interface Props {
  page: PageKey
  onNavigate: (page: PageKey) => void
  user: User
  onLogout: () => void
  children: ReactNode
}

export function Layout({ page, onNavigate, user, onLogout, children }: Props) {
  const { baseCurrency, setBaseCurrency } = useSettings()

  const logout = async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      /* 会话已失效也照常回到登录页 */
    }
    onLogout()
  }

  const navButtonCls = (active: boolean) =>
    cn(
      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
      active
        ? 'bg-brand-primary/15 text-brand-primary'
        : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
    )

  return (
    <div className="flex h-full">
      <aside className="flex w-52 shrink-0 flex-col border-r border-slate-800 bg-card-bg/60">
        <div className="flex items-center gap-2 px-5 py-5">
          <TrendingUp className="h-6 w-6 text-brand-primary" />
          <div>
            <div className="text-lg font-bold tracking-wide">OmniNAV</div>
            <div className="text-[10px] text-slate-500">全资产净值化复盘</div>
          </div>
        </div>

        <nav className="mt-2 flex flex-col gap-1 px-3">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => onNavigate(key)} className={navButtonCls(page === key)}>
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
          {user.role === 'admin' &&
            ADMIN_NAV_ITEMS.map(({ key, label, icon: Icon }) => (
              <button key={key} onClick={() => onNavigate(key)} className={navButtonCls(page === key)}>
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
        </nav>

        <div className="mt-auto p-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="min-w-0">
              <div className="truncate text-xs text-slate-300">{user.username}</div>
              <div className="text-[10px] text-slate-600">
                {user.role === 'admin' ? '管理员' : '成员'}
              </div>
            </div>
            <button
              onClick={() => void logout()}
              title="退出登录"
              className="rounded p-1 text-slate-600 hover:text-slate-300"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">
            基准币种
          </div>
          <div className="flex overflow-hidden rounded-lg border border-slate-700">
            {(['CNY', 'USD'] as const).map((c) => (
              <button
                key={c}
                onClick={() => setBaseCurrency(c)}
                className={cn(
                  'flex-1 py-1.5 text-xs font-medium transition-colors',
                  baseCurrency === c
                    ? 'bg-brand-primary text-white'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  )
}
