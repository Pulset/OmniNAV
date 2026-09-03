import { useEffect, useState } from 'react'
import { KeyRound, UserPlus } from 'lucide-react'
import { api } from '../api/client'
import type { User, UserRole } from '../api/types'

const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-brand-primary'

export function Users() {
  const [users, setUsers] = useState<User[]>([])
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [form, setForm] = useState({ username: '', password: '', role: 'member' as UserRole })
  const [resetId, setResetId] = useState<number | null>(null)
  const [resetPwd, setResetPwd] = useState('')

  const load = async () => {
    setUsers(await api.get<User[]>('/admin/users'))
  }

  useEffect(() => {
    void load().catch((e) =>
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }),
    )
  }, [])

  const create = async () => {
    try {
      await api.post('/admin/users', form)
      setMsg({ ok: true, text: `用户 ${form.username} 已创建` })
      setForm({ username: '', password: '', role: 'member' })
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  const toggleActive = async (u: User) => {
    setMsg(null)
    try {
      await api.patch(`/admin/users/${u.id}`, { is_active: !u.is_active })
      await load()
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  const doResetPassword = async (u: User) => {
    setMsg(null)
    try {
      await api.patch(`/admin/users/${u.id}`, { password: resetPwd })
      setMsg({ ok: true, text: `用户 ${u.username} 密码已重置，其全部会话已失效` })
      setResetId(null)
      setResetPwd('')
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">用户管理</h1>
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

      <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
        <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-300">
          <UserPlus className="h-4 w-4" /> 新建账号
        </h3>
        <div className="grid grid-cols-4 gap-2">
          <input
            className={inputCls}
            placeholder="用户名"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
          <input
            type="password"
            className={inputCls}
            placeholder="密码（至少 8 位）"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <select
            className={inputCls}
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}
          >
            <option value="member">成员</option>
            <option value="admin">管理员</option>
          </select>
          <button
            onClick={() => void create()}
            disabled={!form.username || form.password.length < 8}
            className="rounded-lg bg-brand-primary px-3 text-sm font-medium text-white disabled:opacity-40"
          >
            创建
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-card-bg p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              <th className="py-2">用户名</th>
              <th className="py-2">角色</th>
              <th className="py-2">状态</th>
              <th className="py-2">创建时间</th>
              <th className="py-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-slate-800/60">
                <td className="py-2 text-slate-200">{u.username}</td>
                <td className="py-2 text-slate-400">
                  {u.role === 'admin' ? '管理员' : '成员'}
                </td>
                <td className="py-2">
                  <span className={u.is_active ? 'text-profit' : 'text-slate-600'}>
                    {u.is_active ? '启用' : '停用'}
                  </span>
                </td>
                <td className="py-2 text-xs text-slate-500">
                  {new Date(u.created_at).toLocaleString('zh-CN')}
                </td>
                <td className="py-2">
                  <div className="flex items-center justify-end gap-2">
                    {resetId === u.id ? (
                      <>
                        <input
                          type="password"
                          className={inputCls + ' w-40 px-2 py-1 text-xs'}
                          placeholder="新密码（至少 8 位）"
                          value={resetPwd}
                          onChange={(e) => setResetPwd(e.target.value)}
                          autoFocus
                        />
                        <button
                          onClick={() => void doResetPassword(u)}
                          disabled={resetPwd.length < 8}
                          className="rounded-lg bg-brand-primary px-2 py-1 text-xs text-white disabled:opacity-40"
                        >
                          确认
                        </button>
                        <button
                          onClick={() => {
                            setResetId(null)
                            setResetPwd('')
                          }}
                          className="text-xs text-slate-500 hover:text-slate-300"
                        >
                          取消
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => setResetId(u.id)}
                          className="flex items-center gap-1 text-xs text-slate-500 hover:text-brand-primary"
                        >
                          <KeyRound className="h-3 w-3" /> 重置密码
                        </button>
                        {u.is_active ? (
                          <button
                            onClick={() => void toggleActive(u)}
                            className="text-xs text-slate-500 hover:text-loss"
                          >
                            停用
                          </button>
                        ) : (
                          <button
                            onClick={() => void toggleActive(u)}
                            className="text-xs text-slate-500 hover:text-profit"
                          >
                            启用
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="py-6 text-center text-xs text-slate-600">
                  暂无用户
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-slate-600">
          重置密码或停用后，该用户全部会话即时失效；不能停用自己的账号。
        </p>
      </div>
    </div>
  )
}
