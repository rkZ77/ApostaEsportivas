import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { Plus, Play, AlertTriangle } from 'lucide-react'
import PageShell from '../components/PageShell'
import { Button, Modal, Spinner, SpinnerBlock } from '../components/ui'
import AdminShareResults from '../components/AdminShareResults'
import AdminIAPerformance from '../components/AdminIAPerformance'
import AdminMotorLive from '../components/AdminMotorLive'
import AdminDados from '../components/AdminDados'
import AdminPendencias from '../components/AdminPendencias'
import AdminEngajamento from '../components/AdminEngajamento'
import { fmtBRL } from '../utils/format'

interface User {
  id: number
  name: string
  email: string
  phone?: string | null
  plan: string
  subscription_type: string | null
  active: boolean
  expires_at: string | null
  created_at: string
  last_login_at: string | null
  bankroll_current: number | null
  unit_value: number | null
}

interface Stats {
  total: number
  vip: number
  trial: number
  free: number
  ativos: number
  vip_expirando: number
  ativos_hoje: number
  ativos_semana: number
  picks_hoje: {
    vip_picks: number
    alavancagem: number
    dica: number
    multiplas: number
  }
}

interface AIReviewStatus {
  config: { environment?: string; mode?: string; daily_limit?: number }
  summary: { reviews_24h?: number; rejected_24h?: number; cache_hits_24h?: number; reviews_today?: number }
  events: Array<{ pipeline: string; mode: string; provider: string; model: string; status: string; decision: string; risk_level: string | null; cached: boolean; review: { reasons?: string[] }; created_at: string }>
  migration_pending?: boolean
}

const SUBSCRIPTION_TYPES = [
  { value: '',           label: ''          },
  { value: 'mensal',     label: 'Mensal'     },
  { value: 'trimestral', label: 'Trimestral' },
  { value: 'semestral',  label: 'Semestral'  },
  { value: 'anual',      label: 'Anual'      },
]

const PLAN_FILTER = ['todos', 'free', 'trial', 'vip', 'admin'] as const
type PlanFilter = typeof PLAN_FILTER[number]

interface ContagemPick { n: number; pendentes: number }
interface Overview {
  usuarios: Record<string, number>
  picks_hoje: Record<string, ContagemPick>
  coleta: {
    jogos_hoje: number; jogos_por_comecar: number; jogos_com_odds: number
    ultimo_jogo_coletado: string | null
    ligas: number; times: number; estatisticas_jogador: number
  }
  financeiro: { receita_mes: number; pagamentos_mes: number }
  api_football: {
    plano: string | null; ativo: boolean | null; expira_em: string | null
    usado: number | null; limite: number | null; pct: number | null
  } | null
  pipeline: { status?: string; started_at?: string | null; finished_at?: string | null; error?: string | null }
}

interface Liga {
  league_id: number; name: string; season: number
  times: number; jogos_coletados: number; jogos_agendados: number
  /** null = ninguém marcou. Nesse estado a coleta roda completa. */
  temporada_iniciada: boolean | null
  /** false = só histórico. A linha fica na tabela pra o nome não sumir do site. */
  ativa: boolean
}

const PICK_LABEL: Record<string, string> = {
  vip: 'VIP', free: 'Dica do Dia', multiplas: 'Múltiplas',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
}

// Sub-paginas do /admin.
//
// A "Visão geral" foi dissolvida, e nao por gosto de arrumacao. Ela era um
// resumo de numeros que moram em outras abas, e o custo disso aparecia toda
// vez que algum deles estava errado: a cota da API ficava la', mas quem ia
// segurar a mao no pipeline estava na aba Pipeline; a contagem de picks do dia
// ficava la', mas quem ia resolver pendencia estava na aba Picks. Duas telas
// pra mesma pergunta, e a de resumo sempre um passo atras da de acao.
//
// Agora cada numero vive na aba onde se age sobre ele: cota e coleta no
// Pipeline, contagem do dia em Picks, receita em Financeiro. O cartao de
// "ultimo pipeline" nao mudou de casa, foi apagado -- a aba Pipeline ja diz
// isso por step, com log.
const ABAS = [
  { key: 'usuarios',   label: 'Usuários'    },
  { key: 'pipeline',   label: 'Pipeline'    },
  { key: 'live',       label: 'Ao Vivo'     },
  { key: 'ia',         label: 'IA'          },
  { key: 'financeiro', label: 'Financeiro'  },
  { key: 'picks',      label: 'Picks'       },
  { key: 'ligas',      label: 'Ligas'       },
  // Depois de Ligas de proposito: a pergunta "o motor esta enxergando?" quase
  // sempre termina em "qual liga nao coletou", que e' a aba ao lado.
  { key: 'dados',      label: 'Dados'       },
  { key: 'casas',      label: 'Casas'       },
] as const
type AdminAba = typeof ABAS[number]['key']

const planBadge = (plan: string) => {
  if (plan === 'vip')   return 'badge-vip'
  if (plan === 'trial') return 'badge-trial'
  if (plan === 'admin') return 'badge-admin'
  return 'badge-free'
}

const expiryWarning = (expires_at: string | null) => {
  if (!expires_at) return null
  const days = Math.ceil((new Date(expires_at).getTime() - Date.now()) / 86400000)
  if (days < 0)  return <span className="text-xs text-red-400 font-semibold">Expirado</span>
  if (days <= 7) return <span className="text-xs text-orange-400 font-semibold">{days}d</span>
  return null
}

export default function Admin() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const [users, setUsers]     = useState<User[]>([])
  const [stats, setStats]     = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [search, setSearch]   = useState('')
  const [planFilter, setPlanFilter] = useState<PlanFilter>('todos')
  const [newUser, setNewUser] = useState({ name: '', email: '', password: '', plan: 'free' })
  const [runningCmd, setRunningCmd] = useState<string | null>(null)
  const [pipelineStatus, setPipelineStatus] = useState<Record<string, { status: string; started_at: string | null; finished_at: string | null; error: string | null; log: string | null }>>({})
  const [aiReviewStatus, setAiReviewStatus] = useState<AIReviewStatus | null>(null)
  const [expandedLog, setExpandedLog] = useState<string | null>(null)
  const [payments, setPayments] = useState<any[]>([])
  const [paymentsLoading, setPaymentsLoading] = useState(false)
  const [paymentEvents, setPaymentEvents] = useState<any[]>([])
  const [sincronizando, setSincronizando] = useState(false)
  const [revenue, setRevenue] = useState<{
    total: number; count: number; avg_ticket: number; active_vip: number;
    monthly: { month: string; total: number; count: number }[];
    by_plan: { plan: string; total: number; count: number }[];
  } | null>(null)
  const [paymentsPage, setPaymentsPage] = useState(0)
  const [usersPage, setUsersPage] = useState(0)
  const [pickSearch, setPickSearch] = useState('')
  const [pickDateFrom, setPickDateFrom] = useState('')
  const [pickDateTo, setPickDateTo] = useState('')
  const [pickTypeFilter, setPickTypeFilter] = useState('')
  const [pickResults, setPickResults] = useState<any[]>([])
  const [pickSearching, setPickSearching] = useState(false)
  const [settingResult, setSettingResult] = useState<number | null>(null)
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const [acaoResultado, setAcaoResultado] = useState<'resolve' | 'reverify' | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [ligas, setLigas] = useState<Liga[] | null>(null)
  const [bookmakers, setBookmakers] = useState<{
    bookmaker_id: number; bookmaker_name: string; ativo: boolean
    created_at: string | null; n_odds: number; n_fixtures: number
  }[] | null>(null)
  const [bkLoading, setBkLoading] = useState(false)
  const [novoBookmaker, setNovoBookmaker] = useState({ bookmaker_id: '', bookmaker_name: '' })
  const [salvandoBk, setSalvandoBk] = useState(false)
  /** Liga no card de confirmação da coleta. null = card fechado. */
  const [confirmarColeta, setConfirmarColeta] = useState<Liga | null>(null)
  /** true entre o clique em "Coletar agora" e a resposta do POST. */
  const [disparando, setDisparando] = useState(false)
  const [novaLiga, setNovaLiga] = useState<{
    league_id: string; season: string; name: string
    temporada_iniciada: boolean | null
  }>({ league_id: '', season: String(new Date().getFullYear()), name: '', temporada_iniciada: null })
  const [salvandoLiga, setSalvandoLiga] = useState(false)
  const [verificando, setVerificando] = useState(false)
  /** Prévia da API antes de cadastrar: a temporada já começou, tem jogo? */
  const [previaLiga, setPreviaLiga] = useState<{
    existe: boolean; iniciada: boolean; total: number
    finalizados: number; agendados: number
    inicio?: string | null; fim?: string | null
    rodada_atual?: string | null; nome?: string | null; aviso?: string
  } | null>(null)
  // Hash da URL manda na aba inicial, pra dar pra abrir/recarregar direto em
  // /admin#usuarios. Hash invalido (inclusive o #visao dos favoritos antigos)
  // cai no Pipeline, que e' de onde se opera o dia.
  const [aba, setAba] = useState<AdminAba>(() => {
    const h = window.location.hash.replace('#', '') as AdminAba
    return ABAS.some(a => a.key === h) ? h : 'pipeline'
  })
  const USERS_PER_PAGE = 15
  const PAYMENTS_PER_PAGE = 10

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 3000)
  }

  const PIPELINE_ACTIONS = [
    { command: 'atualizar_jogos',      label: 'Atualizar Jogos'      },
    { command: 'capturar_odds',        label: 'Capturar Odds'        },
    { command: 'gerar_vip',            label: 'Gerar VIP'            },
    { command: 'gerar_free',           label: 'Gerar Free'           },
    { command: 'gerar_multipla',       label: 'Gerar Múltipla'       },
    { command: 'gerar_alavancagem',    label: 'Gerar Alavancagem'    },
    { command: 'gerar_faltas',         label: 'Gerar Faltas'         },
    { command: 'gerar_goleiros',       label: 'Gerar Defesas'        },
    { command: 'atualizar_resultados', label: 'Atualizar Resultados' },
  ] as const

  /* ── Motor Ao Vivo ──────────────────────────────────────────────────────
     Mudou de casa (16/08): virou aba própria em components/AdminMotorLive.
     Ficava aqui como um bloco entre outros seis da aba Pipeline, sem espaço
     pra mostrar o que a rodada produziu · e testar o motor é um ciclo
     (dispara · lê o log · vê os picks · liquida · confere a taxa) que não
     cabia num cartão. Continua fora do grid de PIPELINE_ACTIONS pelo motivo
     de sempre: o Live não é etapa do pipeline diário e não pode entrar no
     "Rodar Tudo" enquanto o consumo de API não estiver medido. */

  useEffect(() => {
    const poll = () => {
      api.get('/admin/pipeline-status').then(r => setPipelineStatus(r.data)).catch(() => {})
      api.get('/admin/ai-review-status').then(r => setAiReviewStatus(r.data)).catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  /* Log ao vivo · busca só o que chegou desde a última consulta (`desde`), em
     vez de rebaixar o log inteiro a cada segundo. `logCursor` num ref e não em
     estado porque ele muda a cada resposta e não deve provocar re-render por
     si só · quem redesenha é `logLinhas`. */
  const logCursor = useRef(0)
  const logFimRef = useRef<HTMLDivElement | null>(null)
  const [logLinhas, setLogLinhas] = useState<string[]>([])
  const [logAberto, setLogAberto] = useState(false)
  const [logAutoScroll, setLogAutoScroll] = useState(true)
  const [logCmd, setLogCmd] = useState('tudo')

  const abrirLog = (command: string) => {
    if (logAberto && logCmd === command) { setLogAberto(false); return }
    logCursor.current = 0
    setLogLinhas([])
    setLogCmd(command)
    setLogAberto(true)
  }

  useEffect(() => {
    if (!logAberto) return
    let vivo = true
    const buscar = async () => {
      try {
        const { data } = await api.get('/admin/pipeline-log', {
          params: { command: logCmd, desde: logCursor.current },
        })
        if (!vivo) return
        logCursor.current = data.proximo ?? 0
        if (data.linhas?.length) setLogLinhas(prev => [...prev, ...data.linhas].slice(-500))
      } catch { /* etapa que ainda não rodou não tem log · silêncio é a resposta certa */ }
    }
    buscar()
    const id = setInterval(buscar, 1500)
    return () => { vivo = false; clearInterval(id) }
  }, [logAberto, logCmd])

  useEffect(() => {
    if (logAutoScroll && logAberto) logFimRef.current?.scrollIntoView({ block: 'nearest' })
  }, [logLinhas, logAutoScroll, logAberto])

  const runPipeline = async (command: string) => {
    setRunningCmd(command)
    try {
      await api.post('/admin/run-pipeline', { command })
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Erro ao iniciar pipeline', false)
    } finally {
      setRunningCmd(null)
    }
  }

  const reload = () => {
    setLoading(true)
    api.get('/admin/users')
      .then(u => setUsers(u.data))
      .catch(() => setUsers([]))
      .finally(() => setLoading(false))
    api.get('/admin/stats')
      .then(s => setStats(s.data))
      .catch(() => {})
  }

  // Abrir a aba Picks ja com os ultimos 3 dias na tela. Antes ela abria em
  // branco e so' mostrava algo depois de preencher filtro e clicar buscar --
  // o caso comum e' justamente conferir o que saiu nos ultimos dias.
  const [picksCarregouInicial, setPicksCarregouInicial] = useState(false)
  useEffect(() => {
    if (aba !== 'picks' || picksCarregouInicial) return
    setPicksCarregouInicial(true)
    const iso = (diasAtras: number) => {
      const d = new Date()
      d.setDate(d.getDate() - diasAtras)
      return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo' }).format(d)
    }
    const de = iso(3), ate = iso(0)
    setPickDateFrom(de); setPickDateTo(ate)
    setPickSearching(true)
    api.get('/admin/picks/search', { params: { date_from: de, date_to: ate } })
      .then(r => setPickResults(r.data))
      .catch(() => {})
      .finally(() => setPickSearching(false))
  }, [aba, picksCarregouInicial])

  const carregarOverview = () => {
    api.get('/admin/overview').then(r => setOverview(r.data)).catch(() => {})
  }
  const carregarLigas = () => {
    api.get('/admin/leagues').then(r => setLigas(r.data)).catch(() => setLigas([]))
  }
  const carregarBookmakers = () => {
    setBkLoading(true)
    api.get('/admin/bookmakers').then(r => setBookmakers(r.data)).catch(() => setBookmakers([])).finally(() => setBkLoading(false))
  }

  /*
   * Recarrega a lista quando a coleta termina.
   *
   * Sem isto a linha continua mostrando "0 times · 0 jogos" depois de uma
   * coleta bem-sucedida, que é justamente a leitura que a pessoa abriu a tela
   * pra conferir · e o sintoma pareceria "a coleta não fez nada".
   */
  const statusColetaAnterior = useRef<string | undefined>(undefined)
  useEffect(() => {
    const atual = pipelineStatus['coletar_liga']?.status
    if (statusColetaAnterior.current === 'running' && atual && atual !== 'running') {
      carregarLigas()
    }
    statusColetaAnterior.current = atual
  }, [pipelineStatus])

  useEffect(() => {
    if (!isAdmin) { navigate('/picks'); return }
    carregarOverview()
    carregarLigas()
    carregarBookmakers()
    reload()
    setPaymentsLoading(true)
    api.get('/admin/payments').then(r => setPayments(r.data)).catch(() => {}).finally(() => setPaymentsLoading(false))
    api.get('/admin/revenue').then(r => setRevenue(r.data)).catch(() => {})
    api.get('/admin/payment-events').then(r => setPaymentEvents(r.data)).catch(() => {})
  }, [isAdmin])

  const setPlan = async (id: number, plan: string) => {
    try {
      await api.put(`/admin/users/${id}`, { plan })
      setUsers(u => u.map(x => x.id === id ? { ...x, plan } : x))
      showToast('Plano atualizado')
    } catch { showToast('Erro ao atualizar plano', false) }
  }

  const setSubscriptionType = async (id: number, subscription_type: string) => {
    try {
      await api.put(`/admin/users/${id}`, { subscription_type: subscription_type || null })
      setUsers(u => u.map(x => x.id === id ? { ...x, subscription_type: subscription_type || null } : x))
      showToast('Tipo salvo')
    } catch { showToast('Erro ao salvar tipo', false) }
  }

  const setExpiresAt = async (id: number, expires_at: string) => {
    try {
      await api.put(`/admin/users/${id}`, { expires_at: expires_at || null })
      setUsers(u => u.map(x => x.id === id ? { ...x, expires_at: expires_at || null } : x))
      showToast(expires_at ? 'Validade salva' : 'Validade removida')
    } catch { showToast('Erro ao salvar validade', false) }
  }

  const toggleActive = async (id: number, active: boolean) => {
    try {
      await api.put(`/admin/users/${id}`, { active: !active })
      setUsers(u => u.map(x => x.id === id ? { ...x, active: !active } : x))
      showToast(active ? 'Usuário desativado' : 'Usuário ativado')
    } catch { showToast('Erro ao alterar status', false) }
  }

  const deleteUser = async (id: number, name: string) => {
    if (!window.confirm(`Desativar usuário "${name}"?`)) return
    try {
      await api.delete(`/admin/users/${id}`)
      setUsers(u => u.map(x => x.id === id ? { ...x, active: false } : x))
      showToast('Usuário desativado')
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Erro ao desativar usuário', false)
    }
  }

  const searchPicks = async () => {
    setPickSearching(true)
    try {
      const params: Record<string, string> = {}
      if (pickSearch)     params.q         = pickSearch
      if (pickDateFrom)   params.date_from = pickDateFrom
      if (pickDateTo)     params.date_to   = pickDateTo
      if (pickTypeFilter) params.pick_type = pickTypeFilter
      const r = await api.get('/admin/picks/search', { params })
      setPickResults(r.data)
    } catch { showToast('Erro ao buscar picks', false) }
    finally { setPickSearching(false) }
  }

  const setPickResult = async (pick: any, result: string) => {
    setSettingResult(pick.id)
    try {
      await api.post('/admin/picks/set-result', {
        pick_type: pick.pick_type,
        pick_id: pick.id,
        result: result === 'pending' ? null : result,
      })
      setPickResults(prev => prev.map(p =>
        p.id === pick.id && p.pick_type === pick.pick_type
          ? { ...p, result: result === 'pending' ? null : result }
          : p
      ))
      showToast(`Resultado alterado para ${result === 'pending' ? 'Pendente' : result}`)
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Erro ao alterar resultado', false)
    } finally { setSettingResult(null) }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const { data } = await api.post('/admin/users', newUser)
      setUsers(u => [data, ...u])
      setNewUser({ name: '', email: '', password: '', plan: 'free' })
      setCreating(false)
      showToast('Usuário criado')
      reload()
    } catch (err: any) { showToast(err.response?.data?.detail || 'Erro ao criar usuário', false) }
  }

  const filtered = users.filter(u => {
    const q = search.toLowerCase()
    const matchSearch = !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    const matchPlan = planFilter === 'todos' || u.plan === planFilter
    return matchSearch && matchPlan
  })
  const usersTotalPages = Math.ceil(filtered.length / USERS_PER_PAGE)
  const usersPageSafe = Math.min(usersPage, Math.max(0, usersTotalPages - 1))
  const filteredPage = filtered.slice(usersPageSafe * USERS_PER_PAGE, (usersPageSafe + 1) * USERS_PER_PAGE)

  const paymentsTotalPages = Math.ceil(payments.length / PAYMENTS_PER_PAGE)
  const paymentsPageSafe = Math.min(paymentsPage, Math.max(0, paymentsTotalPages - 1))
  const paymentsPage_ = payments.slice(paymentsPageSafe * PAYMENTS_PER_PAGE, (paymentsPageSafe + 1) * PAYMENTS_PER_PAGE)

  if (loading) return (
    <PageShell title="Painel Admin" noindex width="full" footer={false}>
      <SpinnerBlock />
    </PageShell>
  )

  return (
    <PageShell
      title="Painel Admin"
      noindex
      width="full"
      bar={{
        back: '/picks',
        title: 'Painel Admin',
        sub: 'Gerenciar usuários e planos',
        actions: (
          <Button size="sm" Icon={Plus} onClick={() => setCreating(v => !v)}>
            Novo usuário
          </Button>
        ),
      }}
    >
      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] px-5 py-3 rounded-md shadow-elev text-sm font-semibold whitespace-nowrap transition-all ${toast.ok ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
          {toast.msg}
        </div>
      )}

        {/* Sub-paginas. A pagina inteira era uma coluna so' com 7 blocos
            empilhados -- no celular dava varias telas de rolagem ate chegar
            em usuarios, que e' o bloco mais usado. Hash na URL (#usuarios)
            pra poder abrir/recarregar direto numa aba, mesmo padrao da
            pagina de Picks. */}
        <div className="relative mb-6 -mx-4">
          <div className="pointer-events-none absolute right-0 top-0 h-full w-10 bg-gradient-to-l from-surface-0 to-surface-0/0 z-10" />
          <div className="flex border-b border-line px-4 overflow-x-auto scrollbar-none">
            {ABAS.map(a => (
              <button
                key={a.key}
                onClick={() => { setAba(a.key); window.location.hash = a.key }}
                className={`relative px-3 sm:px-4 py-3 text-xs sm:text-sm font-semibold mr-1 whitespace-nowrap flex-shrink-0 transition-colors ${
                  aba === a.key ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2'
                }`}
              >
                {a.label}
                <div className={`absolute left-0 right-0 -bottom-px h-0.5 ${aba === a.key ? 'bg-green-500' : 'bg-transparent'}`} />
              </button>
            ))}
          </div>
        </div>


        {aba === 'pipeline' && (<>
        {/* Cota da API-Football. Primeiro bloco de proposito: e' o recurso
            que ja parou o site inteiro por estouro, e o unico numero aqui
            que vem de fora e nao da' pra descobrir olhando o banco. */}
        {overview?.api_football && (
          <div className="card p-4 mb-4">
            <div className="flex items-center justify-between mb-2 gap-3">
              <h2 className="text-xs font-semibold text-ink-3">Cota da API-Football</h2>
              <span className={`text-[10px] font-black border px-1.5 py-0.5 rounded ${
                overview.api_football.ativo
                  ? 'text-green-400 bg-green-500/10 border-green-500/30'
                  : 'text-red-400 bg-red-500/10 border-red-500/30'
              }`}>
                {overview.api_football.plano ?? 'desconhecido'}
              </span>
            </div>
            <div className="flex items-baseline gap-2 font-mono">
              <span className={`text-3xl font-black ${
                (overview.api_football.pct ?? 0) >= 90 ? 'text-red-400'
                  : (overview.api_football.pct ?? 0) >= 70 ? 'text-orange-400' : 'text-green-400'
              }`}>{overview.api_football.usado ?? '·'}</span>
              <span className="text-ink-4 text-sm">/ {overview.api_football.limite ?? '·'} hoje</span>
            </div>
            <div className="mt-2 h-1.5 bg-surface-2 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${
                (overview.api_football.pct ?? 0) >= 90 ? 'bg-red-500'
                  : (overview.api_football.pct ?? 0) >= 70 ? 'bg-orange-500' : 'bg-green-500'
              }`} style={{ width: `${Math.min(100, overview.api_football.pct ?? 0)}%` }} />
            </div>
            {overview.api_football.expira_em && (
              <p className="text-[11px] text-ink-4 mt-2">
                Plano válido até {new Date(overview.api_football.expira_em).toLocaleDateString('pt-BR')}
              </p>
            )}
          </div>
        )}

        {/* Saúde da coleta. Sem isso, "não saiu pick hoje" fica
            indistinguível de "a coleta nem rodou". */}
        {overview?.coleta && (
          <div className="card p-4 mb-4">
            <h2 className="text-xs font-semibold text-ink-3 mb-3">Coleta</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { label: 'Jogos hoje',      value: overview.coleta.jogos_hoje },
                { label: 'Por começar',     value: overview.coleta.jogos_por_comecar },
                { label: 'Jogos com odds',  value: overview.coleta.jogos_com_odds },
                { label: 'Ligas',           value: overview.coleta.ligas },
                { label: 'Times',           value: overview.coleta.times },
                { label: 'Stats jogador',   value: overview.coleta.estatisticas_jogador },
              ].map(({ label, value }) => (
                <div key={label} className="bg-surface-1 rounded-md px-3 py-2.5 text-center">
                  <div className={`font-mono text-xl font-black ${value > 0 ? 'text-ink-1' : 'text-ink-4'}`}>{value}</div>
                  <div className="text-[10px] text-ink-3 mt-0.5">{label}</div>
                </div>
              ))}
            </div>
            {overview.coleta.ultimo_jogo_coletado && (
              <p className="text-[11px] text-ink-4 mt-3">
                Último jogo com estatística coletada:{' '}
                {new Date(overview.coleta.ultimo_jogo_coletado).toLocaleDateString('pt-BR')}
              </p>
            )}
            {overview.coleta.estatisticas_jogador === 0 && (
              <p className="text-[11px] text-orange-400 mt-1">
                Sem estatística por jogador, o pipeline de defesas de goleiro não gera pick até rodar a coleta.
              </p>
            )}
          </div>
        )}

        {/* Pipeline */}
        <div className="card p-4 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold text-ink-3">Pipeline</h2>
            {(() => {
              const s = pipelineStatus['tudo']
              const isTudoRunning = runningCmd === 'tudo' || s?.status === 'running'
              return (
                <div className="flex flex-col items-end gap-1">
                  <Button
                    size="sm"
                    Icon={Play}
                    loading={isTudoRunning}
                    disabled={runningCmd !== null}
                    onClick={() => runPipeline('tudo')}
                  >
                    {isTudoRunning ? 'Rodando tudo...' : 'Rodar tudo'}
                  </Button>
                  {s && (
                    <span
                      className={`text-[10px] cursor-pointer underline ${s.status === 'error' ? 'text-red-500' : 'text-ink-4'}`}
                      onClick={() => setExpandedLog(expandedLog === 'tudo' ? null : 'tudo')}
                    >
                      {s.status === 'running' ? 'rodando...' : `último: ${s.finished_at ?? 's/d'}`}
                    </span>
                  )}
                  {expandedLog === 'tudo' && (s?.error || s?.log) && (
                    <pre className={`text-[10px] bg-surface-1 rounded p-2 max-w-sm whitespace-pre-wrap break-all overflow-y-auto max-h-40 ${s.status === 'error' ? 'text-red-400' : 'text-ink-2'}`}>
                      {s.error || s.log}
                    </pre>
                  )}
                  <button
                    onClick={() => abrirLog('tudo')}
                    className="text-[10px] text-ink-4 underline hover:text-ink-2"
                  >
                    {logAberto && logCmd === 'tudo' ? 'esconder log ao vivo' : 'acompanhar log ao vivo'}
                  </button>
                </div>
              )
            })()}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
            {PIPELINE_ACTIONS.map(({ command, label }, idx) => {
              const s = pipelineStatus[command]
              const isRunning = runningCmd === command || s?.status === 'running'
              const borderCls = !s ? 'border-line'
                : s.status === 'running' ? 'border-yellow-500/50'
                : s.status === 'ok'      ? 'border-green-500/40'
                : 'border-red-500/50'
              const bgCls = !s ? ''
                : s.status === 'running' ? 'bg-yellow-500/5'
                : s.status === 'ok'      ? 'bg-green-500/5'
                : 'bg-red-500/5'
              return (
                <div key={command} className={`rounded-md border ${borderCls} ${bgCls} p-3 flex flex-col gap-2 transition-colors`}>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-ink-4 font-mono font-bold">{String(idx + 1).padStart(2, '0')}</span>
                    {!s                    && <span className="w-2 h-2 rounded-full bg-surface-3" />}
                    {s?.status === 'running' && <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />}
                    {s?.status === 'ok'      && <span className="w-2 h-2 rounded-full bg-green-500" />}
                    {s?.status === 'error'   && <span className="w-2 h-2 rounded-full bg-red-500" />}
                  </div>
                  <p className="text-xs font-semibold text-ink-2 leading-tight">{label}</p>
                  {s && !isRunning && (
                    <p
                      className={`text-[10px] cursor-pointer truncate ${s.status === 'error' ? 'text-red-400 underline' : 'text-ink-4'}`}
                      onClick={() => setExpandedLog(expandedLog === command ? null : command)}
                    >
                      {s.status === 'error'
                        ? <span className="inline-flex items-center gap-1"><AlertTriangle className="w-2.5 h-2.5" /> ver log</span>
                        : s.finished_at ?? ''}
                    </p>
                  )}
                  <button
                    onClick={() => runPipeline(command)}
                    disabled={runningCmd !== null || isRunning}
                    className="mt-auto text-[10px] px-2 py-1 rounded-md border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 transition-colors duration-1 ease-smooth disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center gap-1"
                  >
                    {isRunning
                      ? <><Spinner size="sm" className="w-2.5 h-2.5" tone="ink" /> rodando</>
                      : <><Play className="w-2.5 h-2.5" /> rodar</>}
                  </button>
                  {expandedLog === command && (s?.error || s?.log) && (
                    <pre className={`text-[10px] bg-surface-0 rounded p-2 whitespace-pre-wrap break-all overflow-y-auto max-h-40 ${s.status === 'error' ? 'text-red-400' : 'text-ink-2'}`}>
                      {s.error || s.log}
                    </pre>
                  )}
                  {isRunning && (
                    <button
                      onClick={() => abrirLog(command)}
                      className="text-[10px] text-ink-4 underline hover:text-ink-2"
                    >
                      {logAberto && logCmd === command ? 'esconder log' : 'ver ao vivo'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>

          {/* ── Log ao vivo ──────────────────────────────────────────────
              Só admin: a saída crua dos scripts carrega host de banco, liga em
              coleta, contagem de requisição de API e traceback inteiro quando
              quebra. A tela de espera do assinante continua em
              /pipeline-status-public, que mostra só o rótulo da etapa. */}
          {logAberto && (
            <div className="mt-4 border border-line rounded-md overflow-hidden">
              <div className="flex items-center justify-between gap-3 px-3 py-2 bg-surface-2 border-b border-line">
                <div className="flex items-center gap-2 min-w-0">
                  {pipelineStatus[logCmd]?.status === 'running'
                    ? <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse shrink-0" />
                    : <span className="w-2 h-2 rounded-full bg-surface-3 shrink-0" />}
                  <span className="text-[11px] font-semibold text-ink-2 truncate">
                    {logCmd === 'tudo'
                      ? 'Pipeline completo'
                      : (PIPELINE_ACTIONS.find(a => a.command === logCmd)?.label ?? logCmd)}
                  </span>
                  <span className="text-[10px] text-ink-4 shrink-0">{logLinhas.length} linha(s)</span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <label className="text-[10px] text-ink-4 flex items-center gap-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={logAutoScroll}
                      onChange={e => setLogAutoScroll(e.target.checked)}
                      className="accent-current w-3 h-3"
                    />
                    seguir
                  </label>
                  <button onClick={() => setLogAberto(false)}
                          className="text-[10px] text-ink-4 underline hover:text-ink-2">
                    fechar
                  </button>
                </div>
              </div>
              <div className="bg-surface-0 max-h-72 overflow-y-auto px-3 py-2">
                {logLinhas.length === 0 ? (
                  <p className="text-[11px] text-ink-4 py-2">
                    {pipelineStatus[logCmd]?.status === 'running'
                      ? 'Aguardando a primeira linha...'
                      : 'Sem log. Rode a etapa para acompanhar aqui.'}
                  </p>
                ) : (
                  <pre className="text-[10px] leading-relaxed text-ink-2 font-mono whitespace-pre-wrap break-all">
                    {logLinhas.map((l, i) => (
                      <div key={i} className={l.startsWith('!') ? 'text-red-400' : undefined}>{l}</div>
                    ))}
                  </pre>
                )}
                <div ref={logFimRef} />
              </div>
            </div>
          )}
        </div>


        {/* Revisão IA · contadores ao vivo enquanto o pipeline roda. A leitura
            de desempenho por modelo (e a lista de pareceres) mora na aba IA,
            que é onde ela é analisada com calma. */}
        <div className="card p-4 mb-6">
          <div className="flex items-center justify-between mb-3 gap-3">
            <div className="min-w-0">
              <h2 className="text-xs font-semibold text-ink-3">Revisão por IA</h2>
              <p className="text-[11px] text-ink-4 mt-1">
                {aiReviewStatus?.migration_pending ? 'Aguardando a primeira migração do pipeline.' :
                  `${aiReviewStatus?.config?.mode ?? 'off'} · ${aiReviewStatus?.config?.environment ?? 'prod'} · limite ${aiReviewStatus?.config?.daily_limit ?? 0}/dia`}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => { setAba('ia'); window.location.hash = 'ia' }}
                className="text-[10px] px-2 py-1 rounded-md border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 transition-colors"
              >
                analisar por modelo
              </button>
              <span className={`text-xs font-bold px-2 py-1 rounded ${aiReviewStatus?.config?.mode === 'enforce' ? 'bg-orange-500/15 text-orange-300' : 'bg-blue-500/15 text-blue-300'}`}>
                {aiReviewStatus?.config?.mode === 'enforce' ? 'VETO ATIVO' : 'SOMBRA'}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              ['Hoje', aiReviewStatus?.summary?.reviews_today ?? 0],
              ['24h', aiReviewStatus?.summary?.reviews_24h ?? 0],
              ['Vetos 24h', aiReviewStatus?.summary?.rejected_24h ?? 0],
              ['Cache 24h', aiReviewStatus?.summary?.cache_hits_24h ?? 0],
            ].map(([label, value]) => <div key={String(label)} className="rounded bg-surface-1 px-3 py-2">
              <p className="text-[10px] text-ink-4">{label}</p><p className="text-lg font-bold text-ink-1">{value}</p>
            </div>)}
          </div>
        </div>
        </>)}

        {aba === 'live' && <AdminMotorLive />}

        {aba === 'dados' && <AdminDados />}

        {aba === 'ia' && <AdminIAPerformance status={aiReviewStatus} />}

        {aba === 'financeiro' && (<>
        {/* Receita do mês · era o único número financeiro que morava fora
            desta aba. */}
        {overview?.financeiro && (
          <div className="card p-4 mb-4">
            <h2 className="text-xs font-semibold text-ink-3 mb-2">Receita do mês</h2>
            <div className="font-mono text-3xl font-black text-green-400">{fmtBRL(overview.financeiro.receita_mes)}</div>
            <p className="text-[11px] text-ink-4 mt-1">{overview.financeiro.pagamentos_mes} pagamento(s) aprovado(s)</p>
          </div>
        )}
        {/* Financeiro */}
        {revenue && (
          <div className="mb-6">
            <h2 className="text-xs font-semibold text-ink-3 mb-3">Financeiro</h2>

            {/* KPIs */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              {[
                { label: 'Receita Total',    value: fmtBRL(revenue.total),        color: 'text-green-400' },
                { label: 'Assinaturas',      value: String(revenue.count),        color: 'text-ink-1'    },
                { label: 'Ticket Médio',     value: fmtBRL(revenue.avg_ticket),   color: 'text-blue-400' },
                { label: 'VIPs Ativos Agora',value: String(revenue.active_vip),                                                   color: 'text-yellow-400' },
              ].map(({ label, value, color }) => (
                <div key={label} className="stat-card text-center py-4">
                  <div className={`font-mono text-2xl font-black ${color}`}>{value}</div>
                  <div className="text-xs text-ink-3 mt-1">{label}</div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Receita por mês */}
              <div className="card overflow-hidden lg:col-span-2">
                <div className="px-4 py-3 border-b border-line">
                  <span className="text-xs font-semibold text-ink-3">Receita por mês (últimos 12)</span>
                </div>
                {revenue.monthly.length === 0 ? (
                  <p className="text-center text-ink-4 text-sm py-6">Sem dados.</p>
                ) : (() => {
                  const maxTotal = Math.max(...revenue.monthly.map(m => m.total), 1)
                  return (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-line">
                            <th className="text-left text-ink-3 font-medium px-4 py-2">Mês</th>
                            <th className="text-left text-ink-3 font-medium px-4 py-2">Receita</th>
                            <th className="text-left text-ink-3 font-medium px-4 py-2">Vendas</th>
                            <th className="w-32 px-4 py-2"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {revenue.monthly.map(m => {
                            const [y, mo] = m.month.split('-')
                            const label = new Date(Number(y), Number(mo) - 1).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' })
                            const pct = (m.total / maxTotal) * 100
                            return (
                              <tr key={m.month} className="border-b border-line/40 hover:bg-surface-1/40">
                                <td className="px-4 py-2.5 text-ink-2 font-medium capitalize">{label}</td>
                                <td className="px-4 py-2.5 text-green-400 font-semibold font-mono">
                                  {fmtBRL(m.total)}
                                </td>
                                <td className="px-4 py-2.5 text-ink-2 font-mono">{m.count}</td>
                                <td className="px-4 py-2.5">
                                  <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
                                    <div className="h-full bg-green-500 rounded-full transition-all" style={{ width: `${pct}%` }} />
                                  </div>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )
                })()}
              </div>

              {/* Por plano */}
              <div className="card overflow-hidden">
                <div className="px-4 py-3 border-b border-line">
                  <span className="text-xs font-semibold text-ink-3">Por plano</span>
                </div>
                {revenue.by_plan.length === 0 ? (
                  <p className="text-center text-ink-4 text-sm py-6">Sem dados.</p>
                ) : (() => {
                  const planColors: Record<string, string> = {
                    mensal: 'text-blue-400', trimestral: 'text-purple-400',
                    semestral: 'text-orange-400', anual: 'text-green-400',
                  }
                  const maxTotal = Math.max(...revenue.by_plan.map(p => p.total), 1)
                  return (
                    <div className="p-4 space-y-4">
                      {revenue.by_plan.map(p => {
                        const pct = (p.total / maxTotal) * 100
                        const color = planColors[p.plan] ?? 'text-ink-2'
                        return (
                          <div key={p.plan}>
                            <div className="flex items-center justify-between mb-1">
                              <span className={`text-xs font-bold capitalize ${color}`}>{p.plan}</span>
                              <div className="font-mono text-right">
                                <span className="text-xs text-ink-1 font-semibold">{fmtBRL(p.total)}</span>
                                <span className="text-[10px] text-ink-4 ml-1">({p.count}x)</span>
                              </div>
                            </div>
                            <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
                              <div className="h-full bg-green-500/60 rounded-full" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}
              </div>
            </div>
          </div>
        )}

        {/* Pagamentos */}
        <div className="card overflow-hidden mb-6">
          <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3 flex-wrap">
            <h2 className="text-xs font-semibold text-ink-3">Pagamentos</h2>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-ink-4">{payments.length} registro(s)</span>
              {/* Rede de segurança do dinheiro: pergunta ao MercadoPago quais
                  assinaturas foram aprovadas e ativa o que faltou, sem precisar
                  saber o ID de ninguém. Rodar de novo não estende VIP repetido. */}
              <button
                disabled={sincronizando}
                onClick={async () => {
                  setSincronizando(true)
                  try {
                    const r = await api.post('/admin/reconcile-payments', { days: 30 })
                    const ativados = r.data?.ativados ?? []
                    showToast(ativados.length > 0
                      ? `${ativados.length} assinatura(s) ativada(s): ${ativados.map((a: any) => a.email ?? a.user_id).join(', ')}`
                      : `Nada pendente, ${r.data?.ja_registrados ?? 0} já registrada(s) nos últimos 30 dias.`)
                    api.get('/admin/payments').then(r2 => setPayments(r2.data)).catch(() => {})
                    api.get('/admin/payment-events').then(r2 => setPaymentEvents(r2.data)).catch(() => {})
                    api.get('/admin/revenue').then(r2 => setRevenue(r2.data)).catch(() => {})
                  } catch (e: any) {
                    showToast('Erro: ' + (e.response?.data?.detail || e.message), false)
                  } finally { setSincronizando(false) }
                }}
                className="px-2 py-1 text-xs rounded border border-line-strong text-ink-2 hover:text-ink-1 hover:border-green-600 transition-colors disabled:opacity-40"
              >
                {sincronizando ? 'Sincronizando…' : 'Sincronizar com MercadoPago'}
              </button>
              <button
                onClick={async () => {
                  const id = prompt('ID do pagamento MercadoPago:')
                  if (!id) return
                  try {
                    const r = await api.post('/admin/sync-payment', { mp_payment_id: id })
                    showToast(r.data.duplicate
                      ? 'Pagamento já estava registrado.'
                      : `VIP ativado: ${r.data.user.name} · ${r.data.plan}`)
                    api.get('/admin/payments').then(r2 => setPayments(r2.data)).catch(() => {})
                  } catch (e: any) {
                    showToast('Erro: ' + (e.response?.data?.detail || e.message), false)
                  }
                }}
                className="px-2 py-1 text-xs rounded border border-line-strong text-ink-2 hover:text-ink-1 hover:border-green-600 transition-colors"
              >
                + Reprocessar por ID
              </button>
            </div>
          </div>
          {paymentsLoading ? (
            <div className="p-6 flex justify-center"><Spinner size="sm" /></div>
          ) : payments.length === 0 ? (
            <p className="text-center text-ink-4 text-sm py-6">Nenhum pagamento registrado.</p>
          ) : (
            <>
              {/* Celular: cartão por pagamento. Sete colunas não cabem em tela
                  de telefone, e o admin é aberto no celular tanto quanto o
                  resto do site. A tabela continua igual do md pra cima. */}
              <ul className="md:hidden divide-y divide-line/40">
                {paymentsPage_.map((p, i) => (
                  <li key={`m-${i}`} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-ink-1 font-medium text-sm truncate">{p.user_name}</p>
                        <p className="text-ink-4 text-[11px] truncate">{p.user_email}</p>
                      </div>
                      <span className="text-green-400 font-semibold font-mono text-sm shrink-0">
                        R${Number(p.amount).toFixed(2)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap mt-1.5">
                      <span className={p.status === 'approved' ? 'badge-green' : 'badge-free'}>{p.status}</span>
                      <span className="text-[11px] text-ink-3 capitalize">{p.plan_key}</span>
                      {p.payment_method && <span className="text-[11px] text-ink-4">{p.payment_method}</span>}
                    </div>
                    <p className="text-[10px] text-ink-4 font-mono mt-1">
                      {new Date(p.created_at).toLocaleDateString('pt-BR')}
                      {p.expires_at && <> · expira {new Date(p.expires_at).toLocaleDateString('pt-BR')}</>}
                    </p>
                  </li>
                ))}
              </ul>

              <div className="overflow-x-auto hidden md:block">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-line">
                      {['Data', 'Usuário', 'Plano', 'Valor', 'Método', 'Status', 'Expira'].map(h => (
                        <th key={h} className="text-left text-ink-3 font-medium px-4 py-2 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {paymentsPage_.map((p, i) => (
                      <tr key={i} className="border-b border-line/40 hover:bg-surface-1/40">
                        <td className="px-4 py-2 text-ink-3 whitespace-nowrap">{new Date(p.created_at).toLocaleDateString('pt-BR')}</td>
                        <td className="px-4 py-2">
                          <div className="text-ink-1 font-medium">{p.user_name}</div>
                          <div className="text-ink-4">{p.user_email}</div>
                        </td>
                        <td className="px-4 py-2 capitalize text-ink-2">{p.plan_key}</td>
                        <td className="px-4 py-2 text-green-400 font-semibold font-mono">R${Number(p.amount).toFixed(2)}</td>
                        <td className="px-4 py-2 text-ink-2">{p.payment_method ?? ''}</td>
                        <td className="px-4 py-2">
                          <span className={p.status === 'approved' ? 'badge-green' : 'badge-free'}>
                            {p.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-ink-3 whitespace-nowrap">{p.expires_at ? new Date(p.expires_at).toLocaleDateString('pt-BR') : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {paymentsTotalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-line">
                  <span className="text-xs text-ink-4">Página {paymentsPageSafe + 1} de {paymentsTotalPages}</span>
                  <div className="flex gap-2">
                    <button onClick={() => setPaymentsPage(p => Math.max(0, p - 1))} disabled={paymentsPageSafe === 0} className="px-3 py-1 text-xs rounded border border-line-strong text-ink-2 hover:text-ink-1 disabled:opacity-30">← Ant</button>
                    <button onClick={() => setPaymentsPage(p => Math.min(paymentsTotalPages - 1, p + 1))} disabled={paymentsPageSafe === paymentsTotalPages - 1} className="px-3 py-1 text-xs rounded border border-line-strong text-ink-2 hover:text-ink-1 disabled:opacity-30">Próx</button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Trilha de processamento. O webhook rejeitado por assinatura não
            deixava rastro nenhum: o comprador seguia free e a venda sumia do
            relatório sem nada para olhar. Aqui a recusa aparece. */}
        <div className="card overflow-hidden mb-6">
          <div className="px-4 py-3 border-b border-line">
            <h2 className="text-xs font-semibold text-ink-3">Eventos de pagamento</h2>
            <p className="text-[11px] text-ink-4 mt-0.5">
              Últimas tentativas de processar pagamento, inclusive as recusadas.
            </p>
          </div>
          {paymentEvents.length === 0 ? (
            <p className="text-center text-ink-4 text-sm py-6">Nenhum evento registrado.</p>
          ) : (
            <>
            {/* Mesmo motivo da tabela de pagamentos acima. Aqui o campo que
                importa é o `detail`, que é texto longo e some no fim de uma
                linha larga · no cartão ele ganha a largura inteira. */}
            <ul className="md:hidden divide-y divide-line/40">
              {paymentEvents.map((e, i) => (
                <li key={`m-${i}`} className="px-4 py-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={e.status === 'ativado' ? 'badge-green' : 'badge-free'}>{e.status}</span>
                    <span className="text-[11px] text-ink-2">{e.source}</span>
                    <span className="text-[10px] text-ink-4 font-mono ml-auto">
                      {new Date(e.created_at).toLocaleString('pt-BR')}
                    </span>
                  </div>
                  {e.detail && <p className="text-[11px] text-ink-3 mt-1 break-words">{e.detail}</p>}
                  <p className="text-[10px] text-ink-4 font-mono mt-0.5">{e.mp_payment_id}</p>
                </li>
              ))}
            </ul>

            <div className="overflow-x-auto hidden md:block">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line">
                    {['Quando', 'Origem', 'Status', 'Pagamento', 'Detalhe'].map(h => (
                      <th key={h} className="text-left text-ink-3 font-medium px-4 py-2 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paymentEvents.map((e, i) => (
                    <tr key={i} className="border-b border-line/40 hover:bg-surface-1/40">
                      <td className="px-4 py-2 text-ink-3 whitespace-nowrap">
                        {new Date(e.created_at).toLocaleString('pt-BR')}
                      </td>
                      <td className="px-4 py-2 text-ink-2">{e.source}</td>
                      <td className="px-4 py-2">
                        <span className={e.status === 'ativado' ? 'badge-green' : 'badge-free'}>{e.status}</span>
                      </td>
                      <td className="px-4 py-2 font-mono text-ink-3">{e.mp_payment_id}</td>
                      <td className="px-4 py-2 text-ink-3">{e.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </>
          )}
        </div>
        </>)}

        {aba === 'picks' && (<>
        {/* Picks de hoje, os 6 tipos */}
        {overview?.picks_hoje && (
          <div className="card p-4 mb-4">
            <h2 className="text-xs font-semibold text-ink-3 mb-3">Picks de hoje</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {Object.entries(overview.picks_hoje).map(([chave, c]) => (
                <div key={chave} className="flex items-center gap-3 bg-surface-1 rounded-md px-3 py-2.5">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${c.n > 0 ? 'bg-green-500' : 'bg-surface-3'}`} />
                  <div className="min-w-0">
                    <div className="font-mono text-ink-1 font-bold text-lg leading-none">{c.n}</div>
                    <div className="text-ink-3 text-[11px] mt-0.5 truncate">{PICK_LABEL[chave] ?? chave}</div>
                    {c.pendentes > 0 && (
                      <div className="text-[10px] text-orange-400 mt-0.5">{c.pendentes} pendente{c.pendentes > 1 ? 's' : ''}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <AdminShareResults />
        <AdminPendencias />
        {/* Ações de resultado. Os dois endpoints já existiam no backend desde
            que o scheduler foi removido, mas não tinham botão nenhum -- só
            dava pra chamar por fora. Sem scheduler, esta é a única forma de
            resolver pick em lote. */}
        <div className="card p-4 mb-4">
          <h2 className="text-xs font-semibold text-ink-3 mb-1">Resultados</h2>
          <p className="text-xs text-ink-3 mb-3 leading-relaxed">
            Nada roda agendado. Resolver marca GREEN/RED nos picks cujo jogo já
            terminou; reconferir corrige escanteios e cartões que a API revisou
            depois do apito.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              className="btn-primary text-sm py-3 disabled:opacity-40"
              disabled={acaoResultado !== null}
              onClick={async () => {
                setAcaoResultado('resolve')
                try {
                  const r = await api.post('/admin/resolve-picks')
                  const res = r.data?.resolved ?? {}
                  const total = Object.values(res).reduce((a: number, b: any) => a + Number(b || 0), 0)
                  showToast(total > 0
                    ? `${total} pick(s) resolvido(s): ${Object.entries(res).filter(([, v]) => Number(v) > 0).map(([k, v]) => `${k} ${v}`).join(', ')}`
                    : 'Nenhum pick pendente com jogo encerrado.')
                  carregarOverview()
                } catch (err: any) {
                  showToast(err.response?.data?.detail || 'Erro ao resolver picks', false)
                } finally { setAcaoResultado(null) }
              }}>
              {acaoResultado === 'resolve' ? 'Resolvendo...' : 'Resolver picks pendentes'}
            </button>
            <button
              className="btn-ghost text-sm py-3 disabled:opacity-40"
              disabled={acaoResultado !== null}
              onClick={async () => {
                setAcaoResultado('reverify')
                try {
                  const r = await api.post('/admin/reverify-stats-results')
                  const n = (r.data?.corrected ?? []).length
                  showToast(n > 0 ? `${n} resultado(s) corrigido(s) após revisão da API.` : 'Nenhuma correção necessária.')
                  carregarOverview()
                } catch (err: any) {
                  showToast(err.response?.data?.detail || 'Erro ao reconferir', false)
                } finally { setAcaoResultado(null) }
              }}>
              {acaoResultado === 'reverify' ? 'Reconferindo...' : 'Reconferir escanteios e cartões'}
            </button>
          </div>
        </div>

        <div className="card p-4 mb-6">
          <h2 className="text-xs font-semibold text-ink-3 mb-3">Corrigir Resultado de Pick</h2>
          {(() => {
            const brt = (daysAgo = 0) => {
              const d = new Date()
              d.setDate(d.getDate() - daysAgo)
              return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo' }).format(d)
            }
            const shortcuts = [
              { label: 'Hoje',          from: brt(0),  to: brt(0)  },
              { label: 'Ontem',         from: brt(1),  to: brt(1)  },
              { label: '3 dias',        from: brt(3),  to: brt(0)  },
              { label: 'Semana passada',from: brt(7),  to: brt(0)  },
              { label: '15 dias',       from: brt(15), to: brt(0)  },
            ]
            return (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {shortcuts.map(s => (
                  <button key={s.label}
                    onClick={() => { setPickDateFrom(s.from); setPickDateTo(s.to) }}
                    className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors touch-manipulation ${pickDateFrom === s.from && pickDateTo === s.to ? 'border-green-500/50 bg-green-500/10 text-green-400' : 'border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-2'}`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )
          })()}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-ink-3 font-semibold">Time</label>
              <input
                className="input text-sm"
                placeholder="Ex: Brasil, Flamengo..."
                value={pickSearch}
                onChange={e => setPickSearch(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchPicks()}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-ink-3 font-semibold">Tipo</label>
              <select className="input text-sm" value={pickTypeFilter} onChange={e => setPickTypeFilter(e.target.value)}>
                <option value="">Todos</option>
                <option value="vip">VIP</option>
                <option value="free">Free</option>
                <option value="multipla">Múltipla</option>
                <option value="alavancagem">Alavancagem</option>
                <option value="faltas">Faltas</option>
                <option value="goleiros">Defesas</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-ink-3 font-semibold">Data de</label>
              <input type="date" className="input text-sm" value={pickDateFrom} onChange={e => setPickDateFrom(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-ink-3 font-semibold">Data até</label>
              <input type="date" className="input text-sm" value={pickDateTo} onChange={e => setPickDateTo(e.target.value)} />
            </div>
          </div>
          <button onClick={searchPicks} disabled={pickSearching}
            className="w-full btn-primary text-sm py-3 disabled:opacity-40 touch-manipulation mb-3">
            {pickSearching ? 'Buscando...' : 'Buscar Picks'}
          </button>

          {pickResults.length > 0 && (
            <div className="space-y-2 mt-2">
              {pickResults.map((p) => {
                const resultCls: Record<string, string> = {
                  GREEN: 'text-green-400 bg-green-400/10 border-green-500/30',
                  RED: 'text-red-400 bg-red-400/10 border-red-500/30',
                  PUSH: 'text-ink-2 bg-surface-3/40 border-line-strong/30',
                  'HALF-WIN': 'text-teal-400 bg-teal-400/10 border-teal-500/30',
                  'HALF-LOSS': 'text-orange-400 bg-orange-400/10 border-orange-500/30',
                }
                // Mesmas cores da aba Mercados na página de picks, pra o tipo
                // ser reconhecido pela cor em qualquer tela.
                const typeCls: Record<string, string> = {
                  vip: 'text-yellow-400 bg-yellow-400/10', free: 'text-green-400 bg-green-400/10',
                  multipla: 'text-blue-400 bg-blue-400/10', alavancagem: 'text-orange-400 bg-orange-400/10',
                  faltas: 'text-purple-400 bg-purple-400/10', goleiros: 'text-sky-400 bg-sky-400/10',
                }
                const resCls = p.result ? (resultCls[p.result] ?? 'text-ink-2 bg-surface-3/40 border-line-strong/30') : 'text-ink-4 bg-surface-1 border-line'
                return (
                  <div key={`${p.pick_type}-${p.id}`} className="bg-surface-1 border border-line rounded-lg p-3 flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap min-w-0">
                        <span className={`text-[10px] font-black px-2 py-0.5 rounded ${typeCls[p.pick_type] ?? 'text-ink-2 bg-surface-3/40'}`}>{p.pick_type}</span>
                        <span className="text-xs font-semibold text-ink-1 truncate">{p.home_team}{p.away_team ? ` vs ${p.away_team}` : ''}</span>
                      </div>
                      <span className="text-[10px] text-ink-3 shrink-0">{p.match_date ? new Date(p.match_date + 'T12:00:00').toLocaleDateString('pt-BR') : ''}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-black px-2 py-1 rounded border ${resCls}`}>{p.result ?? 'Pendente'}</span>
                      <span className="text-ink-4 text-xs">·</span>
                      <span className="text-xs text-ink-3 truncate flex-1">{p.market} {p.line ?? ''}</span>
                      {p.odd != null && (
                        <span className="font-mono text-xs text-ink-2 shrink-0">@{Number(p.odd).toFixed(2)}</span>
                      )}
                      {p.profit != null && (
                        <span className={`font-mono text-xs shrink-0 ${Number(p.profit) > 0 ? 'text-green-400' : Number(p.profit) < 0 ? 'text-red-400' : 'text-ink-3'}`}>
                          {Number(p.profit) > 0 ? '+' : ''}{Number(p.profit).toFixed(2)}u
                        </span>
                      )}
                    </div>
                    <select
                      disabled={settingResult === p.id}
                      value=""
                      onChange={e => { if (e.target.value) setPickResult(p, e.target.value) }}
                      className="w-full bg-surface-2 border border-line-strong rounded-lg px-3 py-2.5 text-sm text-ink-2 focus:outline-none focus:border-green-500 disabled:opacity-40 touch-manipulation"
                    >
                      <option value="">Alterar resultado...</option>
                      <option value="GREEN">GREEN</option>
                      <option value="RED">RED</option>
                      <option value="PUSH">PUSH</option>
                      <option value="HALF-WIN">HALF-WIN</option>
                      <option value="HALF-LOSS">HALF-LOSS</option>
                      <option value="pending">Pendente (limpar)</option>
                    </select>
                  </div>
                )
              })}
            </div>
          )}
          {pickResults.length === 0 && !pickSearching && (pickSearch || pickDateFrom) && (
            <p className="text-ink-4 text-xs text-center py-4">Nenhum pick encontrado.</p>
          )}
        </div>
        </>)}

        {aba === 'usuarios' && (<>
        {/* Contagem por plano e atividade. Moraram na Visao geral ate 16/08 e
            vieram pra ca: sao numeros SOBRE USUARIO, e quem esta olhando a
            base nao devia trocar de aba pra ver quantos VIP existem. */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
            {[
              { label: 'Total',         value: stats.total,          color: 'text-ink-1' },
              { label: 'VIP',           value: stats.vip,            color: 'text-yellow-400' },
              { label: 'Teste',         value: stats.trial,          color: 'text-blue-400' },
              { label: 'Free',          value: stats.free,           color: 'text-ink-2' },
              { label: 'Ativos',        value: stats.ativos,         color: 'text-accent-ink' },
              { label: 'VIP expirando', value: stats.vip_expirando,  color: stats.vip_expirando > 0 ? 'text-orange-400' : 'text-ink-4' },
            ].map(({ label, value, color }) => (
              <div key={label} className="stat-card text-center py-3">
                <div className={`font-mono text-3xl font-black ${color}`}>{value}</div>
                <div className="text-xs text-ink-3 mt-1">{label}</div>
              </div>
            ))}
          </div>
        )}
        <AdminEngajamento />
        {/* Criar usuário */}
        {creating && (
          <form onSubmit={handleCreate} className="card p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <input className="input" placeholder="Nome" value={newUser.name} onChange={e => setNewUser(v => ({ ...v, name: e.target.value }))} required />
            <input className="input" placeholder="Email" type="email" value={newUser.email} onChange={e => setNewUser(v => ({ ...v, email: e.target.value }))} required />
            <input className="input" placeholder="Senha (min 10 chars, maiúscula, número)" type="password" value={newUser.password} onChange={e => setNewUser(v => ({ ...v, password: e.target.value }))} required />
            <select className="input" value={newUser.plan} onChange={e => setNewUser(v => ({ ...v, plan: e.target.value }))}>
              <option value="free">Free</option>
              <option value="trial">Teste</option>
              <option value="vip">VIP</option>
              <option value="admin">Admin</option>
            </select>
            <div className="flex gap-2">
              <button type="submit" className="btn-primary flex-1">Criar</button>
              <button type="button" onClick={() => setCreating(false)} className="px-3 py-2 rounded-lg border border-line-strong text-ink-2 hover:text-ink-1 text-sm transition-colors">✕</button>
            </div>
          </form>
        )}

        {/* Busca + filtro */}
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <input
            className="input flex-1 text-sm"
            placeholder="Buscar por nome ou email..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <div className="flex gap-1 flex-wrap">
            {PLAN_FILTER.map(p => (
              <button
                key={p}
                onClick={() => setPlanFilter(p)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors border ${
                  planFilter === p
                    ? 'bg-green-500 border-green-500 text-black'
                    : 'border-line-strong text-ink-2 hover:border-ink-4'
                }`}
              >
                {p === 'todos' ? 'Todos' : p.toUpperCase()}
              </button>
            ))}
          </div>
          <span className="text-ink-4 text-xs self-center whitespace-nowrap">{filtered.length} usuário(s)</span>
        </div>

        {/* Tabela · desktop */}
        <div className="card overflow-hidden hidden md:block">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  {['Usuário', 'WhatsApp', 'Plano', 'Tipo / Validade', 'Banca', 'Status', 'Cadastro', 'Último acesso', 'Ações'].map(h => (
                    <th key={h} className="text-left text-ink-3 font-medium px-4 py-3 text-xs whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredPage.map(u => (
                  <tr key={u.id} className="border-b border-line/50 hover:bg-surface-1/50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-ink-1">{u.name}</div>
                      <div className="text-ink-3 text-xs">{u.email}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-2 whitespace-nowrap">
                      {u.phone
                        ? <span className="text-green-400">{u.phone}</span>
                        : <span className="text-ink-4">sem número</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={planBadge(u.plan)}>
                        {u.plan.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <select
                          value={u.subscription_type ?? ''}
                          onChange={e => setSubscriptionType(u.id, e.target.value)}
                          className="bg-surface-2 border border-line-strong rounded-lg px-2 py-1 text-xs text-ink-2 focus:outline-none focus:border-green-500"
                        >
                          {SUBSCRIPTION_TYPES.map(t => (
                            <option key={t.value} value={t.value}>{t.label}</option>
                          ))}
                        </select>
                        <div className="flex items-center gap-1">
                          <input
                            type="date"
                            value={u.expires_at ? u.expires_at.slice(0, 10) : ''}
                            onChange={e => setExpiresAt(u.id, e.target.value)}
                            className="bg-surface-2 border border-line-strong rounded-lg px-2 py-1 text-xs text-ink-2 focus:outline-none focus:border-green-500 w-32"
                          />
                          {expiryWarning(u.expires_at)}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-2 font-mono">
                      {u.bankroll_current != null
                        ? <><div className="text-ink-1 font-semibold">R${u.bankroll_current.toFixed(0)}</div><div className="text-ink-4">{u.unit_value != null ? `U R$${u.unit_value.toFixed(0)}` : ''}</div></>
                        : null}
                    </td>
                    <td className="px-4 py-3">
                      <span className={u.active ? 'badge-green' : 'badge-red'}>
                        {u.active ? 'Ativo' : 'Inativo'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-3 text-xs whitespace-nowrap">
                      {new Date(u.created_at).toLocaleDateString('pt-BR')}
                    </td>
                    <td className="px-4 py-3 text-xs whitespace-nowrap">
                      {u.last_login_at ? (() => {
                        const diff = Date.now() - new Date(u.last_login_at).getTime()
                        const mins = Math.floor(diff / 60000)
                        const hrs  = Math.floor(diff / 3600000)
                        const days = Math.floor(diff / 86400000)
                        if (mins < 60)  return <span className="text-green-400 font-semibold">{mins}min atrás</span>
                        if (hrs  < 24)  return <span className="text-green-300">{hrs}h atrás</span>
                        if (days < 7)   return <span className="text-ink-2">{days}d atrás</span>
                        return <span className="text-ink-4">{new Date(u.last_login_at).toLocaleDateString('pt-BR')}</span>
                      })() : <span className="text-ink-4">nunca</span>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 items-center">
                        <select
                          value={u.plan}
                          onChange={e => setPlan(u.id, e.target.value)}
                          className="bg-surface-2 border border-line-strong rounded-lg px-2 py-1 text-xs text-ink-1 focus:outline-none"
                        >
                          <option value="free">Free</option>
                          <option value="trial">Teste</option>
                          <option value="vip">VIP</option>
                          <option value="admin">Admin</option>
                        </select>
                        <button
                          onClick={() => toggleActive(u.id, u.active)}
                          className={`text-xs px-2 py-1 rounded-lg border transition-colors whitespace-nowrap ${
                            u.active
                              ? 'border-red-700 text-red-400 hover:bg-red-900/20'
                              : 'border-green-700 text-green-400 hover:bg-green-900/20'
                          }`}
                        >
                          {u.active ? 'Desativar' : 'Ativar'}
                        </button>
                        {u.active && (
                          <button
                            onClick={() => deleteUser(u.id, u.name)}
                            className="text-xs px-2 py-1 rounded-lg border border-line text-ink-4 hover:border-red-800 hover:text-red-500 transition-colors"
                            title="Desativar usuário"
                          >✕</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredPage.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-ink-4 text-sm">
                      Nenhum usuário encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {usersTotalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-line">
                <span className="text-xs text-ink-4">Página {usersPageSafe + 1} de {usersTotalPages} · {filtered.length} usuário(s)</span>
                <div className="flex gap-2">
                  <button onClick={() => setUsersPage(p => Math.max(0, p - 1))} disabled={usersPageSafe === 0} className="px-3 py-1 text-xs rounded border border-line-strong text-ink-2 hover:text-ink-1 disabled:opacity-30">← Ant</button>
                  <button onClick={() => setUsersPage(p => Math.min(usersTotalPages - 1, p + 1))} disabled={usersPageSafe === usersTotalPages - 1} className="px-3 py-1 text-xs rounded border border-line-strong text-ink-2 hover:text-ink-1 disabled:opacity-30">Próx</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Cards · mobile */}
        <div className="flex flex-col gap-3 md:hidden">
          {filtered.length === 0 && (
            <p className="text-center text-ink-4 text-sm py-8">Nenhum usuário encontrado.</p>
          )}
          {filteredPage.map(u => (
            <div key={u.id} className="card p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="font-semibold text-ink-1">{u.name}</div>
                  <div className="text-ink-3 text-xs mt-0.5">{u.email}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={planBadge(u.plan)}>
                    {u.plan.toUpperCase()}
                  </span>
                  <span className={u.active ? 'badge-green' : 'badge-red'}>
                    {u.active ? 'Ativo' : 'Inativo'}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs text-ink-3 mb-3">
                <div>Tipo: <span className="text-ink-2">{u.subscription_type ?? ''}</span></div>
                <div className="flex items-center gap-1">
                  Expira: <span className="text-ink-2">{u.expires_at ? u.expires_at.slice(0, 10) : ''}</span>
                  {expiryWarning(u.expires_at)}
                </div>
                <div>Banca: <span className="font-mono text-ink-2">{u.bankroll_current != null ? `R$${u.bankroll_current.toFixed(0)}` : ''}</span></div>
                <div>Cadastro: <span className="text-ink-2">{new Date(u.created_at).toLocaleDateString('pt-BR')}</span></div>
              </div>

              <div className="flex gap-2 flex-wrap">
                <select
                  value={u.plan}
                  onChange={e => setPlan(u.id, e.target.value)}
                  className="bg-surface-2 border border-line-strong rounded-lg px-2 py-1 text-xs text-ink-1 focus:outline-none flex-1"
                >
                  <option value="free">Free</option>
                  <option value="trial">Teste</option>
                  <option value="vip">VIP</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  onClick={() => toggleActive(u.id, u.active)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    u.active ? 'border-red-700 text-red-400' : 'border-green-700 text-green-400'
                  }`}
                >
                  {u.active ? 'Desativar' : 'Ativar'}
                </button>
              </div>
            </div>
          ))}
        </div>
        </>)}

        {aba === 'ligas' && (<>
          <div className="card p-4 mb-4">
            <h2 className="text-xs font-semibold text-ink-3 mb-1">Cadastrar liga</h2>
            <p className="text-xs text-ink-3 mb-3 leading-relaxed">
              O ID é o da API-Football (ex.: 71 = Brasileirão Série A). O nome é
              buscado automaticamente, só preencha se a validação estiver fora.
            </p>
            <div className="grid gap-2 sm:grid-cols-4">
              <input className="input" placeholder="ID da liga" inputMode="numeric"
                value={novaLiga.league_id}
                onChange={e => { setNovaLiga(v => ({ ...v, league_id: e.target.value.replace(/\D/g, '') })); setPreviaLiga(null) }} />
              <input className="input" placeholder="Temporada" inputMode="numeric"
                value={novaLiga.season}
                onChange={e => { setNovaLiga(v => ({ ...v, season: e.target.value.replace(/\D/g, '') })); setPreviaLiga(null) }} />
              <input className="input" placeholder="Nome (opcional)"
                value={novaLiga.name}
                onChange={e => setNovaLiga(v => ({ ...v, name: e.target.value }))} />
              <button
                className="text-xs text-ink-1 border border-line hover:border-accent/40 rounded px-3 py-2 transition-colors disabled:opacity-40"
                disabled={verificando || !novaLiga.league_id || !novaLiga.season}
                onClick={async () => {
                  setVerificando(true); setPreviaLiga(null)
                  try {
                    const r = await api.get(
                      `/admin/leagues/${novaLiga.league_id}/verificar`,
                      { params: { season: Number(novaLiga.season) } })
                    setPreviaLiga(r.data)
                    // Marca sozinho com o que a API respondeu · a caixa fica
                    // pra corrigir, não pra adivinhar.
                    if (r.data?.existe) {
                      setNovaLiga(v => ({ ...v, temporada_iniciada: !!r.data.iniciada }))
                    }
                  } catch (err: any) {
                    showToast(err.response?.data?.detail || 'Erro ao verificar liga', false)
                  } finally {
                    setVerificando(false)
                  }
                }}>
                {verificando ? 'Verificando...' : 'Verificar'}
              </button>
              <button
                className="btn-primary disabled:opacity-40"
                disabled={salvandoLiga || !novaLiga.league_id || !novaLiga.season}
                onClick={async () => {
                  setSalvandoLiga(true)
                  try {
                    const r = await api.post('/admin/leagues', {
                      temporada_iniciada: novaLiga.temporada_iniciada,
                      league_id: Number(novaLiga.league_id),
                      season: Number(novaLiga.season),
                      name: novaLiga.name || undefined,
                    })
                    showToast(`${r.data.name} ${r.data.acao}. ${r.data.aviso}`)
                    setNovaLiga({ league_id: '', season: String(new Date().getFullYear()),
                                  name: '', temporada_iniciada: null })
                    setPreviaLiga(null)
                    carregarLigas()
                  } catch (err: any) {
                    showToast(err.response?.data?.detail || 'Erro ao cadastrar liga', false)
                  } finally {
                    setSalvandoLiga(false)
                  }
                }}>
                {salvandoLiga ? 'Salvando...' : 'Cadastrar'}
              </button>
            </div>

            {/*
              Caixa de seleção da temporada.

              Três estados, não dois: marcada (já começou), desmarcada (não
              começou) e SEM MARCAR. O terceiro existe porque quem cadastra
              pode não saber, e assumir "já começou" faria o Coletar disparar
              o backfill · uma requisição por jogo · numa liga que pode não ter
              jogo finalizado nenhum. Sem marcar, roda completo, que é o seguro.
            */}
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <span className="text-[11px] text-ink-4">Temporada:</span>
              {([
                [true,  'Já começou'],
                [false, 'Ainda não começou'],
                [null,  'Não sei'],
              ] as const).map(([valor, rotulo]) => (
                <button
                  key={String(valor)}
                  onClick={() => setNovaLiga(v => ({ ...v, temporada_iniciada: valor }))}
                  className={`text-[11px] px-2.5 py-1.5 rounded border transition-colors ${
                    novaLiga.temporada_iniciada === valor
                      ? 'border-accent/50 bg-accent/10 text-accent-ink font-semibold'
                      : 'border-line text-ink-3 hover:text-ink-1'}`}>
                  {rotulo}
                </button>
              ))}
              {novaLiga.temporada_iniciada === false && (
                <span className="text-[11px] text-ink-4">
                  Coletar vai pular a estatística do histórico.
                </span>
              )}
            </div>

            {/*
              Prévia antes de gastar cota.
              
              Cadastrar uma liga cuja temporada não abriu, ou com o `season`
              errado, resulta numa coleta que roda inteira e traz zero jogo · e
              o único sintoma é a linha ficar em "0 times, 0 jogos", que se
              confunde com falha de coleta.
            */}
            {previaLiga && (
              <div className={`mt-3 rounded-lg border p-3 ${
                !previaLiga.existe ? 'bg-red-500/5 border-red-500/25'
                  : previaLiga.iniciada ? 'bg-accent/5 border-accent/25'
                  : 'bg-yellow-500/5 border-yellow-500/25'}`}>
                {!previaLiga.existe ? (
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                    <p className="text-xs text-ink-2 leading-relaxed">{previaLiga.aviso}</p>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2 flex-wrap mb-1.5">
                      <span className="text-sm font-bold text-ink-1">{previaLiga.nome}</span>
                      <span className={`text-[10px] font-black px-1.5 py-0.5 rounded ${
                        previaLiga.iniciada ? 'bg-accent/15 text-accent-ink'
                                            : 'bg-yellow-500/15 text-yellow-400'}`}>
                        {previaLiga.iniciada ? 'TEMPORADA EM ANDAMENTO' : 'AINDA NÃO COMEÇOU'}
                      </span>
                    </div>
                    <p className="text-xs text-ink-2 font-mono">
                      {previaLiga.finalizados} jogos finalizados, {previaLiga.agendados} agendados,
                      {' '}{previaLiga.total} no total
                    </p>
                    <p className="text-[11px] text-ink-4 mt-1">
                      {previaLiga.inicio} a {previaLiga.fim}
                      {previaLiga.rodada_atual ? ` · agora em "${previaLiga.rodada_atual}"` : ''}
                    </p>
                    <p className="text-[11px] text-ink-3 mt-2 leading-relaxed">
                      {previaLiga.iniciada
                        ? `Coletar vai buscar a estatística dos ${previaLiga.finalizados} jogos já finalizados, uma requisição por jogo.`
                        : 'Nenhum jogo finalizado ainda, então Coletar só traz os times e os jogos agendados. A estatística vem quando a bola rolar.'}
                    </p>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="card p-4">
            <h2 className="text-xs font-semibold text-ink-3 mb-3">
              Ligas na coleta {ligas ? `(${ligas.length})` : ''}
            </h2>
            {!ligas ? (
              <p className="text-sm text-ink-4">Carregando...</p>
            ) : ligas.length === 0 ? (
              <p className="text-sm text-ink-4">Nenhuma liga cadastrada, o motor não tem o que coletar.</p>
            ) : (
              <div className="space-y-2">
                {ligas.map(l => {
                  // Estado da coleta que esta rodando AGORA (uma por vez, o
                  // backend recusa a segunda com 409). `league_id` vem junto no
                  // status justamente pra saber de qual linha ele fala.
                  const coletaAtual = pipelineStatus['coletar_liga'] as
                    (typeof pipelineStatus[string] & { league_id?: number }) | undefined
                  const ehEstaLiga = coletaAtual?.league_id === l.league_id
                  const coletaRodando = coletaAtual?.status === 'running'
                  return (
                  <div key={l.league_id}
                    className="flex items-center gap-3 bg-surface-1 border border-line rounded-md px-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm text-ink-1 font-bold truncate">{l.name}</span>
                        <span className="font-mono text-[10px] text-ink-4">#{l.league_id} · {l.season}</span>
                        {!l.ativa && (
                          <span className="text-[10px] font-black px-1.5 py-0.5 rounded bg-surface-3 text-ink-3">
                            SÓ HISTÓRICO
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-ink-3 mt-0.5 font-mono">
                        {l.times} times · {l.jogos_coletados} jogos coletados · {l.jogos_agendados} agendados
                      </div>
                      {l.temporada_iniciada === false && (
                        <div className="text-[11px] text-ink-4 mt-0.5">
                          Marcada como temporada não iniciada, a coleta pula o histórico.
                        </div>
                      )}
                      {/*
                        Liga sem time nunca coleta jogo: o coletor filtra pelos
                        times conhecidos. O aviso fica aqui porque a linha já
                        mostra "0 times" e ninguém liga os dois fatos sozinho ·
                        foi assim que a Sul-Americana ficou dias cadastrada,
                        com as oitavas rolando, e zero jogo no banco.
                      */}
                      {l.times === 0 && !ehEstaLiga && (
                        <div className="flex items-start gap-1.5 mt-1 text-[11px] text-yellow-500/90 leading-snug">
                          <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
                          <span>Sem times cadastrados, nenhum jogo desta liga será coletado até você clicar em Coletar.</span>
                        </div>
                      )}

                      {/*
                        Andamento na PRÓPRIA linha, não só na aba Pipeline. O
                        backfill leva minutos e é fácil achar que não fez nada
                        e clicar de novo · daí o estado morar aqui, junto do
                        botão que o disparou.
                      */}
                      {ehEstaLiga && coletaAtual?.status === 'running' && (
                        <div className="flex items-center gap-1.5 mt-1 text-[11px] text-accent-ink">
                          <Spinner className="w-3 h-3" />
                          <span>Coletando desde {coletaAtual.started_at}, pode levar alguns minutos.</span>
                        </div>
                      )}
                      {ehEstaLiga && coletaAtual?.status === 'ok' && (
                        <div className="text-[11px] text-accent-ink mt-1">
                          Coleta concluída às {coletaAtual.finished_at}.
                        </div>
                      )}
                      {ehEstaLiga && coletaAtual?.status === 'error' && (
                        <div className="flex items-start gap-1.5 mt-1 text-[11px] text-red-400 leading-snug">
                          <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
                          <span>Coleta falhou. Veja o log na aba Pipeline.</span>
                        </div>
                      )}
                    </div>
                    <button
                      className="text-xs text-ink-1 border border-line hover:border-accent/40 rounded px-3 py-2 shrink-0 transition-colors disabled:opacity-50"
                      disabled={coletaRodando}
                      title={coletaRodando && !ehEstaLiga
                        ? 'Já há uma coleta em andamento' : undefined}
                      onClick={() => setConfirmarColeta(l)}>
                      {ehEstaLiga && coletaAtual?.status === 'running' ? 'Coletando...' : 'Coletar'}
                    </button>
                    {!l.ativa ? (
                      <button
                        className="text-xs text-ink-1 border border-line hover:border-accent/40 rounded px-3 py-2 shrink-0 transition-colors"
                        onClick={async () => {
                          try {
                            const r = await api.post(`/admin/leagues/${l.league_id}/reativar`)
                            showToast(`${r.data.liga} voltou pra coleta.`)
                            carregarLigas()
                          } catch (err: any) {
                            showToast(err.response?.data?.detail || 'Erro ao reativar', false)
                          }
                        }}>
                        Reativar
                      </button>
                    ) : (
                    <button
                      className="text-xs text-red-400 hover:text-red-300 border border-line hover:border-red-500/40 rounded px-3 py-2 shrink-0 transition-colors"
                      onClick={async () => {
                        // Confirmacao explicita porque o efeito nao e' obvio
                        // pelo botao: para de COLETAR, mas o historico fica.
                        if (!window.confirm(
                          `Tirar "${l.name}" da coleta?\n\n` +
                          `Os ${l.jogos_coletados} jogos, os times, os picks e o NOME da liga são PRESERVADOS, ` +
                          `ela só para de receber dados novos e continua legível no histórico do site. ` +
                          `Dá pra reativar depois.`
                        )) return
                        try {
                          const r = await api.delete(`/admin/leagues/${l.league_id}`)
                          showToast(`${r.data.removida} saiu da coleta. ${r.data.aviso}`)
                          carregarLigas()
                        } catch (err: any) {
                          showToast(err.response?.data?.detail || 'Erro ao remover liga', false)
                        }
                      }}>
                      Tirar da coleta
                    </button>
                    )}
                  </div>
                  )
                })}
              </div>
            )}
            <p className="text-[11px] text-ink-4 mt-3 leading-relaxed">
              Cadastrar só coloca a liga na fila, <span className="text-ink-2">Coletar</span> é
              o que traz os times, os jogos e a estatística da temporada. Roda em segundo plano,
              com o andamento na própria linha da liga.
            </p>
          </div>

          {/*
            Card de confirmação no lugar do window.confirm: a ação gasta cota
            de API de verdade e leva minutos, então merece ver o que vai
            acontecer antes de disparar.
          */}
          <AnimatePresence>
            {confirmarColeta && (
              <Modal
                onClose={() => setConfirmarColeta(null)}
                width="sm"
                title="Coletar liga"
                description={confirmarColeta.name}
              >
                <div className="p-5 space-y-4">
                  <div>
                    <p className="text-xs text-ink-2 leading-relaxed mb-2.5">O que vai acontecer:</p>
                    <ol className="space-y-1.5">
                      {[
                        'Times da liga',
                        'Jogos da janela de coleta',
                        'Estatística de todos os jogos já finalizados da temporada',
                        'Médias agregadas por time',
                      ].map((passo, i) => (
                        <li key={passo} className="flex gap-2 text-xs text-ink-1">
                          <span className="font-mono text-[10px] text-ink-4 pt-0.5">{i + 1}</span>
                          <span>{passo}</span>
                        </li>
                      ))}
                    </ol>
                  </div>

                  <div className="bg-yellow-500/5 border border-yellow-500/25 rounded-lg p-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="w-3.5 h-3.5 text-yellow-500 shrink-0 mt-0.5" />
                      <p className="text-[11px] text-ink-2 leading-relaxed">
                        O passo 3 gasta uma requisição da API por jogo. Numa liga de pontos
                        corridos são centenas, então pode levar minutos e consumir bastante cota.
                      </p>
                    </div>
                  </div>

                  <p className="text-[11px] text-ink-4 leading-relaxed">
                    Nada é apagado, é tudo atualização. Roda em segundo plano e o andamento
                    aparece na linha da liga.
                  </p>

                  <div className="flex gap-2 pt-1">
                    <button
                      className="flex-1 text-xs text-ink-3 border border-line rounded px-3 py-2.5 hover:text-ink-1 transition-colors"
                      onClick={() => setConfirmarColeta(null)}>
                      Cancelar
                    </button>
                    <Button
                      className="flex-1"
                      disabled={disparando}
                      onClick={async () => {
                        setDisparando(true)
                        try {
                          const r = await api.post(`/admin/leagues/${confirmarColeta.league_id}/coletar`)
                          showToast(`Coleta de ${r.data.liga} iniciada.`)
                          setConfirmarColeta(null)
                        } catch (err: any) {
                          showToast(err.response?.data?.detail || 'Erro ao iniciar coleta', false)
                        } finally {
                          setDisparando(false)
                        }
                      }}>
                      {disparando ? 'Iniciando...' : 'Coletar agora'}
                    </Button>
                  </div>
                </div>
              </Modal>
            )}
          </AnimatePresence>
        </>)}

        {aba === 'casas' && (<>
          {/* Cadastrar casa */}
          <div className="card p-4 mb-4">
            <h2 className="text-xs font-semibold text-ink-3 mb-1">Cadastrar / editar casa de aposta</h2>
            <p className="text-xs text-ink-3 mb-3 leading-relaxed">
              O ID é o que a API-Football usa (ex.: 8 = Bet365, 32 = Betano).
              Casas já coletadas aparecem na lista abaixo; aqui você pode cadastrar
              uma nova antes da primeira coleta ou corrigir o nome.
            </p>
            <div className="grid gap-2 sm:grid-cols-3">
              <input
                className="input"
                placeholder="ID da casa (ex.: 8)"
                inputMode="numeric"
                value={novoBookmaker.bookmaker_id}
                onChange={e => setNovoBookmaker(v => ({ ...v, bookmaker_id: e.target.value.replace(/\D/g, '') }))}
              />
              <input
                className="input"
                placeholder="Nome (ex.: Bet365)"
                value={novoBookmaker.bookmaker_name}
                onChange={e => setNovoBookmaker(v => ({ ...v, bookmaker_name: e.target.value }))}
              />
              <button
                className="btn-primary disabled:opacity-40"
                disabled={salvandoBk || !novoBookmaker.bookmaker_id || !novoBookmaker.bookmaker_name.trim()}
                onClick={async () => {
                  setSalvandoBk(true)
                  try {
                    await api.put(`/admin/bookmakers/${novoBookmaker.bookmaker_id}`, {
                      bookmaker_id: Number(novoBookmaker.bookmaker_id),
                      bookmaker_name: novoBookmaker.bookmaker_name.trim(),
                      ativo: true,
                    })
                    showToast(`Casa ${novoBookmaker.bookmaker_name} salva.`)
                    setNovoBookmaker({ bookmaker_id: '', bookmaker_name: '' })
                    carregarBookmakers()
                  } catch (err: any) {
                    showToast(err.response?.data?.detail || 'Erro ao salvar', false)
                  } finally { setSalvandoBk(false) }
                }}>
                {salvandoBk ? 'Salvando...' : 'Salvar'}
              </button>
            </div>
          </div>

          {/* Lista de casas */}
          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
              <h2 className="text-xs font-semibold text-ink-3">
                Casas coletadas {bookmakers ? `(${bookmakers.length})` : ''}
              </h2>
              <button
                className="text-xs text-ink-3 hover:text-ink-1 border border-line-strong rounded px-2 py-1 transition-colors"
                onClick={carregarBookmakers}>
                Recarregar
              </button>
            </div>
            {bkLoading ? (
              <div className="p-6 flex justify-center"><Spinner size="sm" /></div>
            ) : !bookmakers || bookmakers.length === 0 ? (
              <p className="text-center text-ink-4 text-sm py-6">
                Nenhuma casa encontrada. Rode a coleta de odds primeiro.
              </p>
            ) : (
              <>
              {/* Celular: cartão por casa. Seis colunas com dois botões de ação
                  na última é o pior caso pra rolagem lateral · a ação fica
                  justamente na ponta que não aparece. */}
              <ul className="md:hidden divide-y divide-line/40">
                {bookmakers.map(bk => (
                  <li key={`m-${bk.bookmaker_id}`} className="px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-ink-1 font-medium text-sm">{bk.bookmaker_name}</span>
                      <span className={bk.ativo ? 'badge-green shrink-0' : 'text-xs text-ink-4 shrink-0'}>
                        {bk.ativo ? 'Ativo' : 'Inativo'}
                      </span>
                    </div>
                    <p className="text-[11px] text-ink-4 font-mono mt-0.5">
                      #{bk.bookmaker_id} · {bk.n_odds.toLocaleString('pt-BR')} odds
                      {' · '}{bk.n_fixtures.toLocaleString('pt-BR')} fixtures
                    </p>
                    <button
                      className="mt-2 text-[11px] text-ink-2 border border-line-strong rounded px-2 py-1 hover:text-ink-1 transition-colors"
                      onClick={() => setNovoBookmaker({
                        bookmaker_id: String(bk.bookmaker_id),
                        bookmaker_name: bk.bookmaker_name,
                      })}>
                      Editar
                    </button>
                  </li>
                ))}
              </ul>

              <div className="overflow-x-auto hidden md:block">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-line">
                      {['ID', 'Nome', 'Status', 'Odds coletadas', 'Fixtures', 'Ações'].map(h => (
                        <th key={h} className="text-left text-ink-3 font-medium px-4 py-2.5 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {bookmakers.map(bk => (
                      <tr key={bk.bookmaker_id} className="border-b border-line/40 hover:bg-surface-1/40">
                        <td className="px-4 py-2.5 font-mono text-ink-3">{bk.bookmaker_id}</td>
                        <td className="px-4 py-2.5 text-ink-1 font-medium">{bk.bookmaker_name}</td>
                        <td className="px-4 py-2.5">
                          <span className={bk.ativo ? 'badge-green' : 'text-xs text-ink-4'}>
                            {bk.ativo ? 'Ativo' : 'Inativo'}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 font-mono text-ink-2">{bk.n_odds.toLocaleString('pt-BR')}</td>
                        <td className="px-4 py-2.5 font-mono text-ink-2">{bk.n_fixtures.toLocaleString('pt-BR')}</td>
                        <td className="px-4 py-2.5">
                          <div className="flex gap-2">
                            <button
                              className="text-[11px] text-ink-2 border border-line-strong rounded px-2 py-1 hover:text-ink-1 hover:border-accent/40 transition-colors"
                              onClick={() => setNovoBookmaker({
                                bookmaker_id: String(bk.bookmaker_id),
                                bookmaker_name: bk.bookmaker_name,
                              })}>
                              Editar
                            </button>
                            {bk.ativo && (
                              <button
                                className="text-[11px] text-red-400 border border-line-strong rounded px-2 py-1 hover:border-red-500/40 transition-colors"
                                onClick={async () => {
                                  if (!window.confirm(
                                    `Desativar "${bk.bookmaker_name}"?\n\n` +
                                    `As ${bk.n_odds.toLocaleString('pt-BR')} odds já coletadas ficam intactas, ` +
                                    `só a coleta futura ignora esta casa.`
                                  )) return
                                  try {
                                    const r = await api.delete(`/admin/bookmakers/${bk.bookmaker_id}`)
                                    showToast(r.data.aviso)
                                    carregarBookmakers()
                                  } catch (err: any) {
                                    showToast(err.response?.data?.detail || 'Erro ao desativar', false)
                                  }
                                }}>
                                Desativar
                              </button>
                            )}
                            {!bk.ativo && (
                              <button
                                className="text-[11px] text-ink-2 border border-line-strong rounded px-2 py-1 hover:text-ink-1 hover:border-accent/40 transition-colors"
                                onClick={async () => {
                                  try {
                                    await api.put(`/admin/bookmakers/${bk.bookmaker_id}`, {
                                      bookmaker_id: bk.bookmaker_id,
                                      bookmaker_name: bk.bookmaker_name,
                                      ativo: true,
                                    })
                                    showToast(`${bk.bookmaker_name} reativada.`)
                                    carregarBookmakers()
                                  } catch (err: any) {
                                    showToast(err.response?.data?.detail || 'Erro ao reativar', false)
                                  }
                                }}>
                                Reativar
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
            <p className="text-[11px] text-ink-4 px-4 py-3 border-t border-line leading-relaxed">
              Desativar para de coletar odds desta casa, e o histórico existente fica intacto.
              O ID é o mesmo que a API-Football usa internamente.
            </p>
          </div>
        </>)}

    </PageShell>
  )
}
