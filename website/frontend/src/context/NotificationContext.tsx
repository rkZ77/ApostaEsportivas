import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import api from '../services/api'
import { useAuth } from './AuthContext'
import { ID_NOTIFICACAO_PLANO, adiarPlano, convitePlano, planoAdiado } from '../lib/planoUpsell'

const LS_KEY = 'lastSeenPickId'
// 60s: esse poll roda em TODA página do site pra todo usuário logado (não só
// na aba "Minhas Apostas"), então cada segundo a menos aqui multiplica pelo
// total de usuários ativos * jogos ao vivo. LivePicks.tsx tem seu próprio
// poll mais rápido quando a aba está de fato aberta.
const POLL_INTERVAL = 60_000

/* Espelha as constantes TYPE_* de backend/routers/notifications.py · manter em
   sincronia, senão o sino cai no ícone padrão (resultado de pick) para um tipo
   que não é resultado nenhum. */
export type NotificationType =
  /* `pick_live` e `live_novo` são eventos diferentes e por isso são dois
   * tipos: o primeiro é "o pick QUE VOCÊ SEGUIU entrou em jogo" (pessoal, só
   * existe pra quem apostou); o segundo é "o motor achou uma oportunidade
   * agora" (vale pra toda a base). Um tipo só faria o sino dizer "começou" pra
   * um pick que ninguém pegou ainda. */
  | 'monthly_close' | 'new_picks' | 'pick_live' | 'live_novo' | 'pick_result' | 'plan_expiring'
  | 'trial_ended' | 'vip_ended'
  /* Único tipo que NÃO vem do servidor. O convite de plano é um estado
     permanente da conta ("você está no free"), não um evento, então não existe
     linha em `notifications` para ele · criar uma por usuário seria inventar um
     evento que nunca aconteceu. Ele é montado aqui, no cliente, a partir do
     plano, e some quando o estado muda. Ver lib/planoUpsell.ts. */
  | 'plan_upsell'

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
  /** Acesso que acabou e ainda não foi visto · dispara o popup de conversão.
      Vale pro teste grátis e pro VIP vencido: o `type` do item é o que decide a
      cópia do modal. O "uma vez só" é do servidor (dedupe_key), e a regra muda
      entre os dois de propósito · fixa no teste, por ciclo no VIP. */
  pendingAccessEnded: AppNotification | null
  /** Pick ao vivo recém-publicado, para o aviso em tela. Null quando não há
      nada novo ou depois de dispensado. Ver components/LivePickToast. */
  livePickNovo: AppNotification | null
  dismissLivePickNovo: () => void
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
  pendingAccessEnded: null,
  livePickNovo: null,
  dismissLivePickNovo: () => {},
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

/* Pick NOVO do Motor Live · outro evento e outra urgência.
 *
 * A de cima avisa que um pick que o usuário JÁ SEGUIU entrou em jogo. Esta
 * avisa que o motor acabou de achar uma oportunidade · e o produto tem uma
 * janela de minutos, porque a odd vence. Por isso `requireInteraction`: a
 * notificação fica na bandeja até ele olhar, em vez de sumir sozinha em cinco
 * segundos como a outra.
 *
 * `tag` própria pelo mesmo motivo: com a tag da outra, um pick novo SUBSTITUIRIA
 * o aviso de "seu pick começou" na bandeja do sistema, e o usuário perderia um
 * dos dois sem nunca saber que existiu. */
function avisarPickNovoDoMotor(titulo: string, corpo?: string | null) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  const notif = new Notification(titulo, {
    body: corpo || 'O Motor Ao Vivo achou uma oportunidade. A odd vence em minutos.',
    icon: '/logo.png',
    tag: 'live-novo',
    requireInteraction: true,
  })
  notif.onclick = () => { window.focus(); notif.close() }
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { user, isAdmin, daysUntilExpiry } = useAuth()
  const [items, setItems]     = useState<AppNotification[]>([])
  const [unreadCount, setUnread] = useState(0)
  const [loading, setLoading] = useState(false)
  const [hasNew, setHasNew]   = useState(false)
  const [liveCount, setLiveCount] = useState(0)
  const [hasLive, setHasLive] = useState(false)
  const latestIdRef = useRef(0)
  // IDs dos picks ao vivo já notificados nesta sessão
  const seenLiveIds = useRef<Set<string>>(new Set())
  /* Pick ao vivo novo, para o aviso EM TELA (LivePickToast).
   *
   * A notificação do navegador só chega a quem deu permissão, e ela é
   * justamente a que a maioria nega · quem está com o site aberto ficava sem
   * saber de um pick que vence em minutos, enquanto olhava outra aba do
   * próprio site. Este estado é o mesmo evento, entregue por dentro. */
  const [livePickNovo, setLivePickNovo] = useState<AppNotification | null>(null)

  // Lista do sino
  const refresh = useCallback(async () => {
    try {
      const r = await api.get('/notifications')
      const novos: AppNotification[] = r.data.items ?? []

      /* O aviso de pick novo do Motor Live sai daqui e não de uma quarta
       * requisição: o item já vem nesta lista, criado no servidor quando
       * alguém abriu o feed (ver routers/live_picks.py::feed). O que falta é
       * levá-lo pra bandeja do sistema de quem NÃO está com a aba aberta.
       *
       * Só o que ainda não foi lido e ainda não foi avisado nesta sessão ·
       * `seenLiveIds` já existia pro outro evento e serve igual aqui. */
      for (const n of novos) {
        if (n.type !== 'live_novo' || n.read) continue
        const chave = `novo-${n.id}`
        if (seenLiveIds.current.has(chave)) continue
        seenLiveIds.current.add(chave)
        avisarPickNovoDoMotor(n.title, n.body)
        // O mais recente ganha a tela: são picks de janela curta, e empilhar
        // avisos de oportunidade que já venceram não ajuda ninguém.
        setLivePickNovo(n)
      }

      setItems(novos)
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
      setLivePickNovo(null)
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
    const ciclo = () => { checkNew(); checkLive(); refresh() }

    // ABA ESCONDIDA NÃO PESQUISA.
    //
    // Isto roda em TODA página pra todo usuário logado, e são três requisições
    // por ciclo. Uma aba deixada aberta em segundo plano (o caso comum: o
    // usuário abre o site, vai pro WhatsApp e volta depois do jogo) gastava
    // três requisições por minuto a noite inteira, cada uma passando pela
    // checagem de sessão no servidor. Nenhuma delas muda nada que o usuário
    // possa ver com a aba escondida.
    //
    // Ao voltar pra aba, pesquisa na hora · sem isso ele veria dado velho por
    // até um minuto justamente no momento em que está olhando.
    const timer = setInterval(() => { if (!document.hidden) ciclo() }, POLL_INTERVAL)
    const aoVoltar = () => { if (!document.hidden) ciclo() }
    document.addEventListener('visibilitychange', aoVoltar)

    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', aoVoltar)
    }
  }, [user, refresh])

  /*
   * Convite de plano no sino.
   *
   * Ele aparece como aviso de rodapé (PlanUpsellToast) e, dispensado, continua
   * aqui · era o pedido: não sumir de vez. Como não é evento, não vem do
   * servidor: é montado do plano da conta e entra no TOPO da lista, sempre não
   * lido, enquanto o estado valer.
   *
   * `planoAdiadoAgora` só serve para a lista reagir na hora em que alguém
   * dispensa: `planoAdiado()` lê localStorage, que não dispara render.
   */
  const [planoAdiadoAgora, setPlanoAdiadoAgora] = useState(() => planoAdiado())
  const convite = convitePlano(user, daysUntilExpiry, isAdmin)

  useEffect(() => { setPlanoAdiadoAgora(planoAdiado()) }, [user?.id, convite?.titulo])

  const itemDePlano: AppNotification | null = convite && !planoAdiadoAgora
    ? {
        id: ID_NOTIFICACAO_PLANO,
        type: 'plan_upsell',
        title: convite.titulo,
        body: convite.texto,
        url: convite.to,
        payload: {},
        read: false,
        created_at: null,
      }
    : null

  const itensComPlano = itemDePlano ? [itemDePlano, ...items] : items

  const markRead = useCallback(async (id: number) => {
    // O convite de plano não tem linha no servidor (ver 'plan_upsell' acima):
    // marcá-lo como lido é adiar por 24h aqui mesmo. Sem esta saída, o POST
    // iria para /notifications/-1 e o catch dispararia um refresh a cada
    // clique.
    if (id === ID_NOTIFICACAO_PLANO) {
      adiarPlano()
      setPlanoAdiadoAgora(true)
      return
    }
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

  /* Dispensar o aviso em tela NÃO marca a notificação como lida: ela continua
     no sino, que é o outro pedido. Fechar o toast é "vi o aviso", não "resolvi
     o assunto". */
  const dismissLivePickNovo = useCallback(() => setLivePickNovo(null), [])

  const pendingMonthlyClose = items.find(n => n.type === 'monthly_close' && !n.read) ?? null
  /* Os dois finais concorrem pelo mesmo popup, mas nunca coexistem numa conta
     no mesmo instante: o teste acaba uma vez na vida, e depois dele a pessoa
     só volta a perder acesso como VIP. `find` pega o primeiro não lido de
     qualquer um dos dois e o modal lê o `type` pra saber o que dizer. */
  const pendingAccessEnded  = items.find(
    n => (n.type === 'trial_ended' || n.type === 'vip_ended') && !n.read) ?? null

  const [monthlyCloseOpen, setMonthlyCloseOpen] = useState(false)
  const openMonthlyClose  = useCallback(() => setMonthlyCloseOpen(true), [])
  const closeMonthlyClose = useCallback(() => setMonthlyCloseOpen(false), [])

  return (
    <NotificationContext.Provider value={{
      items: itensComPlano, unreadCount: unreadCount + (itemDePlano ? 1 : 0),
      loading, refresh, markRead, markAllRead, pendingMonthlyClose,
      pendingAccessEnded,
      monthlyCloseOpen, openMonthlyClose, closeMonthlyClose,
      hasNew, markSeen, liveCount, hasLive, clearLive,
      livePickNovo, dismissLivePickNovo,
    }}>
      {children}
    </NotificationContext.Provider>
  )
}

export const useNotifications = () => useContext(NotificationContext)
