import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Bell, BellOff, CalendarCheck, CheckCheck, Radio, TrendingDown, TrendingUp, X, Zap,
} from 'lucide-react'
import { useNotifications, type AppNotification } from '../context/NotificationContext'
import { backdropFade, popIn, sheetUp } from '../lib/motion'

/** "agora", "12 min", "3 h", "ontem", "12/07" · compacto o bastante pro item da lista. */
function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (isNaN(then)) return ''
  const diffMin = Math.floor((Date.now() - then) / 60000)
  if (diffMin < 1)    return 'agora'
  if (diffMin < 60)   return `${diffMin} min`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24)     return `${diffH} h`
  if (diffH < 48)     return 'ontem'
  const d = new Date(then)
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
}

function NotificationIcon({ n }: { n: AppNotification }) {
  const base = 'w-4 h-4 shrink-0'
  if (n.type === 'monthly_close') return <CalendarCheck className={`${base} text-yellow-400`} />
  if (n.type === 'new_picks')     return <Zap className={`${base} text-green-400`} />
  if (n.type === 'pick_live')     return <Radio className={`${base} text-red-400`} />
  const result = String(n.payload?.result ?? '')
  const isLoss = result === 'RED' || result === 'HALF-LOSS'
  return isLoss
    ? <TrendingDown className={`${base} text-red-400`} />
    : <TrendingUp className={`${base} text-green-400`} />
}

interface ListProps {
  onNavigate: () => void
}

function NotificationList({ onNavigate }: ListProps) {
  const navigate = useNavigate()
  const { items, unreadCount, loading, markRead, markAllRead, openMonthlyClose } = useNotifications()

  const handleClick = (n: AppNotification) => {
    if (!n.read) markRead(n.id)
    onNavigate()
    // Fechamento mensal abre o resumo por cima da tela atual em vez de navegar:
    // é onde o usuário confirma a banca do mês novo.
    if (n.type === 'monthly_close') { openMonthlyClose(); return }
    if (n.url) navigate(n.url)
  }

  if (loading && items.length === 0) {
    return <p className="px-5 py-8 text-center text-sm text-ink-3">Carregando...</p>
  }

  if (items.length === 0) {
    return (
      <div className="px-5 py-10 flex flex-col items-center text-center gap-2">
        <BellOff className="w-7 h-7 text-ink-4" />
        <p className="text-sm text-ink-3">Nenhuma notificação por aqui ainda.</p>
        <p className="text-xs text-ink-4 leading-relaxed">
          Você recebe aviso dos picks do dia, dos jogos que começam e do resultado das suas entradas.
        </p>
      </div>
    )
  }

  return (
    <>
      {unreadCount > 0 && (
        <div className="px-4 py-2 border-b border-line flex justify-end">
          <button
            onClick={() => markAllRead()}
            className="flex items-center gap-1.5 text-[11px] font-bold text-ink-2 hover:text-ink-1 transition-colors"
          >
            <CheckCheck className="w-3.5 h-3.5" />
            Marcar todas como lidas
          </button>
        </div>
      )}
      <ul className="divide-y divide-line/70">
        {items.map(n => (
          <li key={n.id}>
            <button
              onClick={() => handleClick(n)}
              className={`w-full text-left px-4 py-3 flex gap-3 transition-colors hover:bg-surface-2/50 ${
                n.read ? '' : 'bg-green-500/[0.04]'
              }`}
            >
              <span className="mt-0.5"><NotificationIcon n={n} /></span>
              <span className="flex-1 min-w-0">
                <span className="flex items-baseline gap-2">
                  <span className={`text-sm leading-snug ${n.read ? 'text-ink-2' : 'text-ink-1 font-bold'}`}>
                    {n.title}
                  </span>
                  <span className="text-[10px] text-ink-4 ml-auto shrink-0">{timeAgo(n.created_at)}</span>
                </span>
                {n.body && (
                  <span className="block text-xs text-ink-3 leading-snug mt-0.5 break-words">{n.body}</span>
                )}
              </span>
              {!n.read && <span className="w-1.5 h-1.5 rounded-full bg-green-500 mt-2 shrink-0" />}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

export default function NotificationBell() {
  const { unreadCount, refresh } = useNotifications()
  const [open, setOpen] = useState(false)
  // lg é o mesmo corte que a Navbar usa pra trocar menu por sidebar
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia('(min-width: 1024px)').matches)

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // Bottom sheet aberta trava o scroll do body (mesmo padrão da sidebar)
  useEffect(() => {
    if (!open || isDesktop) return
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [open, isDesktop])

  const handleOpen = () => {
    setOpen(v => !v)
    if (!open) refresh()
  }

  const badge = unreadCount > 9 ? '9+' : String(unreadCount)

  return (
    <div className="relative">
      <button
        onClick={handleOpen}
        aria-label={unreadCount > 0 ? `Notificações (${unreadCount} não lidas)` : 'Notificações'}
        className="relative p-2 text-ink-2 hover:text-ink-1 transition-colors"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute top-0.5 right-0.5 min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-green-500 text-[9px] font-black text-surface-0 border border-surface-0">
            {badge}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (isDesktop ? (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              variants={popIn} initial="hidden" animate="visible" exit="exit"
              className="absolute right-0 top-full mt-2 w-[22rem] bg-surface-1 border border-line rounded-lg shadow-2xl z-50 overflow-hidden"
            >
              <div className="px-4 py-3 border-b border-line flex items-center justify-between">
                <p className="text-ink-1 text-sm font-black">Notificações</p>
                <button onClick={() => setOpen(false)} aria-label="Fechar" className="text-ink-3 hover:text-ink-1 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="max-h-[26rem] overflow-y-auto">
                <NotificationList onNavigate={() => setOpen(false)} />
              </div>
            </motion.div>
          </>
        ) : (
          <>
            <motion.div
              variants={backdropFade} initial="hidden" animate="visible" exit="exit"
              onClick={() => setOpen(false)}
              className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[9998]"
            />
            <motion.div
              variants={sheetUp} initial="hidden" animate="visible" exit="exit"
              className="fixed bottom-0 left-0 right-0 z-[9999] bg-surface-0 border-t border-line rounded-t-2xl max-h-[85dvh] flex flex-col"
            >
              <div className="px-5 pt-4 pb-3 flex items-center justify-between shrink-0">
                <p className="text-ink-1 text-base font-black">Notificações</p>
                <button
                  onClick={() => setOpen(false)}
                  aria-label="Fechar"
                  className="w-8 h-8 flex items-center justify-center rounded-full border border-line text-ink-3 hover:text-ink-1 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="overflow-y-auto pb-[env(safe-area-inset-bottom)]">
                <NotificationList onNavigate={() => setOpen(false)} />
              </div>
            </motion.div>
          </>
        ))}
      </AnimatePresence>
    </div>
  )
}
