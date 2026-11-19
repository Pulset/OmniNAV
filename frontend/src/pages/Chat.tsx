import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Eraser, MessagesSquare, SendHorizontal } from 'lucide-react'
import { api, postStream } from '../api/client'
import type { ChatMessage } from '../api/types'
import { cn } from '../lib/format'

const EXAMPLES = [
  '我的组合现在最大的风险是什么？',
  '今天有什么消息会影响我的持仓？',
  '如果市场回调，我应该先减哪部分？',
]

// 回答为 Markdown：用 Tailwind 任意选择器统一暗色排版，不引 typography 插件
const MD_CLS =
  '[&_h1]:mt-2 [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-white' +
  ' [&_h2]:mt-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-white' +
  ' [&_h3]:mt-2 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-white' +
  ' [&_p]:my-1.5 [&_p]:first:mt-0 [&_p]:last:mb-0 [&_p]:whitespace-pre-wrap' +
  ' [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5' +
  ' [&_li]:my-0.5 [&_li]:pl-0.5' +
  ' [&_strong]:font-semibold [&_strong]:text-white' +
  ' [&_code]:rounded [&_code]:bg-slate-800 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[12px]' +
  ' [&_a]:text-brand-primary [&_a]:underline' +
  ' [&_blockquote]:border-l-2 [&_blockquote]:border-slate-700 [&_blockquote]:pl-3 [&_blockquote]:text-slate-400'

export function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api
      .get<ChatMessage[]>('/chat/messages?limit=200')
      .then((msgs) => {
        setMessages(msgs)
        setLoaded(true)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const send = useCallback(async () => {
    const question = input.trim()
    if (!question || streaming) return
    setInput('')
    setError('')
    setStreaming(true)
    setMessages((prev) => [
      ...prev,
      { id: -Date.now(), role: 'user', content: question, created_at: '' },
      { id: -Date.now() - 1, role: 'assistant', content: '', created_at: '' },
    ])
    try {
      await postStream('/chat/ask', { question }, (delta) => {
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, content: last.content + delta }
          return next
        })
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      // 失败时移除空的 assistant 占位气泡
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        return last?.role === 'assistant' && !last.content ? prev.slice(0, -1) : prev
      })
    } finally {
      setStreaming(false)
    }
  }, [input, streaming])

  const clear = async () => {
    if (!confirm('确定清空全部对话记录？')) return
    try {
      await api.delete('/chat/messages')
      setMessages([])
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const lastId = messages.length ? messages[messages.length - 1].id : null

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">AI 问答</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            基于实时新闻、行情与你的持仓回答决策问题 · 支持多轮追问
          </p>
        </div>
        <button
          onClick={() => void clear()}
          disabled={streaming || !messages.length}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800/60 hover:text-slate-200 disabled:opacity-40"
        >
          <Eraser className="h-3.5 w-3.5" />
          清空对话
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
          {error}
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {loaded && !messages.length && (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <MessagesSquare className="h-10 w-10 text-slate-700" />
            <div className="text-sm text-slate-500">问点什么吧，例如：</div>
            <div className="flex flex-col gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => {
                    setInput(ex)
                  }}
                  className="rounded-xl border border-slate-800 bg-card-bg px-4 py-2 text-xs text-slate-300 transition-colors hover:border-brand-primary/40 hover:text-brand-primary"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-xl rounded-br-sm bg-brand-primary/15 px-3.5 py-2.5 text-sm text-slate-100">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex justify-start">
              <div className="max-w-[92%] rounded-xl rounded-bl-sm border border-slate-800 bg-card-bg px-4 py-2.5 text-sm text-slate-200">
                {m.content ? (
                  <div className={MD_CLS}>
                    <ReactMarkdown>{m.content}</ReactMarkdown>
                  </div>
                ) : (
                  <span className="text-xs text-slate-500">正在结合持仓与新闻思考…</span>
                )}
                {streaming && m.id === lastId && m.content && (
                  <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-slate-400 align-middle" />
                )}
              </div>
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void send()
            }
          }}
          rows={2}
          placeholder="输入你的问题…（Enter 发送，Shift+Enter 换行）"
          disabled={streaming}
          className="min-h-0 flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-200 placeholder:text-slate-600 transition-colors focus:border-brand-primary focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={() => void send()}
          disabled={streaming || !input.trim()}
          className={cn(
            'flex items-center gap-1.5 rounded-xl bg-brand-primary px-3.5 py-2.5 text-sm font-medium text-white',
            'transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          <SendHorizontal className="h-4 w-4" />
          发送
        </button>
      </div>
      <div className="text-center text-[10px] text-slate-600">
        AI 生成，仅供参考，不构成投资建议
      </div>
    </div>
  )
}
