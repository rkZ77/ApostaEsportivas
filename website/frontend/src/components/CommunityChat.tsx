import { useState, useEffect, useRef, useCallback } from 'react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Avatar from './Avatar'

const PLAN_BADGE: Record<string, string> = {
  vip:   'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  trial: 'text-green-400 bg-green-500/10 border-green-500/20',
  admin: 'text-purple-400 bg-purple-400/10 border-purple-400/20',
  free:  'text-zinc-500 bg-zinc-800/50 border-zinc-700',
}
const PLAN_LABEL: Record<string, string> = {
  vip: 'VIP', trial: 'TESTE', admin: 'ADMIN', free: 'FREE',
}

interface ChatMsg {
  id: number
  user_id: number
  user_name: string
  user_plan: string
  user_avatar_url?: string | null
  content: string
  created_at: string
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

function formatDateLabel(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  const isSameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  if (isSameDay(d, today)) return 'Hoje'
  if (isSameDay(d, yesterday)) return 'Ontem'
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })
}

export default function CommunityChat({ onLatestId }: { onLatestId?: (id: number) => void }) {
  const { user } = useAuth()
  const [messages, setMessages]   = useState<ChatMsg[]>([])
  const [input, setInput]         = useState('')
  const [sending, setSending]     = useState(false)
  const [sendError, setSendError] = useState('')
  const [connected, setConnected] = useState(false)
  const [online, setOnline]       = useState(0)
  const lastIdRef  = useRef(0)
  const bottomRef  = useRef<HTMLDivElement>(null)
  const inputRef   = useRef<HTMLTextAreaElement>(null)
  const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null)
  const onlinePoll = useRef<ReturnType<typeof setInterval> | null>(null)

  const scrollBottom = (force = false) => {
    if (!bottomRef.current) return
    const el = bottomRef.current.parentElement!
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (force || nearBottom) bottomRef.current.scrollIntoView({ behavior: 'smooth' })
  }

  const fetchOnline = useCallback(async () => {
    try {
      const r = await api.get('/social/chat/online')
      setOnline(r.data.count)
    } catch {}
  }, [])

  const fetchMessages = useCallback(async (initial = false) => {
    try {
      const r = await api.get('/social/chat/messages', {
        params: { after_id: initial ? 0 : lastIdRef.current, limit: initial ? 60 : 30 },
      })
      const newMsgs: ChatMsg[] = r.data
      if (newMsgs.length) {
        const latestId = newMsgs[newMsgs.length - 1].id
        lastIdRef.current = latestId
        onLatestId?.(latestId)
        setMessages(prev => {
          if (initial) return newMsgs
          const ids = new Set(prev.map(m => m.id))
          const fresh = newMsgs.filter(m => !ids.has(m.id))
          return fresh.length ? [...prev, ...fresh] : prev
        })
        if (!initial) setTimeout(() => scrollBottom(), 60)
      }
      setConnected(true)
    } catch {
      setConnected(false)
    }
  }, [onLatestId])

  useEffect(() => {
    fetchMessages(true).then(() => setTimeout(() => scrollBottom(true), 100))
    fetchOnline()
    pollRef.current    = setInterval(() => fetchMessages(), 5000)
    onlinePoll.current = setInterval(() => fetchOnline(), 30_000)
    return () => {
      if (pollRef.current)    clearInterval(pollRef.current)
      if (onlinePoll.current) clearInterval(onlinePoll.current)
    }
  }, [fetchMessages, fetchOnline])

  const sendMessage = async () => {
    const content = input.trim()
    if (!content || sending) return
    setSendError('')
    setSending(true)
    try {
      const r = await api.post('/social/chat/messages', { content })
      setMessages(prev => [...prev, r.data])
      lastIdRef.current = r.data.id
      onLatestId?.(r.data.id)
      setInput('')
      setTimeout(() => scrollBottom(true), 60)
    } catch (e: any) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail
      if (status === 429) setSendError('Muitas mensagens. Aguarde um momento.')
      else if (status === 401) setSendError('Sessão expirada. Faça login novamente.')
      else setSendError(detail ?? 'Erro ao enviar. Tente novamente.')
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  const deleteMsg = async (id: number) => {
    try {
      await api.delete(`/social/chat/${id}`)
      setMessages(prev => prev.filter(m => m.id !== id))
    } catch {}
  }

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  // Agrupa mensagens com separadores de data
  const items: ({ type: 'date'; label: string } | { type: 'msg'; msg: ChatMsg; index: number })[] = []
  let lastDate = ''
  messages.forEach((msg, i) => {
    const dateLabel = formatDateLabel(msg.created_at)
    if (dateLabel !== lastDate) {
      items.push({ type: 'date', label: dateLabel })
      lastDate = dateLabel
    }
    items.push({ type: 'msg', msg, index: i })
  })

  return (
    <div className="flex flex-col h-[600px] bg-zinc-950 rounded-2xl border border-zinc-800 overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-black text-white">Chat ao Vivo</span>
          <span className="text-xs text-zinc-500">· Comunidade Pick<span className="text-green-500">IA</span></span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
          <span className="text-xs text-zinc-500">
            {online > 0 ? `${online} online` : 'conectando...'}
          </span>
        </div>
      </div>

      {/* Aviso de regras */}
      <div className="px-4 py-2 bg-zinc-900/50 border-b border-zinc-800/50 shrink-0">
        <p className="text-xs text-zinc-600">
          Respeite todos os membros. Spam, links e promoções serão removidos pelo admin.
        </p>
      </div>

      {/* Mensagens */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-zinc-600 text-sm text-center">
              Seja o primeiro a mandar uma mensagem!<br />
              <span className="text-xs text-zinc-700">Os picks do dia acabaram de sair.</span>
            </p>
          </div>
        )}

        {items.map((item, idx) => {
          if (item.type === 'date') {
            return (
              <div key={`date-${idx}`} className="flex items-center gap-3 py-1">
                <div className="flex-1 h-px bg-zinc-800" />
                <span className="text-[11px] text-zinc-500 font-semibold shrink-0">
                  {item.label}
                </span>
                <div className="flex-1 h-px bg-zinc-800" />
              </div>
            )
          }

          const { msg: m, index: i } = item
          const isMe    = user?.id === m.user_id
          const isAdmin = m.user_plan === 'admin'
          const prev    = messages[i - 1]
          const samePrev = prev && prev.user_id === m.user_id &&
            (new Date(m.created_at).getTime() - new Date(prev.created_at).getTime()) < 90_000 &&
            formatDateLabel(m.created_at) === formatDateLabel(prev.created_at)

          return (
            <div key={m.id} className={`flex gap-2.5 group ${isMe ? 'flex-row-reverse' : ''}`}>
              {!samePrev ? (
                <Avatar name={m.user_name} imageUrl={m.user_avatar_url} size="sm" className="shrink-0 mt-0.5" />
              ) : (
                <div className="w-7 shrink-0" />
              )}

              <div className={`max-w-[75%] ${isMe ? 'items-end' : 'items-start'} flex flex-col gap-0.5`}>
                {!samePrev && (
                  <div className={`flex items-center gap-1.5 ${isMe ? 'flex-row-reverse' : ''}`}>
                    <span className={`text-xs font-bold ${isAdmin ? 'text-purple-400' : isMe ? 'text-green-400' : 'text-zinc-300'}`}>
                      {m.user_name}
                    </span>
                    <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border ${PLAN_BADGE[m.user_plan] ?? PLAN_BADGE.free}`}>
                      {PLAN_LABEL[m.user_plan] ?? 'FREE'}
                    </span>
                  </div>
                )}

                <div className="relative">
                  <div className={`px-3 py-2 rounded-2xl text-sm leading-relaxed ${
                    isMe
                      ? 'bg-green-600 text-white rounded-tr-sm'
                      : isAdmin
                      ? 'bg-purple-600/20 border border-purple-500/30 text-zinc-200 rounded-tl-sm'
                      : 'bg-zinc-800 text-zinc-200 rounded-tl-sm'
                  }`}>
                    {m.content}
                  </div>

                  {/* Timestamp sempre visível + delete no hover */}
                  <div className={`flex items-center gap-1 mt-0.5 ${isMe ? 'flex-row-reverse' : ''}`}>
                    <span className="text-[10px] text-zinc-600">
                      {formatTime(m.created_at)}
                    </span>
                    {(isMe || user?.plan === 'admin') && (
                      <button
                        onClick={() => deleteMsg(m.id)}
                        className="text-zinc-700 hover:text-red-400 transition-colors text-xs leading-none px-1 opacity-0 group-hover:opacity-100"
                        title={isMe ? 'Apagar minha mensagem' : 'Deletar mensagem'}
                      >
                        ×
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-zinc-800 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => { setInput(e.target.value.slice(0, 500)); if (sendError) setSendError('') }}
            onKeyDown={handleKey}
            placeholder="Mensagem... (Enter para enviar)"
            rows={1}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-green-500/50 resize-none"
            style={{ minHeight: 42, maxHeight: 96 }}
            disabled={sending}
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || sending}
            className="w-10 h-10 rounded-xl bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-white shrink-0"
          >
            {sending ? (
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        {sendError ? (
          <p className="text-[11px] text-red-400 mt-1.5 text-center">{sendError}</p>
        ) : (
          <p className="text-[10px] text-zinc-700 mt-1.5 text-center">
            {input.length > 0 ? `${input.length}/500` : 'Shift+Enter para nova linha'}
          </p>
        )}
      </div>
    </div>
  )
}
