import { useRef, useEffect } from 'react'
import { Helmet } from 'react-helmet-async'
import { Zap, Lock } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import Navbar from '../components/Navbar'
import PageShell from '../components/PageShell'
import { EmptyState, LiveDot } from '../components/ui'
import Avatar from '../components/Avatar'
import BackButton from '../components/BackButton'
import { useAuth } from '../context/AuthContext'
import { useCookieBannerVisible } from '../hooks/useCookieBannerVisible'
import { useAgentChat } from '../hooks/useAgentChat'

const SUGGESTIONS = [
  'Quais os picks do site pra hoje?',
  'Como está minha banca de alavancagem?',
  'Qual o desempenho dos picks este mês?',
  'Como funciona a alavancagem?',
  'Jogos ao vivo agora',
  'Classificação do Brasileirão',
]

function TypingDots() {
  return (
    <span className="flex gap-1 items-center h-4">
      <span className="w-1.5 h-1.5 bg-ink-4 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1.5 h-1.5 bg-ink-4 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1.5 h-1.5 bg-ink-4 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </span>
  )
}

function AgentMessage({ content, loading, statusText }: { content: string; loading: boolean; statusText: string }) {
  if (loading && !content) {
    return (
      <div className="text-ink-2 text-sm flex items-center gap-2">
        <TypingDots />
        {statusText && <span className="text-ink-3 text-xs">{statusText}</span>}
      </div>
    )
  }

  return (
    <div className="prose prose-invert prose-sm max-w-none text-ink-2
      prose-p:my-1 prose-pre:bg-surface-2 prose-pre:border prose-pre:border-line-strong
      prose-pre:rounded-lg prose-pre:text-xs prose-code:text-green-400
      prose-code:bg-surface-2 prose-code:px-1 prose-code:rounded prose-strong:text-ink-1
      prose-headings:text-ink-1">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}

export default function Agente() {
  const { user, isVip, isAdmin } = useAuth()
  const { messages, input, setInput, loading, statusText, sendMessage: sendMessageBase } = useAgentChat()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const cookieBannerVisible = useCookieBannerVisible()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async (text?: string) => {
    await sendMessageBase(text)
    inputRef.current?.focus()
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
      <PageShell
        title="Agente IA"
        description="Converse com uma IA especialista em futebol sobre picks, banca e jogos ao vivo."
        noindex
        width="narrow"
        mainClassName="flex items-center"
      >
        <EmptyState
          Icon={Lock}
          title="Agente exclusivo VIP"
          description="O Agente IA analisa picks, banca, jogos ao vivo e responde qualquer dúvida em tempo real. Disponível apenas para assinantes VIP."
          action={{ children: 'Assinar VIP', to: '/checkout', variant: 'vip' }}
          className="w-full"
        />
      </PageShell>
    )
  }

  return (
    /* h-screen + overflow-hidden de propósito: o chat rola por dentro, não a
       página. Por isso esta tela não usa PageShell, que assume página que rola
       e termina em rodapé. */
    <div className="h-screen bg-surface-0 flex flex-col overflow-hidden">
      <Helmet>
        <title>Agente IA · Pick IA</title>
        <meta name="robots" content="noindex, nofollow" />
      </Helmet>
      <Navbar />

      {/* Header */}
      <div className="bg-surface-0 border-b border-line">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-3">
          <BackButton />
          <div className="w-9 h-9 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center shrink-0">
            <span className="text-accent text-sm font-bold">AI</span>
          </div>
          <div>
            <h1 className="font-display text-base font-semibold text-ink-1">Pick<span className="text-accent">IA</span> Agent</h1>
            <p className="text-ink-3 text-xs mt-0.5">Picks · Banca · Alavancagem · Jogos ao vivo</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <LiveDot tone={loading ? 'amber' : 'green'} />
            <span className="text-ink-3 text-xs">{loading ? 'Analisando...' : 'Online'}</span>
          </div>
        </div>
      </div>

      {/* Chat area */}
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-4 flex flex-col gap-4 overflow-y-auto min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center flex-1 gap-6 py-8">
            <div className="w-16 h-16 rounded-md bg-green-500/10 border border-green-500/20 flex items-center justify-center">
              <Zap className="w-8 h-8 text-green-400" />
            </div>
            <div className="text-center">
              <h2 className="text-ink-1 font-bold text-lg">Olá, {user?.name?.split(' ')[0]}!</h2>
              <p className="text-ink-3 text-sm mt-1 max-w-xs">
                Pergunte sobre os picks do dia, sua banca, alavancagem, desempenho do site, jogos ao vivo e muito mais.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="text-left px-4 py-3 rounded-md bg-surface-1 border border-line hover:border-green-500/40 hover:bg-surface-2 transition-all text-sm text-ink-2"
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
              <div className={`max-w-[80%] sm:max-w-[75%] rounded-md px-4 py-3 text-sm leading-relaxed
                ${msg.role === 'user'
                  ? 'bg-green-600 text-ink-1 rounded-tr-sm'
                  : 'bg-surface-1 border border-line rounded-tl-sm'}`}>
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
          e bloqueia cliques aqui · reserva espaço extra embaixo pra textarea ficar
          acima da área coberta pelo banner. */}
      <div className={`bg-surface-0 border-t border-line ${cookieBannerVisible ? 'pb-24 sm:pb-14' : ''}`}>
        <div className="max-w-3xl mx-auto px-4 py-3 flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Pergunte sobre picks, banca, jogos ao vivo... (Enter para enviar)"
            rows={1}
            className="flex-1 bg-surface-1 border border-line-strong rounded-md px-4 py-3 text-sm text-ink-1 placeholder-ink-3 focus:outline-none focus:border-green-500/50 resize-none"
            style={{ minHeight: '48px', maxHeight: '120px' }}
            disabled={loading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={!input.trim() || loading}
            className="w-12 h-12 rounded-md bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-ink-1 shrink-0"
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
        <p className="text-center text-ink-4 text-xs pb-2">Análises baseadas em dados reais da API-Football. Aposte com responsabilidade.</p>
      </div>
    </div>
  )
}
