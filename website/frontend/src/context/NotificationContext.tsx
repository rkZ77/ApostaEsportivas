import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import api from '../services/api'
import { useAuth } from './AuthContext'

const LS_KEY = 'lastSeenPickId'
// 60s: esse poll roda em TODA página do site pra todo usuário logado (não só
// na aba "Minhas Apostas"), então cada segundo a menos aqui multiplica pelo
// total de usuários ativos * jogos ao vivo. LivePicks.tsx tem seu próprio
// poll mais rápido quando a aba está de fato aberta.
const POLL_INTERVAL = 60_000

export type NotificationType = 'monthly_close' | 'new_picks' | 'pick_live' | 'pick_result'

export interface AppNotification {
  id: number
  type: NotificationType
  title: string
  body: string | null
  url: string | null
  payload: Record<string, any>
  read: boolean
  created_at: string | null
}

interface NotificationCtx {
  // Sino
  items: AppNotification[]
  unreadCount: number
  loading: boolean
  refresh: () => Promise<void>
  markRead: (id: number) => Promise<void>
  markAllRead: () => Promise<void>
  /** Fechamento do mês passado ainda não visto · é o que dispara o popup automático. */
  pendingMonthlyClose: AppNotification | null
  /** Abertura do fechamento mensal · usada pelo sino e pelo card da Banca. */
  monthlyCloseOpen: boolean
  openMonthlyClose: () => void
  closeMonthlyClose: () => void

  // Sinais legados (bolinha verde na navbar e badges em Picks.tsx)
  hasNew: boolean
  markSeen: () => void
  liveCount: number
  hasLive: boolean
  clearLive: () => void
}

const NotificationContext = createContext<NotificationCtx>({
  items: [],
  unreadCount: 0,
  loading: false,
  refresh: async () => {},
  markRead: async () => {},
  markAllRead: async () => {},
  pendingMonthlyClose: null,
  monthlyCloseOpen: false,
  openMonthlyClose: () => {},
  closeMonthlyClose: () => {},
  hasNew: false,
  markSeen: () => {},
  liveCount: 0,
  hasLive: false,
  clearLive: () => {},
})

function requestBrowserPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {})
  }
}

function sendBrowserNotification(count: number, teams: string) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  const notif = new Notification('Pick ao vivo!', {
    body: teams
      ? `${teams} está em andamento. Veja na aba Ao Vivo.`
      : `${count} pick${count > 1 ? 's' : ''} em andamento. Acesse a aba Ao Vivo.`,
    icon: '/logo.png',
    tag: 'live-picks',
    requireInteraction: false,
  })
  notif.onclick = () => { window.focus(); notif.close() }
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [items, setItems]     = useState<AppNotification[]>([])
  const [unreadCount, setUnread] = useState(0)
  const [loading, setLoading] = useState(false)
  const [hasNew, setHasNew]   = useState(false)
  const [liveCount, setLiveCount] = useState(0)
  const [hasLive, setHasLive] = useState(false)
  const latestIdRef = useRef(0)
  // IDs dos picks ao vivo já notificados nesta sessão
  const seenLiveIds = useRef<Set<string>>(new Set())

  // Lista do sino
  const refresh = useCallback(async () => {
    try {
      const r = await api.get('/notifications')
      setItems(r.data.items ?? [])
      setUnread(r.data.unread_count ?? 0)
    } catch {
      // Falha de rede não pode zerar a lista nem "queimar" nada: mantém o que
      // já está em tela e tenta de novo no próximo ciclo.
    }
  }, [])

  // Picks novos
  const checkNew = () => {
    const lastSeen = parseInt(localStorage.getItem(LS_KEY) ?? '0', 10)
    api.get('/suggestions/latest-pick')
      .then(r => {
        const id: number = r.data.id ?? 0
        latestIdRef.current = id
        if (id > lastSeen) setHasNew(true)
      })
      .catch(() => {})
  }

  // Picks ao vivo
  const checkLive = () => {
    api.get('/live/my-picks')
      .then(r => {
        const all: any[] = r.data ?? []
        const live = all.filter(p => p.is_live)
        setLiveCount(live.length)

        // Detecta picks que ficaram ao vivo agora (que não estavam antes)
        const newLive = live.filter(p => {
          const key = `${p.pick_type}-${p.pick_id}`
          return !seenLiveIds.current.has(key)
        })

        if (newLive.length > 0) {
          newLive.forEach(p => seenLiveIds.current.add(`${p.pick_type}-${p.pick_id}`))
          setHasLive(true)
          const teams = newLive.length === 1
            ? `${newLive[0].home_team} x ${newLive[0].away_team}`
            : ''
          sendBrowserNotification(newLive.length, teams)
        }
      })
      .catch(() => {})
  }

  useEffect(() => {
    if (!user) {
      setItems([])
      setUnread(0)
      setHasNew(false)
      setLiveCount(0)
      setHasLive(false)
      seenLiveIds.current = new Set()
      return
    }
    requestBrowserPermission()
    setLoading(true)
    refresh().finally(() => setLoading(false))
    checkNew()
    checkLive()
    // /live/my-picks é quem cria as notificações de "entrou em jogo" no
    // servidor, então o refresh do sino vem depois dele no mesmo ciclo.
    const timer = setInterval(() => { checkNew(); checkLive(); refresh() }, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [user, refresh])

  const markRead = useCallback(async (id: number) => {
    setItems(prev => prev.map(n => (n.id === id ? { ...n, read: true } : n)))
    setUnread(prev => Math.max(0, prev - 1))
    try { await api.post(`/notifications/${id}/read`) } catch { await refresh() }
  }, [refresh])

  const markAllRead = useCallback(async () => {
    setItems(prev => prev.map(n => ({ ...n, read: true })))
    setUnread(0)
    try { await api.post('/notifications/read-all') } catch { await refresh() }
  }, [refresh])

  const markSeen = () => {
    if (latestIdRef.current > 0) localStorage.setItem(LS_KEY, String(latestIdRef.current))
    setHasNew(false)
  }

  const clearLive = () => setHasLive(false)

  const pendingMonthlyClose = items.find(n => n.type === 'monthly_close' && !n.read) ?? null

  const [monthlyCloseOpen, setMonthlyCloseOpen] = useState(false)
  const openMonthlyClose  = useCallback(() => setMonthlyCloseOpen(true), [])
  const closeMonthlyClose = useCallback(() => setMonthlyCloseOpen(false), [])

  return (
    <NotificationContext.Provider value={{
      items, unreadCount, loading, refresh, markRead, markAllRead, pendingMonthlyClose,
      monthlyCloseOpen, openMonthlyClose, closeMonthlyClose,
      hasNew, markSeen, liveCount, hasLive, clearLive,
    }}>
      {children}
    </NotificationContext.Provider>
  )
}

export const useNotifications = () => useContext(NotificationContext)
