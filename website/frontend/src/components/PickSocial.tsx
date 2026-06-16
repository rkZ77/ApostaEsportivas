import { useState, useEffect } from 'react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Avatar from './Avatar'

const REACTIONS = [
  {
    key: 'fire', label: 'Quente',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" />
      </svg>
    ),
  },
  {
    key: 'money', label: 'Confirmado',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    key: 'like', label: 'Boa pick',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
      </svg>
    ),
  },
  {
    key: 'doubt', label: 'Na dúvida',
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
]

const PLAN_BADGE: Record<string, string> = {
  vip:   'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  admin: 'text-purple-400 bg-purple-400/10 border-purple-400/20',
  free:  'text-zinc-400 bg-zinc-800 border-zinc-700',
}

interface Comment {
  id: number
  user_id: number
  user_name: string
  user_plan: string
  user_avatar_url?: string | null
  content: string
  created_at: string
}

interface SocialData {
  reactions: Record<string, number>
  user_reactions: string[]
  comments: Comment[]
}

export default function PickSocial({ pickId, pickType }: { pickId: number; pickType: string }) {
  const { user } = useAuth()
  const [data, setData]           = useState<SocialData | null>(null)
  const [loading, setLoading]     = useState(true)
  const [newComment, setNewComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]         = useState('')

  useEffect(() => {
    setLoading(true)
    api.get(`/social/${pickType}/${pickId}`)
      .then(r => setData(r.data))
      .catch(() => setData({ reactions: {}, user_reactions: [], comments: [] }))
      .finally(() => setLoading(false))
  }, [pickId, pickType])

  const toggleReaction = async (reaction: string) => {
    if (!data) return
    try {
      const r = await api.post(`/social/${pickType}/${pickId}/react`, { reaction })
      setData(prev => {
        if (!prev) return prev
        const reactions = { ...prev.reactions, [reaction]: r.data.count }
        const user_reactions = r.data.active
          ? [...prev.user_reactions, reaction]
          : prev.user_reactions.filter((x: string) => x !== reaction)
        return { ...prev, reactions, user_reactions }
      })
    } catch {}
  }

  const submitComment = async () => {
    const content = newComment.trim()
    if (!content || submitting) return
    setError('')
    setSubmitting(true)
    try {
      const r = await api.post(`/social/${pickType}/${pickId}/comment`, { content })
      setData(prev => prev ? { ...prev, comments: [...prev.comments, r.data] } : prev)
      setNewComment('')
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Erro ao comentar')
    } finally {
      setSubmitting(false)
    }
  }

  const deleteComment = async (commentId: number) => {
    try {
      await api.delete(`/social/comment/${commentId}`)
      setData(prev => prev ? { ...prev, comments: prev.comments.filter(c => c.id !== commentId) } : prev)
    } catch {}
  }

  if (loading) return (
    <div className="flex justify-center py-8">
      <div className="w-6 h-6 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div>
  )

  return (
    <div className="space-y-6">

      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3">Reações</p>
        <div className="flex flex-wrap gap-2">
          {REACTIONS.map(({ key, icon, label }) => {
            const active = data?.user_reactions.includes(key) ?? false
            const count  = data?.reactions[key] ?? 0
            return (
              <button
                key={key}
                onClick={() => toggleReaction(key)}
                className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-sm font-semibold transition-all ${
                  active
                    ? 'bg-green-500/15 border-green-500/40 text-green-400'
                    : 'bg-zinc-800/60 border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200'
                }`}
              >
                {icon}
                <span>{label}</span>
                {count > 0 && (
                  <span className={`text-xs font-black ${active ? 'text-green-400' : 'text-zinc-500'}`}>
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3">
          Comentários{data?.comments.length ? ` (${data.comments.length})` : ''}
        </p>

        {/* Input */}
        <div className="flex gap-2 mb-4">
          {user?.name && (
            <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" className="shrink-0 mt-1" />
          )}
          <div className="flex-1 flex gap-2">
            <input
              value={newComment}
              onChange={e => setNewComment(e.target.value.slice(0, 300))}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitComment() } }}
              placeholder="Comente sobre este pick... (Enter para enviar)"
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-green-500/50"
              disabled={submitting}
            />
            <button
              onClick={submitComment}
              disabled={!newComment.trim() || submitting}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-white text-sm font-bold transition-colors shrink-0"
            >
              {submitting ? '...' : 'Enviar'}
            </button>
          </div>
        </div>
        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        {/* Lista */}
        {!data?.comments.length ? (
          <div className="text-center py-8 text-zinc-600 text-xs">
            Seja o primeiro a comentar neste pick.
          </div>
        ) : (
          <div className="space-y-3">
            {data.comments.map(c => (
              <div key={c.id} className="flex gap-2.5">
                <Avatar name={c.user_name} imageUrl={c.user_avatar_url} size="sm" className="shrink-0 mt-0.5" />
                <div className="flex-1 bg-zinc-900 border border-zinc-800 rounded-xl px-3 py-2.5">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="text-xs font-bold text-white">{c.user_name}</span>
                    <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border ${PLAN_BADGE[c.user_plan] ?? PLAN_BADGE.free}`}>
                      {c.user_plan.toUpperCase()}
                    </span>
                    <span className="text-xs text-zinc-600 ml-auto">
                      {new Date(c.created_at).toLocaleString('pt-BR', {
                        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                      })}
                    </span>
                    {(user?.id === c.user_id || user?.plan === 'admin') && (
                      <button
                        onClick={() => deleteComment(c.id)}
                        className="text-zinc-700 hover:text-red-400 transition-colors text-sm ml-1 leading-none"
                        title="Deletar comentário"
                      >
                        ×
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-zinc-300 leading-relaxed">{c.content}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
