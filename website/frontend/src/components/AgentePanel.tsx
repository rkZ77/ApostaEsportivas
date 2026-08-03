import { useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import { Bot, X as XIcon, Send, Lock } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useAgentChat } from '../hooks/useAgentChat'
import Avatar from './Avatar'

const SUGGESTIONS = [
  'Quais os picks do site pra hoje?',
  'Como está minha banca de alavancagem?',
  'Como funciona a alavancagem?',
  'Jogos ao vivo agora',
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

/** Painel de chat compacto -- mesma lógica de /agente (useAgentChat), layout reduzido pra bolha
 * flutuante. Carregado via lazy() (react-markdown é pesado) só quando o usuário abre o chat. */
export default function AgentePanel({ onClose }: { onClose: () => void }) {
  const { user, isVip, isAdmin } = useAuth()
  const { messages, input, setInput, loading, statusText, sendMessage } = useAgentChat()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage().then(() => inputRef.current?.focus())
    }
  }

  const locked = !user || (!isVip && !isAdmin)

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92, y: 16 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: 10, transition: { duration: 0.15 } }}
      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
      style={{ bottom: 'calc(1.25rem + env(safe-area-inset-bottom))' }}
      className="fixed right-4 z-50 w-[calc(100vw-2rem)] max-w-sm h-[min(72vh,560px)] bg-surface-0 border border-line rounded-xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden origin-bottom-right"
    >
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-line flex items-center gap-2.5 bg-surface-1/60">
        <div className="w-8 h-8 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center shrink-0">
          <Bot className="w-4 h-4 text-green-400" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-black text-ink-1 leading-none truncate">Agente PickIA</p>
          <p className="text-[11px] text-ink-3 mt-1">{loading ? 'Analisando...' : 'Online'}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Fechar chat"
          className="w-8 h-8 flex items-center justify-center rounded-full text-ink-3 hover:text-ink-1 hover:bg-surface-2 transition-colors shrink-0"
        >
          <XIcon className="w-4 h-4" />
        </button>
      </div>

      {locked ? (
        <div className="flex-1 flex items-center justify-center px-6 text-center">
          <div>
            <div className="w-12 h-12 rounded-full bg-yellow-400/10 border border-yellow-400/20 flex items-center justify-center mx-auto mb-4">
              <Lock className="w-5 h-5 text-yellow-400" />
            </div>
            {!user ? (
              <>
                <p className="text-ink-1 font-bold text-sm mb-1.5">Entre na sua conta</p>
                <p className="text-ink-2 text-xs leading-relaxed mb-5">
                  Faça login pra conversar com o Agente IA sobre picks, banca e jogos ao vivo.
                </p>
                <Link to="/login" onClick={onClose} className="inline-block bg-green-500 hover:bg-green-400 text-black font-black px-5 py-2.5 rounded-md text-xs transition-colors">
                  Entrar
                </Link>
              </>
            ) : (
              <>
                <p className="text-ink-1 font-bold text-sm mb-1.5">Agente exclusivo VIP</p>
                <p className="text-ink-2 text-xs leading-relaxed mb-5">
                  Disponível apenas para assinantes VIP. Analisa picks, banca, alavancagem e jogos ao vivo em tempo real.
                </p>
                <Link to="/checkout" onClick={onClose} className="inline-block bg-yellow-400 hover:bg-yellow-300 text-black font-black px-5 py-2.5 rounded-md text-xs transition-colors">
                  Assinar VIP
                </Link>
              </>
            )}
          </div>
        </div>
      ) : (
        <>
          {/* Mensagens */}
          <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-3">
            {messages.length === 0 && (
              <div className="flex-1 flex flex-col items-center justify-center gap-4 py-4 text-center">
                <p className="text-ink-2 text-xs max-w-[220px]">
                  Pergunte sobre os picks do dia, sua banca, alavancagem ou jogos ao vivo.
                </p>
                <div className="grid grid-cols-1 gap-1.5 w-full">
                  {SUGGESTIONS.map(s => (
                    <button
                      key={s}
                      onClick={() => sendMessage(s)}
                      className="text-left px-3 py-2 rounded-md bg-surface-1 border border-line hover:border-green-500/40 hover:bg-surface-2 transition-colors text-xs text-ink-2"
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
                <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                  {msg.role === 'user' ? (
                    <div className="shrink-0 mt-0.5">
                      {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
                    </div>
                  ) : (
                    <div className="w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center shrink-0 text-[10px] font-bold text-green-400 mt-0.5">
                      AI
                    </div>
                  )}
                  <div className={`max-w-[82%] rounded-md px-3 py-2 text-xs leading-relaxed
                    ${msg.role === 'user'
                      ? 'bg-green-600 text-ink-1 rounded-tr-sm'
                      : 'bg-surface-1 border border-line rounded-tl-sm'}`}>
                    {msg.role === 'user' ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : isLoadingMsg && !msg.content ? (
                      <div className="text-ink-2 flex items-center gap-2">
                        <TypingDots />
                        {statusText && <span className="text-ink-3 text-[10px]">{statusText}</span>}
                      </div>
                    ) : (
                      <div className="prose prose-invert prose-xs max-w-none text-ink-2
                        prose-p:my-1 prose-pre:bg-surface-2 prose-pre:border prose-pre:border-line-strong
                        prose-pre:rounded-md prose-pre:text-[11px] prose-code:text-green-400
                        prose-code:bg-surface-2 prose-code:px-1 prose-code:rounded prose-strong:text-ink-1
                        prose-headings:text-ink-1">
                        <ReactMarkdown>{msg.content}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="shrink-0 border-t border-line px-3 py-2.5 flex gap-2 items-end bg-surface-1/40">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Pergunte algo..."
              rows={1}
              className="flex-1 bg-surface-1 border border-line-strong rounded-md px-3 py-2.5 text-xs text-ink-1 placeholder-ink-3 focus:outline-none focus:border-green-500/50 resize-none"
              style={{ minHeight: '38px', maxHeight: '90px' }}
              disabled={loading}
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || loading}
              aria-label="Enviar"
              className="w-9 h-9 rounded-md bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-ink-1 shrink-0"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>
        </>
      )}
    </motion.div>
  )
}
