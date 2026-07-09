import { useState, useRef, useEffect } from 'react'
import { Zap } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import Navbar from '../components/Navbar'
import Avatar from '../components/Avatar'
import BackButton from '../components/BackButton'
import { useAuth } from '../context/AuthContext'
import { useCookieBannerVisible } from '../hooks/useCookieBannerVisible'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const SUGGESTIONS = [
  'Quais os picks do site pra hoje?',
  'Como está minha banca de alavancagem?',
  'Qual o desempenho dos picks este mês?',
  'Como funciona a alavancagem?',
  'Jogos ao vivo agora',
  'Classificação da Copa do Mundo 2026',
]

function TypingDots() {
  return (
    <span className="flex gap-1 items-center h-4">
      <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </span>
  )
}

function AgentMessage({ content, loading, statusText }: { content: string; loading: boolean; statusText: string }) {
  if (loading && !content) {
    return (
      <div className="text-zinc-400 text-sm flex items-center gap-2">
        <TypingDots />
        {statusText && <span className="text-zinc-500 text-xs">{statusText}</span>}
      </div>
    )
  }

  return (
    <div className="prose prose-invert prose-sm max-w-none text-zinc-200
      prose-p:my-1 prose-pre:bg-zinc-800 prose-pre:border prose-pre:border-zinc-700
      prose-pre:rounded-lg prose-pre:text-xs prose-code:text-green-400
      prose-code:bg-zinc-800 prose-code:px-1 prose-code:rounded prose-strong:text-white
      prose-headings:text-white">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}

export default function Agente() {
  const { user, isVip, isAdmin } = useAuth()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [statusText, setStatusText] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const cookieBannerVisible = useCookieBannerVisible()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || loading) return

    const userMsg: Message = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setLoading(true)
    setStatusText('')

    // Adiciona mensagem assistente vazia (mostrará loading)
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ messages: newMessages }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail ?? 'Erro na resposta do servidor')
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let started = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          let event: any
          try { event = JSON.parse(raw) } catch { continue }

          if (event.type === 'status') {
            setStatusText(event.text)
          } else if (event.type === 'chunk') {
            if (event.first) {
              setStatusText('')
              started = true
            }
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: updated[updated.length - 1].content + event.text,
              }
              return updated
            })
          } else if (event.type === 'done') {
            break
          }
        }
      }
    } catch (err: any) {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `Erro: ${err.message ?? 'Falha na conexão'}`,
        }
        return updated
      })
    } finally {
      setLoading(false)
      setStatusText('')
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const lastMsg = messages[messages.length - 1]
  const showLoading = loading && lastMsg?.role === 'assistant' && !lastMsg?.content

  if (!isVip && !isAdmin) {
    return (
      <div className="min-h-screen bg-black flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center px-4 py-16">
          <div className="text-center max-w-sm">
            <div className="w-16 h-16 rounded-full bg-yellow-400/10 border border-yellow-400/20 flex items-center justify-center mx-auto mb-5">
              <svg className="w-8 h-8 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <h2 className="text-white font-black text-xl mb-2">Agente exclusivo VIP</h2>
            <p className="text-zinc-400 text-sm mb-6 leading-relaxed">
              O Agente IA analisa picks, banca, jogos ao vivo e responde qualquer dúvida em tempo real. Disponível apenas para assinantes VIP.
            </p>
            <a href="/checkout" className="inline-block bg-yellow-400 hover:bg-yellow-300 text-black font-black px-8 py-3 rounded-xl transition-colors text-sm">
              Assinar VIP
            </a>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-black flex flex-col overflow-hidden">
      <Navbar />

      {/* Header */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-3">
          <BackButton />
          <div className="w-9 h-9 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center shrink-0">
            <span className="text-green-400 text-sm font-bold">AI</span>
          </div>
          <div>
            <h1 className="text-base font-black text-white">Pick<span className="text-green-500">IA</span> Agent</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Picks · Banca · Alavancagem · Jogos ao vivo</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${loading ? 'bg-yellow-500 animate-pulse' : 'bg-green-500'}`} />
            <span className="text-zinc-500 text-xs">{loading ? 'Analisando...' : 'Online'}</span>
          </div>
        </div>
      </div>

      {/* Chat area */}
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-4 flex flex-col gap-4 overflow-y-auto min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center flex-1 gap-6 py-8">
            <div className="w-16 h-16 rounded-2xl bg-green-500/10 border border-green-500/20 flex items-center justify-center">
              <Zap className="w-8 h-8 text-green-400" />
            </div>
            <div className="text-center">
              <h2 className="text-white font-bold text-lg">Olá, {user?.name?.split(' ')[0]}!</h2>
              <p className="text-zinc-500 text-sm mt-1 max-w-xs">
                Pergunte sobre os picks do dia, sua banca, alavancagem, desempenho do site, jogos ao vivo e muito mais.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="text-left px-4 py-3 rounded-xl bg-zinc-900 border border-zinc-800 hover:border-green-500/40 hover:bg-zinc-800 transition-all text-sm text-zinc-300"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => {
          const isLastAssistant = i === messages.length - 1 && msg.role === 'assistant'
          const isLoadingMsg = isLastAssistant && loading && !msg.content

          return (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
              {msg.role === 'user' ? (
                <div className="shrink-0 mt-0.5">
                  {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
                </div>
              ) : (
                <div className="w-7 h-7 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center shrink-0 text-xs font-bold text-green-400 mt-0.5">
                  AI
                </div>
              )}
              <div className={`max-w-[80%] sm:max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed
                ${msg.role === 'user'
                  ? 'bg-green-600 text-white rounded-tr-sm'
                  : 'bg-zinc-900 border border-zinc-800 rounded-tl-sm'}`}>
                {msg.role === 'user' ? (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                ) : (
                  <AgentMessage
                    content={msg.content}
                    loading={isLoadingMsg}
                    statusText={statusText}
                  />
                )}
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </main>

      {/* Input */}
      {/* Quando o CookieBanner (fixed bottom-0) ainda está visível, ele sobrepõe
          e bloqueia cliques aqui — reserva espaço extra embaixo pra textarea ficar
          acima da área coberta pelo banner. */}
      <div className={`bg-zinc-950 border-t border-zinc-800 ${cookieBannerVisible ? 'pb-24 sm:pb-14' : ''}`}>
        <div className="max-w-3xl mx-auto px-4 py-3 flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Pergunte sobre picks, banca, jogos ao vivo... (Enter para enviar)"
            rows={1}
            className="flex-1 bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-green-500/50 resize-none"
            style={{ minHeight: '48px', maxHeight: '120px' }}
            disabled={loading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={!input.trim() || loading}
            className="w-12 h-12 rounded-xl bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-white shrink-0"
          >
            {loading ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-center text-zinc-700 text-xs pb-2">Análises baseadas em dados reais da API-Football. Aposte com responsabilidade.</p>
      </div>
    </div>
  )
}
