import { useState } from 'react'
import { TrendingUp } from 'lucide-react'
import { api } from '../api/client'
import type { User } from '../api/types'

const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-brand-primary'

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    if (!username || !password || loading) return
    setLoading(true)
    setError('')
    try {
      const user = await api.post<User>('/auth/login', { username, password })
      onLogin(user)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-sm rounded-xl border border-slate-800 bg-card-bg p-6">
        <div className="mb-6 flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-brand-primary" />
          <div>
            <div className="text-lg font-bold tracking-wide">OmniNAV</div>
            <div className="text-[10px] text-slate-500">全资产净值化复盘</div>
          </div>
        </div>

        {error && (
          <div className="mb-3 rounded-lg border border-loss/40 bg-loss/10 p-3 text-sm text-loss">
            {error}
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs text-slate-500">用户名</label>
            <input
              className={inputCls}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">密码</label>
            <input
              type="password"
              className={inputCls}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void submit()}
            />
          </div>
          <button
            onClick={() => void submit()}
            disabled={!username || !password || loading}
            className="w-full rounded-lg bg-brand-primary py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            {loading ? '登录中…' : '登录'}
          </button>
        </div>
      </div>
    </div>
  )
}
