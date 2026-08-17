import { useEffect, useState, useCallback, useMemo, useRef, memo, lazy, Suspense } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { toastUp, fadeInUp, staggerContainer, tabFade } from '../lib/motion'
import api from '../services/api'
import { sinalizarNavegacao } from '../services/progressBus'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import SuggestionCard from '../components/SuggestionCard'
import ApostaModal from '../components/ApostaModal'
import PageShell from '../components/PageShell'
import Avatar from '../components/Avatar'
import {
  LiveDot, Spinner, EmptyState, SkeletonPickGrid, Badge, PickTypeBadge, ResultBadge,
} from '../components/ui'
import { aplicarFiltro, FILTRO_INICIAL, type MercadoFiltro } from '../lib/mercadoFiltro'
import EngineStatus from '../components/EngineStatus'
import AnalysisModal from '../components/AnalysisModal'
import {
  PickCardFooter, PickExplainButton, PickProbability, PickReasoning,
} from '../components/PickCardParts'
/*
 * As duas abas mais pesadas não entram no chunk desta página.
 *
 * Juntas são 68 KB de código-fonte, e o usuário cai sempre na aba "Hoje" ·
 * nenhuma das duas participa da primeira tela. O caso do feed é pior ainda:
 * ele só renderiza com LIVE_PICKS_ENABLED, que está DESLIGADA em produção,
 * então eram 24 KB embarcados em todo carregamento de Picks para código que
 * ninguém executa.
 *
 * `lazy()` aqui é seguro porque as duas já são montadas condicionalmente e
 * fazem o próprio polling · elas não guardam estado que a página precise antes
 * de o usuário trocar de aba.
 */
const LivePicks     = lazy(() => import('../components/LivePicks'))
const LivePicksFeed = lazy(() => import('../components/LivePicksFeed'))
import PicksPendingCard from '../components/PicksPendingCard'
import { LIVE_PICKS_ENABLED } from '../config'
import { UserCircle, Crown, Rocket, Wallet, Clock, ChevronLeft, ChevronRight, BrainCircuit, Share2, Check as CheckIcon, Loader2, SearchX, X as XIcon } from 'lucide-react'
import { calcFreeStake, calcMultiplaStake, calcProfitUnits } from '../utils/stakeUtils'
import {fmtUnits, pctProb } from '../utils/format'
import InfoTip from '../components/InfoTip'
import { getResultStyle, PICK_TYPE_CLS, PICK_TYPE_BORDER } from '../utils/resultStyle'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { useOddAtualizada } from '../hooks/useOddAtualizada'
import { translateMarket, translateLine, translateTeamName, explainMarket } from '../utils/marketTranslate'
import FilterPanel, { FilterGroup } from '../components/FilterPanel'
// Copa do Mundo 2026 · fase pelo match_date
function wcPhase(dateStr?: string): string | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const phases: [string, string, string][] = [
    ['2026-06-11', '2026-07-02', 'Grupos'],
    ['2026-07-03', '2026-07-10', 'Oitavas'],
    ['2026-07-11', '2026-07-17', 'Quartas'],
    ['2026-07-18', '2026-07-22', 'Semis'],
    ['2026-07-23', '2026-07-26', '3º Lugar'],
    ['2026-07-27', '2026-08-01', 'Final'],
  ]
  for (const [start, end, label] of phases) {
    if (d >= new Date(start) && d <= new Date(end)) return label
  }
  return null
}

// Helpers de logo
const TEAM_LOGO   = (id?: number) => id ? `/api/proxy/team/${id}.png` : null

const LEAGUE_LOGO = (id?: number) => id ? `/api/proxy/league/${id}.png` : null

function TeamLogo({ id, name, size = 24 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size} loading="lazy"
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

function LeagueLogo({ id, name, size = 18 }: { id?: number; name?: string; size?: number }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={size} height={size} loading="lazy"
      className="object-contain shrink-0 opacity-80" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

// Tipos
/* `aovivo` foi renomeada pra `minhas_apostas` em 2026-08-11.
 *
 * A chave dizia "ao vivo" e a aba mostrava Minhas Apostas · era o único nome
 * disponível pro produto novo de Picks Ao Vivo, que agora existe de verdade
 * (`ao_vivo`). Manter as duas com nomes parecidos garantiria que alguém
 * ligasse uma na outra mais cedo ou mais tarde.
 *
 * Links antigos (#aovivo) continuam abrindo Minhas Apostas · ver ALIAS_ABA.
 */
type Tab = 'hoje' | 'pick_seguro' | 'vip' | 'multiplas' | 'alavancagem' | 'mercados' | 'ao_vivo' | 'minhas_apostas' | 'chat'

/** Chave antiga na URL -> aba atual. */
const ALIAS_ABA: Record<string, Tab> = { aovivo: 'minhas_apostas' }

const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

interface AlavFilters { date_from: string; date_to: string; resultado: string }

/** Um caminho de alavancagem. `current_bankroll` é o bolo em jogo, não saldo:
 *  só vira dinheiro (e entra na banca) quando o caminho é encerrado. */
interface AlavStep {
  pick_id: number; result: 'GREEN' | 'RED'; odd: number
  date: string | null; match: string; before: number; after: number
}
interface AlavSerie {
  configured: boolean
  series_id?: number
  current_bankroll: number
  initial_bankroll: number
  steps?: AlavStep[]
  open_profit?: number
  can_close?: boolean
  meta?: number
  greens_no_caminho?: number
  realized_units?: number
  open_units?: number
  realized_total?: number
  history?: {
    id: number; initial: number; final: number; realized: number
    units: number; greens: number
    end_reason: 'manual' | 'red' | 'meta'; started_at: string | null; ended_at: string | null
  }[]
}
const defaultAlavFilters: AlavFilters = { date_from: '', date_to: TODAY, resultado: 'all' }

// Tab bar
function TabBar({ tab, setTab, canSeeVip, counts, liveCount, onPrefetch }: {
  tab: Tab; setTab: (t: Tab) => void; canSeeVip: boolean
  counts?: Partial<Record<Tab, number>>
  liveCount?: number
  /** Aquece os dados da aba antes do clique · ver `prefetchAba` no Picks. */
  onPrefetch?: (t: Tab) => void
}) {
  const tabs: { key: Tab; label: string; badge?: string; badgeCls?: string; premiumOnly?: boolean; oculta?: boolean }[] = [
    { key: 'hoje',         label: 'Hoje'            },
    { key: 'pick_seguro',  label: 'Picks Free',      badge: 'FREE', badgeCls: 'bg-green-500/10 text-green-400 border-green-500/20' },
    { key: 'vip',          label: 'Picks VIP',       premiumOnly: true },
    { key: 'multiplas',    label: 'Múltiplas',       premiumOnly: true },
    { key: 'alavancagem',  label: 'Alavancagem',      premiumOnly: true },
    { key: 'mercados',     label: 'Mercados',         premiumOnly: true },
    {
      /* O produto novo: oportunidades que o motor achou durante o jogo.
         "Picks Ao Vivo" e não "Ao Vivo" porque a barra já tem Picks Free e
         Picks VIP · o rótulo curto sugeria uma tela de jogos acontecendo, não
         um produto de pick, que é justamente a confusão que a renomeação de
         `aovivo` pra `minhas_apostas` veio desfazer.

         Sem badge próprio · o rótulo já diz o que é, e o selo VIP de
         `premiumOnly` já ocupa esse espaço. Dois selos na mesma aba viram
         ruído numa barra que rola no celular. */
      key: 'ao_vivo' as Tab, label: 'Picks Ao Vivo',
      premiumOnly: true,
      /* Fora da barra enquanto o Motor Live não roda em produção · ver
         LIVE_PICKS_ENABLED em config.ts. Filtrada logo abaixo em vez de
         removida daqui pra a aba voltar virando uma variável de ambiente, sem
         mexer no código. */
      oculta: !LIVE_PICKS_ENABLED,
    },
    {
      /* O que o usuário decidiu seguir. O contador pulsante continua aqui,
         porque é aqui que ele acompanha o dinheiro dele. */
      key: 'minhas_apostas' as Tab, label: 'Minhas Apostas',
      badge: (liveCount ?? 0) > 0 ? String(liveCount) : undefined,
      badgeCls: 'bg-red-500/20 text-red-300 border-red-400/40 animate-pulse',
    },
  ]

  return (
    <div className="relative mb-6 -mx-4">
      {/* Fade da direita indicando que a barra rola. Desbota de surface-0 pra
          surface-0/0, e nao pra `transparent`: transparent e' rgba(0,0,0,0),
          entao o degrade passaria pelo preto no meio e deixaria uma mancha
          escura na ponta da barra em vez de sumir. */}
      <div className="pointer-events-none absolute right-0 top-0 h-full w-10 bg-gradient-to-l from-surface-0 to-surface-0/0 z-10" />
      <div className="flex border-b border-line px-4 overflow-x-auto scrollbar-none">
        {tabs.filter(t => !t.oculta).map(t => {
          const count = counts?.[t.key]
          return (
            <motion.button
              key={t.key}
              whileTap={{ scale: 0.95 }}
              onClick={() => setTab(t.key)}
              /* Prefetch por intenção: no celular o `touchstart` chega antes do
                 `click`, e no desktop o ponteiro passa por cima antes de clicar.
                 São dezenas a centenas de milissegundos de vantagem, e nesse
                 tempo a requisição já saiu · o clique passa a encontrar o dado
                 pronto ou quase. `onFocus` cobre quem navega por teclado. */
              onPointerEnter={() => onPrefetch?.(t.key)}
              onTouchStart={() => onPrefetch?.(t.key)}
              onFocus={() => onPrefetch?.(t.key)}
              className={`relative px-3 sm:px-4 py-3 text-xs sm:text-sm font-semibold mr-1 whitespace-nowrap flex-shrink-0 transition-colors ${
                tab === t.key ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {t.label}
              {t.badge && (
                <span className={`ml-1.5 text-[10px] border px-1.5 py-0.5 rounded font-bold ${t.badgeCls ?? 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20'}`}>
                  {t.badge}
                </span>
              )}
              {t.premiumOnly && canSeeVip && (
                <span className="ml-1.5 text-[10px] bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 px-1.5 py-0.5 rounded font-bold">
                  VIP
                </span>
              )}
              {t.premiumOnly && !canSeeVip && (
                <svg className="ml-1 w-3 h-3 text-yellow-400 inline-block align-middle" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              )}
              {count != null && count > 0 && (
                <span className="ml-1 text-[10px] bg-green-500/15 text-green-400 border border-green-500/30 px-1.5 py-0.5 rounded font-black">
                  {count}
                </span>
              )}
              {tab === t.key ? (
                <motion.div layoutId="picks-tab-underline" className="absolute left-0 right-0 -bottom-px h-0.5 bg-green-500" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />
              ) : (
                <div className="absolute left-0 right-0 -bottom-px h-0.5 bg-transparent" />
              )}
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}

// User greeting
function UserGreeting({ user, isVip, isAdmin, daysUntilExpiry }: {
  user: any; isVip: boolean; isAdmin: boolean; daysUntilExpiry: number | null
}) {
  if (!user) return null
  const firstName = user.name.split(' ')[0]
  const isTrial = user.plan === 'trial'

  const planBadgeCls = isAdmin ? 'badge-admin' : isTrial ? 'badge-trial' : isVip ? 'badge-vip' : 'badge-free'
  const planLabel = isAdmin ? 'ADMIN' : isTrial ? 'TRIAL' : isVip ? 'VIP' : 'FREE'

  // Countdown ao vivo
  const [countdown, setCountdown] = useState('')
  useEffect(() => {
    // Admin nunca expira, e `isVip` inclui admin · sem esta exclusão o
    // contador lia o expires_at velho da conta e anunciava "Expira em
    // Expirado" pra quem tem acesso permanente. Profile.tsx já cortava assim.
    if (!user?.expires_at || isAdmin || (!isVip && !isTrial)) { setCountdown(''); return }
    const tick = () => {
      const diff = new Date(user.expires_at).getTime() - Date.now()
      if (diff <= 0) { setCountdown('Expirado'); return }
      const d = Math.floor(diff / 86400000)
      const h = Math.floor((diff % 86400000) / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setCountdown(`${d}d ${h}h ${m.toString().padStart(2,'0')}m ${s.toString().padStart(2,'0')}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [user?.expires_at, isVip, isTrial])

  return (
    <div className="card p-4 mb-5 flex items-center gap-4">
      <Avatar name={user.name} imageUrl={user.avatar_url} size="lg" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-ink-1 font-bold text-lg leading-tight">Olá, {firstName}!</h2>
          <span className={planBadgeCls}>{planLabel}</span>
        </div>
        <p className="text-ink-3 text-xs mt-0.5 truncate">{user.email}</p>

        {/* Assinatura inline.
            "Status atual: VIP" saiu daqui: o plano já aparece no badge ao lado
            do nome e de novo na navbar, e três vezes na mesma tela não informa
            mais que uma. Sobra o que o badge NÃO diz, que é quanto tempo falta. */}
        <div className="mt-2 flex items-center gap-3 flex-wrap">
          {countdown && (
            <span className="text-ink-2 text-xs">
              Expira em <span className="font-mono font-bold text-ink-1 tabular-nums">{countdown}</span>
            </span>
          )}
          {!isVip && !isAdmin && (
            <Link to="/planos" className="text-xs font-bold text-green-400 bg-green-500/10 border border-green-500/20 px-2.5 py-1 rounded-lg hover:bg-green-500/20 transition-colors">
              Assinar
            </Link>
          )}
        </div>
      </div>
      <div className="shrink-0 hidden sm:flex flex-col gap-1.5">
        <Link to="/profile" className="flex items-center justify-center gap-1.5 text-blue-400 hover:text-blue-300 transition-colors text-xs border border-blue-400/20 hover:border-blue-400/40 bg-blue-400/5 px-3 py-2 rounded-lg font-semibold">
          <UserCircle className="w-3.5 h-3.5" />
          Editar perfil
        </Link>
        {!isAdmin && (isVip || isTrial) && (
          <Link to="/planos" className="flex items-center justify-center gap-1.5 text-yellow-400 hover:text-yellow-300 transition-colors text-xs border border-yellow-400/20 hover:border-yellow-400/40 bg-yellow-400/5 px-3 py-2 rounded-lg font-semibold">
            <Crown className="w-3.5 h-3.5" />
            Meu Plano
          </Link>
        )}
        {!isAdmin && !isVip && !isTrial && (
          <Link to="/checkout" className="flex items-center justify-center gap-1.5 text-yellow-400 hover:text-yellow-300 transition-colors text-xs border border-yellow-400/20 hover:border-yellow-400/40 bg-yellow-400/5 px-3 py-2 rounded-lg font-semibold">
            <Rocket className="w-3.5 h-3.5" />
            Upgrade VIP
          </Link>
        )}
      </div>
    </div>
  )
}

// Pick do Dia card
function shortReasoning(text?: string): string {
  if (!text) return ''
  const fatoMatch = text.match(/FATO:\s*(.+?)(?=\s*ANÁLISE:|$)/i)
  if (fatoMatch) return fatoMatch[1].trim()
  return text.slice(0, 130)
}

function PickSeguroCardBase({ dica, compact = false, onClick, banca, isLive = false }: { dica: any; compact?: boolean; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null; isLive?: boolean }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const navigate = useNavigate()
  // probability quando existir; confidence e' o fallback dos picks antigos
  const pct = Math.round(Number(dica.probability ?? dica.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState(dica.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalOdd, setModalOdd] = useState(Number(dica.odd))
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  /*
   * O que o usuário registrou · ver o comentário gêmeo em SuggestionCard.tsx.
   *
   * Este card era pior que o outro: além de não atualizar depois de registrar,
   * ele NUNCA teve o estado "Apostado". Com o pick pendente ele sempre mostrava
   * a stake SUGERIDA e a odd DO PICK, mesmo depois de recarregar a página e
   * mesmo com a aposta gravada em user_followed_picks.
   *
   * Caso real (17/08/2026, Internacional x Remo): registrou 6u a 1.52 e o card
   * seguiu anunciando "Apostar 2u", odd 1.75 e "Lucro pot. +1.50u". Os três
   * números descreviam uma aposta que não era a dele.
   */
  const [registrado, setRegistrado] = useState<
    { stakeUnits: number; actualOdd: number; betHouse: string } | null
  >(null)
  const seguido      = registrado != null || (dica.is_followed ?? false)
  const stakeSeguida = registrado?.stakeUnits ?? dica.user_stake_units ?? null
  const oddSeguida   = registrado?.actualOdd ?? dica.user_actual_odd ?? null
  const casaSeguida  = registrado?.betHouse ?? dica.user_bet_house ?? null
  const { share: shareStory, sharing, shared } = useShareStoryImage()
  const { odd: buscarOdd, buscando: buscandoOdd } = useOddAtualizada()
  // Prioridade: suggested_stake_units do backend, senão calcFreeStake fallback (max 2%)
  const stakeSuggestion = (() => {
    if (!banca) return null
    if (dica.suggested_stake_units != null && dica.suggested_stake_units > 0) {
      const units = dica.suggested_stake_units
      return { units, amountR: units * banca.unit_value }
    }
    return calcFreeStake(
      Number(dica.prob_real ?? dica.confidence ?? 0),
      Number(dica.odd),
      Number(dica.ev ?? 0),
      banca.bankroll_current,
      banca.unit_value,
    )
  })()
  const fato = shortReasoning(dica.reasoning)

  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation()
    shareStory({
      pickId: dica.id,
      pickTypeRoute: 'free',
      homeTeamName: translateTeamName(dica.home_team),
      awayTeamName: translateTeamName(dica.away_team),
      homeTeamId: dica.home_team_id,
      awayTeamId: dica.away_team_id,
      leagueName: dica.league_name,
      pickType: 'free',
      market: translateMarket(dica.market),
      line: translateLine(dica.line),
      odd: Number(dica.odd),
      probabilityPct: pctProb(dica.probability ?? dica.confidence),
      result: dica.result,
      profit: dica.result
        ? calcProfitUnits(dica.result, Number(dica.odd), dica.user_stake_units ?? 1,
                          dica.user_stake_units != null ? dica.user_actual_odd : null)
        : null,
    })
  }

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    const { odd } = await buscarOdd(Number(dica.odd), {
      fixture_id: dica.fixture_id,
      market_type: dica.market_type,
      line: dica.line,
    })
    setModalOdd(odd)
    setShowModal(true)
  }

  const handleConfirm = async (actualOdd: number, betHouse: string, stakeUnits: number) => {
    setFollowing(true)
    setApiError(null)
    try {
      await api.post('/banca/follow', { pick_id: dica.id, pick_type: 'free', stake_units: stakeUnits, actual_odd: actualOdd, bet_house: betHouse })
      setFollowed(true)
      setRegistrado({ stakeUnits, actualOdd, betHouse })
      setShowModal(false)
      setShowSuccess(true)
      setTimeout(() => setShowSuccess(false), 3000)
    } catch (err: any) {
      setApiError(err?.response?.data?.detail ?? 'Erro ao registrar aposta. Tente novamente.')
    } finally {
      setFollowing(false)
    }
  }

  const isCopa = dica.league_id === 1
  // Hora do jogo por slice de string: match_datetime e' horario de Brasilia
  // SEM fuso, e `new Date` sobre ele desloca o horario. Mesma leitura do VIP.
  const kickoff = dica.match_datetime ? String(dica.match_datetime).slice(11, 16) : null

  return (
  <>
    <motion.div
      variants={fadeInUp}
      whileHover={onClick ? { y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' } : undefined}
      whileTap={onClick ? { scale: 0.985 } : undefined}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className={`pick-card group ${isCopa ? 'border-yellow-500/20' + (onClick ? ' hover:border-yellow-500/40' : '') : PICK_TYPE_BORDER.free} ${onClick ? 'cursor-pointer' : ''}`}
      onClick={onClick}
    >
      {/* Header · MESMA anatomia do card VIP (SuggestionCard).
          Aqui era tudo desenhado a mao: "Pick do Dia" + badge-free em vez do
          PickTypeBadge, spans proprios no lugar de ResultBadge/Badge, sem o
          horario do jogo, e ainda uma barrinha de gradiente no topo que o VIP
          nao tem. Cada diferenca dessas era invisivel isolada e obvia com os
          dois cards lado a lado. */}
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <PickTypeBadge type="free" />
          {(dica.league_id || dica.league_name) && (
            <div className="flex items-center gap-1 min-w-0">
              <LeagueLogo id={dica.league_id} name={dica.league_name} />
              {dica.league_name && <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{dica.league_name}</span>}
            </div>
          )}
          {kickoff && (
            <span className="flex items-center gap-1 text-[10px] text-ink-4 shrink-0">
              <Clock className="w-3 h-3" />
              {kickoff}
            </span>
          )}
        </div>
        {dica.result ? (
          <ResultBadge result={dica.result} />
        ) : isLive ? (
          <Badge tone="red" className="animate-pulse">Ao vivo</Badge>
        ) : (
          <Badge tone="neutral">Pendente</Badge>
        )}
      </div>

      {/* Hero: Odd | Stake | Retorno */}
      <div className="font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
          <div className="text-3xl font-black text-green-400">
            {seguido && oddSeguida != null
              ? Number(oddSeguida).toFixed(2)
              : Number(dica.odd).toFixed(2)}
          </div>
          {seguido && oddSeguida != null && Math.abs(oddSeguida - Number(dica.odd)) > 0.001 && (
            <div className="text-[9px] text-ink-4 mt-0.5">pick: {Number(dica.odd).toFixed(2)}</div>
          )}
          <div className="text-[10px] text-ink-4 mt-0.5">{seguido && casaSeguida ? casaSeguida : dica.bet_house}</div>
        </div>
        {!dica.result && seguido && stakeSeguida != null ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostado</div>
              <div className="text-xl font-black text-green-400">{stakeSeguida}u</div>
              {banca && <div className="text-[11px] text-ink-4">R${(stakeSeguida * banca.unit_value).toFixed(0)}</div>}
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              {(() => {
                const effOdd = oddSeguida ?? Number(dica.odd)
                const profitU = (effOdd - 1) * stakeSeguida
                return (
                  <>
                    <div className="text-xl font-black text-ink-1">+{profitU.toFixed(2)}u</div>
                    {banca && <div className="text-[11px] text-green-600 font-semibold">+R${(profitU * banca.unit_value).toFixed(0)}</div>}
                  </>
                )
              })()}
            </div>
          </>
        ) : stakeSuggestion && !dica.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-green-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-ink-4">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-ink-1">+{((Number(dica.odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
              <div className="text-[11px] text-green-600 font-semibold">+R${((Number(dica.odd) - 1) * stakeSuggestion.amountR).toFixed(0)}</div>
            </div>
          </>
        ) : dica.result ? (
          (() => {
            /* Dinheiro só pra quem apostou · ver SuggestionCard: a stake caía
               pra sugestão quando o usuário NÃO seguiu, e o card anunciava um
               ganho que ele nunca teve, na conta da banca dele. */
            const seguiu = stakeSeguida != null
            const u = seguiu ? stakeSeguida! : 1
            const p = calcProfitUnits(dica.result, Number(dica.odd), u, seguiu ? oddSeguida : null)
            const color = p >= 0 ? 'text-green-400' : 'text-red-400'
            const profitR = seguiu && banca ? Math.abs(p) * banca.unit_value : null
            return (
              <>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">{seguiu ? 'Seu lucro' : 'Lucro do pick'}</div>
                  <div className={`text-xl font-black ${color}`}>
                    {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  </div>
                  <div className="text-[10px] text-ink-4">{seguiu ? `(${u}u)` : 'por 1u'}</div>
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  {seguiu ? (
                    <>
                      <div className="text-[10px] text-ink-3 mb-0.5">Em reais</div>
                      {profitR != null ? (
                        <div className={`text-xl font-black ${color}`}>
                          {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                        </div>
                      ) : (
                        <div className="text-xl font-black text-ink-4">-</div>
                      )}
                    </>
                  ) : (
                    <>
                      {/* Vocabulário do próprio card: o botão vira "Registrado"
                          quando a aposta é seguida, então o oposto é este. */}
                      <div className="text-[10px] text-ink-3 mb-0.5">Sua aposta</div>
                      <div className="text-sm font-semibold text-ink-4 pt-1.5">Não registrada</div>
                    </>
                  )}
                </div>
              </>
            )
          })()
        ) : (
          <div className="flex-1 px-4 py-3 text-center">
            {dica.ev != null ? (
              <>
                <div className="text-[10px] text-ink-3 mb-0.5">EV</div>
                <div className={`text-xl font-black ${Number(dica.ev) >= 0 ? 'text-green-400' : 'text-orange-400'}`}>
                  {Number(dica.ev) >= 0 ? '+' : ''}{(Number(dica.ev) * 100).toFixed(1)}%
                </div>
              </>
            ) : (
              <>
                <div className="text-[10px] text-ink-3 mb-0.5">Probabilidade</div>
                <div className={`text-xl font-black ${pct >= 75 ? 'text-green-400' : 'text-ink-2'}`}>{pct}%</div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Times + mercado */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={dica.home_team_id} name={dica.home_team ?? ''} size={22} />
          <span className="text-sm font-bold text-ink-1 truncate">{dica.home_team}</span>
          <span className="text-ink-4 text-xs shrink-0">vs</span>
          <span className="text-sm font-bold text-ink-1 truncate">{dica.away_team}</span>
          <TeamLogo id={dica.away_team_id} name={dica.away_team ?? ''} size={22} />
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3">
          <span className="font-semibold text-ink-2">{translateMarket(dica.market)}</span>
          {dica.line && <><span>·</span><span>{translateLine(dica.line)}</span></>}
          <InfoTip text={explainMarket(dica.market, dica.line)} />
        </div>
      </div>

      <PickProbability confidence={dica.confidence} probability={dica.probability} />

      <PickReasoning text={fato} />

      {/* Footer */}
      {dica.reasoning && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!dica.result ? (banca ? handleFollow : () => navigate('/banca')) : undefined}
        betState={following || buscandoOdd ? 'loading' : followed ? 'done' : 'idle'}
        hasBanca={!!banca}
        onShare={handleShare}
        shareState={sharing ? 'loading' : shared ? 'done' : 'idle'}
      />
    </motion.div>
    <AnimatePresence>
    {showAnalysis && (
      <AnalysisModal
        onClose={() => setShowAnalysis(false)}
        data={{
          market: translateMarket(dica.market),
          line: translateLine(dica.line),
          // Crus, pra regra do mercado: explainMarket casa por chave em inglês.
          marketRaw: dica.market,
          lineRaw: dica.line,
          pickId: dica.id,
          pickType: 'free',
          odd: Number(dica.odd),
          confidence: dica.confidence,
          probability: dica.probability ?? null,
          ev: dica.ev ?? null,
          reasoning: dica.reasoning,
          homeTeam: dica.home_team,
          awayTeam: dica.away_team,
        }}
      />
    )}
    </AnimatePresence>

    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={modalOdd}
        originalOdd={Number(dica.odd)}
        suggestedUnits={stakeSuggestion?.units ?? 1}
        suggestedHouse={dica.bet_house}
        maxUnits={Math.max(6, stakeSuggestion?.units ?? 6)}
        onConfirm={handleConfirm}
        onCancel={() => setShowModal(false)}
        loading={following}
        error={apiError}
      />
    )}
    </AnimatePresence>
    <AnimatePresence>
    {showSuccess && (
      <motion.div
        variants={toastUp} initial="hidden" animate="visible" exit="exit"
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-ink-1 text-sm font-semibold px-5 py-3 rounded-md shadow-lg whitespace-nowrap"
      >
        Pick registrado com sucesso!
      </motion.div>
    )}
    </AnimatePresence>
  </>
  )
}

// Vazio do Pick Seguro
function PickSeguroEmpty() {
  const msg = 'Nenhum Pick do Dia disponível para hoje.'

  return (
    <div className="card p-10 text-center border-dashed">
      <p className="text-ink-3 text-sm font-semibold mb-1">Pick do Dia indisponível</p>
      <p className="text-ink-4 text-xs">{msg}</p>
    </div>
  )
}

// Múltipla card
function MultiplaCardBase({ m, onClick, banca, isLive = false }: { m: any; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null; isLive?: boolean }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const navigate = useNavigate()
  let legs: any[] = []
  try { legs = typeof m.legs === 'string' ? JSON.parse(m.legs) : (m.legs ?? []) } catch { legs = [] }

  // Multipla nao tem coluna de probabilidade: score_combo entra como aproximacao
  const pct = Math.round(Number(m.probability ?? m.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState<boolean>(!!m.is_followed)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalOdd, setModalOdd] = useState<number | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  // Mesmo defeito e mesma correção do PickSeguroCard acima: sem isto o card
  // segue anunciando a stake sugerida e a odd do bilhete depois de registrado.
  const [registrado, setRegistrado] = useState<
    { stakeUnits: number; actualOdd: number; betHouse: string } | null
  >(null)
  const seguido      = registrado != null || !!m.is_followed
  const stakeSeguida = registrado?.stakeUnits ?? m.user_stake_units ?? null
  const oddSeguida   = registrado?.actualOdd ?? m.user_actual_odd ?? null
  const { share: shareStory, sharing, shared } = useShareStoryImage()
  const { oddBilhete, buscando: buscandoBilhete } = useOddAtualizada()
  // Prioridade: suggested_stake_units do backend, senão calcMultiplaStake fallback (max 2.5%)
  const stakeSuggestion = (() => {
    if (!banca) return null
    if (m.suggested_stake_units != null && m.suggested_stake_units > 0) {
      const units = m.suggested_stake_units
      return { units, amountR: units * banca.unit_value }
    }
    return calcMultiplaStake(
      Number(m.confidence ?? 0),
      Number(m.total_odd),
      banca.bankroll_current,
      banca.unit_value,
    )
  })()
  const potReturn = stakeSuggestion
    ? (stakeSuggestion.amountR * Number(m.total_odd)).toFixed(2)
    : null

  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation()
    shareStory({
      pickId: m.id,
      pickTypeRoute: 'multipla',
      homeTeamName: translateTeamName(legs[0]?.home ?? legs[0]?.home_team) || 'Múltipla',
      awayTeamName: legs.length > 1 ? `+${legs.length - 1} jogo${legs.length - 1 > 1 ? 's' : ''}` : undefined,
      homeTeamId: legs[0]?.home_team_id,
      awayTeamId: legs[0]?.away_team_id,
      pickType: 'multipla',
      market: `Múltipla · ${legs.length} seleções`,
      odd: Number(m.total_odd),
      probabilityPct: pctProb(m.probability ?? m.confidence),
      result: m.result,
      profit: m.result
        ? calcProfitUnits(m.result, Number(m.total_odd), m.user_stake_units ?? 1,
                          m.user_stake_units != null ? m.user_actual_odd : null)
        : null,
    })
  }

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following || followed) return
    // Bilhete não tem odd numa casa: o backend reconsulta cada perna e refaz o
    // produto. Perna que não puder ser atualizada entra com a odd salva.
    const { odd } = await oddBilhete(Number(m.total_odd), m.id, 'multipla')
    setModalOdd(odd)
    setShowModal(true)
  }

  const handleConfirm = async (actualOdd: number, betHouse: string, stakeUnits: number) => {
    setFollowing(true)
    setApiError(null)
    try {
      await api.post('/banca/follow', {
        pick_id: m.id,
        pick_type: 'multipla',
        stake_units: stakeUnits,
        actual_odd: actualOdd,
        bet_house: betHouse,
      })
      setFollowed(true)
      setRegistrado({ stakeUnits, actualOdd, betHouse })
      setShowModal(false)
      setShowSuccess(true)
      setTimeout(() => setShowSuccess(false), 3000)
    } catch (err: any) {
      setApiError(err?.response?.data?.detail ?? 'Erro ao registrar aposta. Tente novamente.')
    } finally {
      setFollowing(false)
    }
  }

  const resultStyle = getResultStyle(m.result)

  return (
  <>
    <motion.div
      variants={fadeInUp}
      whileHover={onClick ? { y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' } : undefined}
      whileTap={onClick ? { scale: 0.985 } : undefined}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className={`pick-card group ${onClick ? 'cursor-pointer' : ''} ${PICK_TYPE_BORDER.multipla}`}
      onClick={onClick}
    >
      {/* Accent bar */}
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-blue-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2">
          <span className="text-xs font-black text-blue-400">Múltipla</span>
          <span className="badge-vip">VIP</span>
          <span className="text-[10px] text-ink-4">
            {new Date(m.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}
            {' · '}{legs.length} seleções
          </span>
          {legs.length >= 2 && legs[0]?.home && legs[1]?.home && (
            <span className="text-[9px] text-ink-3 truncate max-w-[140px]">
              {legs[0].home} · {legs[1].home}
            </span>
          )}
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label}
          </span>
        ) : isLive ? (
          <span className="flex items-center gap-1 text-[10px] font-black text-red-300 bg-red-500/20 border border-red-400/40 px-2 py-1 rounded-lg animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400" /> AO VIVO
          </span>
        ) : (
          <span className="text-[10px] text-ink-3 border border-line px-2 py-1 rounded-lg">Pendente</span>
        )}
      </div>

      {/* Odd hero + retorno */}
      <div className="font-mono flex items-center gap-0 divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">Odd combinada</div>
          <div className="text-3xl font-black text-green-400">
            {seguido && oddSeguida != null
              ? Number(oddSeguida).toFixed(2)
              : Number(m.total_odd).toFixed(2)}
          </div>
          {seguido && oddSeguida != null && Math.abs(oddSeguida - Number(m.total_odd)) > 0.001 && (
            <div className="text-[9px] text-ink-4 mt-0.5">bilhete: {Number(m.total_odd).toFixed(2)}</div>
          )}
        </div>
        {!m.result && seguido && stakeSeguida != null ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostado</div>
              <div className="text-xl font-black text-blue-400">{stakeSeguida}u</div>
              {banca && <div className="text-[11px] text-ink-4">R${(stakeSeguida * banca.unit_value).toFixed(0)}</div>}
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              {(() => {
                const effOdd = oddSeguida ?? Number(m.total_odd)
                const profitU = (effOdd - 1) * stakeSeguida
                return (
                  <>
                    <div className="text-xl font-black text-ink-1">+{profitU.toFixed(2)}u</div>
                    {banca && <div className="text-[11px] text-green-600 font-semibold">+R${(profitU * banca.unit_value).toFixed(0)}</div>}
                  </>
                )
              })()}
            </div>
          </>
        ) : stakeSuggestion && !m.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-blue-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-ink-4">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-ink-1">+{((Number(m.total_odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
              <div className="text-[11px] text-green-600 font-semibold">+R${((Number(m.total_odd) - 1) * stakeSuggestion.amountR).toFixed(0)}</div>
            </div>
          </>
        ) : m.result ? (
          (() => {
            /* Dinheiro só pra quem apostou · ver SuggestionCard: a stake caía
               pra sugestão quando o usuário NÃO seguiu, e o card anunciava um
               ganho que ele nunca teve, na conta da banca dele. */
            const seguiu = stakeSeguida != null
            const u = seguiu ? stakeSeguida! : 1
            const p = calcProfitUnits(m.result, Number(m.total_odd), u, seguiu ? oddSeguida : null)
            const color = p >= 0 ? 'text-green-400' : 'text-red-400'
            const profitR = seguiu && banca ? Math.abs(p) * banca.unit_value : null
            return (
              <>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">{seguiu ? 'Seu lucro' : 'Lucro do pick'}</div>
                  <div className={`text-xl font-black ${color}`}>
                    {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  </div>
                  <div className="text-[10px] text-ink-4">{seguiu ? `(${u}u)` : 'por 1u'}</div>
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  {seguiu ? (
                    <>
                      <div className="text-[10px] text-ink-3 mb-0.5">Em reais</div>
                      {profitR != null ? (
                        <div className={`text-xl font-black ${color}`}>
                          {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                        </div>
                      ) : (
                        <div className="text-xl font-black text-ink-4">-</div>
                      )}
                    </>
                  ) : (
                    <>
                      {/* Vocabulário do próprio card: o botão vira "Registrado"
                          quando a aposta é seguida, então o oposto é este. */}
                      <div className="text-[10px] text-ink-3 mb-0.5">Sua aposta</div>
                      <div className="text-sm font-semibold text-ink-4 pt-1.5">Não registrada</div>
                    </>
                  )}
                </div>
              </>
            )
          })()
        ) : (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">Probabilidade</div>
            <div className={`text-2xl font-black ${pct >= 70 ? 'text-green-400' : 'text-ink-2'}`}>{pct}%</div>
          </div>
        )}
      </div>

      {/* Legs */}
      <div className="px-5 py-3 space-y-2">
        {legs.map((leg: any, i: number) => {
          /*
           * A PERNA MOSTRA O RESULTADO DELA, não o do bilhete.
           *
           * Antes, bilhete RED pintava de vermelho toda perna que não tivesse
           * um GREEN explícito · e como o resultado por perna nunca era gravado
           * (o caminho de resolução automática só salvava o do bilhete, ver
           * _gravar_resultado_das_pernas em routers/live.py), "sem GREEN
           * explícito" era SEMPRE. Numa múltipla de duas em que uma bateu, o
           * usuário via duas derrotas, uma delas inventada pela tela.
           *
           * Bilhete GREEN continua implicando todas as pernas GREEN · aí é
           * dedução, não palpite: combinada só paga com todas as pernas de pé.
           *
           * Sem o dado da perna e bilhete RED, o estado é NEUTRO. Não sabemos
           * qual delas caiu, e chutar vermelho em todas é pior do que admitir
           * que não sabemos: o placar do bilhete já está no topo do card.
           */
          const lr = (
            leg.result ?? (m.result === 'GREEN' ? 'GREEN' : undefined)
          ) as 'GREEN' | 'RED' | undefined
          const boxClass = lr === 'GREEN'
            ? 'border-green-500/20 bg-green-500/5'
            : lr === 'RED'
            ? 'border-red-500/20 bg-red-500/5'
            : 'border-line bg-surface-1/60'
          const circleClass = lr === 'GREEN'
            ? 'bg-green-500/20 text-green-400'
            : lr === 'RED'
            ? 'bg-red-500/20 text-red-400'
            : 'bg-blue-500/10 text-blue-400'
          return (
          <div key={i} className={`rounded-md border px-3 py-2 ${boxClass}`}>
            <div className="flex items-center gap-2">
              <span className={`w-5 h-5 flex items-center justify-center rounded-full ${circleClass} text-[10px] font-black shrink-0`}>
                {lr === 'GREEN' ? '✓' : lr === 'RED' ? '✗' : i + 1}
              </span>
              <div className="flex items-center gap-1.5 flex-1 min-w-0">
                <TeamLogo id={leg.home_team_id} name={leg.home ?? leg.home_team ?? ''} size={20} />
                <span className="text-xs text-ink-2 font-semibold truncate">{leg.home ?? leg.home_team}</span>
                <span className="text-ink-4 text-[10px] shrink-0">vs</span>
                <span className="text-xs text-ink-2 font-semibold truncate">{leg.away ?? leg.away_team}</span>
                <TeamLogo id={leg.away_team_id} name={leg.away ?? leg.away_team ?? ''} size={20} />
              </div>
              <span className={`font-mono font-black text-sm shrink-0 ${lr === 'GREEN' ? 'text-green-400' : lr === 'RED' ? 'text-red-400' : 'text-blue-300'}`}>
                {Number(leg.odd).toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-1.5 ml-7 text-xs mt-1">
              <span className="font-semibold text-ink-2">{translateMarket(leg.market)}</span>
              {leg.line && <><span className="text-ink-4">·</span><span className="text-ink-2">{translateLine(leg.line)}</span></>}
              <InfoTip text={explainMarket(leg.market, leg.line)} />
            </div>
          </div>
          )
        })}
      </div>

      <PickProbability
        confidence={m.confidence}
        probability={m.probability}
        label="Probabilidade combinada"
      />

      <PickReasoning text={shortReasoning(m.reasoning)} />

      {/* Footer */}
      {m.reasoning && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!m.result ? (banca ? handleFollow : () => navigate('/banca')) : undefined}
        betState={following || buscandoBilhete ? 'loading' : followed ? 'done' : 'idle'}
        hasBanca={!!banca}
        onShare={handleShare}
        shareState={sharing ? 'loading' : shared ? 'done' : 'idle'}
      />
    </motion.div>
    <AnimatePresence>
    {showAnalysis && (
      <AnalysisModal
        onClose={() => setShowAnalysis(false)}
        data={{
          market: 'Múltipla',
          line: `${m.games?.length ?? 0} seleções`,
          odd: Number(m.total_odd),
          confidence: m.confidence ?? null,
          probability: null,
          ev: m.ev ?? null,
          reasoning: m.reasoning,
          homeTeam: legs[0]?.home ?? legs[0]?.home_team,
          awayTeam: legs.length > 1 ? `+${legs.length - 1} jogo${legs.length - 1 > 1 ? 's' : ''}` : (legs[0]?.away ?? legs[0]?.away_team),
          // A série vem PERNA A PERNA · não existe uma que descreva o bilhete.
          pickId: m.id,
          pickType: 'multipla',
          // Regra perna a perna: e' o "igual aos outros pipelines" possivel
          // num bilhete de varios mercados.
          legs: (m.games ?? []).map((g: any) => ({ market: g.market, line: g.line, odd: g.odd })),
        }}
      />
    )}
    </AnimatePresence>
    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={modalOdd ?? Number(m.total_odd)}
        originalOdd={Number(m.total_odd)}
        suggestedUnits={stakeSuggestion?.units ?? 1}
        maxUnits={Math.max(10, stakeSuggestion?.units ?? 10)}
        onConfirm={handleConfirm}
        onCancel={() => setShowModal(false)}
        loading={following}
        error={apiError}
      />
    )}
    </AnimatePresence>
    <AnimatePresence>
    {showSuccess && (
      <motion.div
        variants={toastUp} initial="hidden" animate="visible" exit="exit"
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-ink-1 text-sm font-semibold px-5 py-3 rounded-md shadow-lg whitespace-nowrap"
      >
        Pick registrado com sucesso!
      </motion.div>
    )}
    </AnimatePresence>
  </>
  )
}

// Alavancagem card
function AlavancagemCardBase({ pick, onClick, userBankroll, onConfigureBanca, isLive = false }: { pick: any; onClick?: () => void; userBankroll?: number; onConfigureBanca?: () => void; isLive?: boolean }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const navigate    = useNavigate()
  const isCombo     = pick.tipo === 'dupla' || pick.tipo === 'tripla' || pick.tipo === 'combinacao'
  const comboLabel  = pick.tipo === 'tripla' ? 'Tripla' : pick.tipo === 'dupla' ? 'Dupla' : 'Combinada'
  const oddCombined = Number(pick.odd_combined ?? 0)
  // stake monetário: bankroll do usuário > bankroll_before salvo > fallback 50
  const stake       = userBankroll != null ? userBankroll : Number(pick.bankroll_before ?? pick.stake ?? 50)
  const potReturn   = oddCombined > 0 ? stake * oddCombined : Number(pick.potential_return ?? 0)
  // profit calculado do bankroll real × odd (não usa o campo profit do DB que pode estar em unidades)
  const profit = pick.result === 'GREEN'
    ? stake * (oddCombined - 1)
    : pick.result === 'RED'
    ? -stake
    : null
  const [followed, setFollowed] = useState<boolean>(!!pick.is_followed)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalOdd, setModalOdd] = useState<number | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()
  const { oddBilhete, buscando: buscandoBilhete } = useOddAtualizada()

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following || followed) return
    // Mesma reconsulta perna a perna da múltipla · alavancagem também é bilhete.
    const { odd } = await oddBilhete(Number(pick.odd_combined), pick.id, 'alavancagem')
    setModalOdd(odd)
    setShowModal(true)
  }

  const handleConfirm = async (actualOdd: number, betHouse: string, stakeUnits: number) => {
    setFollowing(true)
    setApiError(null)
    try {
      await api.post('/banca/follow', { pick_id: pick.id, pick_type: 'alavancagem', stake_units: stakeUnits, actual_odd: actualOdd, bet_house: betHouse })
      setFollowed(true)
      setShowModal(false)
      setShowSuccess(true)
      setTimeout(() => setShowSuccess(false), 3000)
    } catch (err: any) {
      setApiError(err?.response?.data?.detail ?? 'Erro ao registrar aposta. Tente novamente.')
    } finally {
      setFollowing(false)
    }
  }

  const legs: any[] = []
  if (pick.home_team_1) legs.push({ home: pick.home_team_1, away: pick.away_team_1, homeId: pick.home_team_id_1, awayId: pick.away_team_id_1, market: pick.market_1, line: pick.line_1, odd: pick.odd_1, house: pick.bet_house_1 })
  if (isCombo && pick.home_team_2) legs.push({ home: pick.home_team_2, away: pick.away_team_2, homeId: pick.home_team_id_2, awayId: pick.away_team_id_2, market: pick.market_2, line: pick.line_2, odd: pick.odd_2, house: pick.bet_house_2 })
  if (pick.home_team_3) legs.push({ home: pick.home_team_3, away: pick.away_team_3, homeId: pick.home_team_id_3, awayId: pick.away_team_id_3, market: pick.market_3, line: pick.line_3, odd: pick.odd_3, house: pick.bet_house_3 })

  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation()
    shareStory({
      pickId: pick.id,
      pickTypeRoute: 'alavancagem',
      homeTeamName: translateTeamName(legs[0]?.home) || 'Alavancagem',
      awayTeamName: translateTeamName(legs[0]?.away),
      homeTeamId: legs[0]?.homeId,
      awayTeamId: legs[0]?.awayId,
      pickType: 'alavancagem',
      market: isCombo ? `${comboLabel} · ${legs.length} jogos` : translateMarket(legs[0]?.market),
      line: translateLine(legs[0]?.line),
      odd: oddCombined,
      result: pick.result,
      profit: pick.result === 'GREEN' ? (oddCombined - 1) : pick.result === 'RED' ? -1 : null,
    })
  }

  const resultStyle = getResultStyle(pick.result)

  return (
  <>
    <motion.div
      variants={fadeInUp}
      whileHover={onClick ? { y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' } : undefined}
      whileTap={onClick ? { scale: 0.985 } : undefined}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className={`pick-card group ${onClick ? 'cursor-pointer' : ''} ${PICK_TYPE_BORDER.alavancagem}`}
      onClick={onClick}
    >
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-orange-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-black text-orange-400">Alavancagem</span>
          <span className="badge-vip">VIP</span>
          {isCombo && <span className="text-[10px] text-blue-400 border border-blue-400/20 bg-blue-400/10 px-2 py-0.5 rounded-md font-bold">{comboLabel}</span>}
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label}
          </span>
        ) : isLive ? (
          <span className="flex items-center gap-1 text-[10px] font-black text-red-300 bg-red-500/20 border border-red-400/40 px-2 py-1 rounded-lg animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400" /> AO VIVO
          </span>
        ) : (
          <span className="text-[10px] text-yellow-500 border border-yellow-500/20 bg-yellow-500/10 px-2 py-1 rounded-lg font-bold">Pendente</span>
        )}
      </div>

      {/* Bankroll progression */}
      <div className="px-5 py-3 border-b border-line/60">
        {userBankroll != null ? (
          <div className="font-mono flex items-center gap-3">
            <div className="flex-1">
              <div className="text-[10px] text-ink-3 mb-1">Sua banca alavancagem</div>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-black text-orange-400">R${stake.toFixed(2)}</span>
                {!pick.result && (
                  <>
                    <span className="text-ink-4 text-sm">·</span>
                    <span className="text-lg font-black text-ink-1">R${potReturn.toFixed(2)}</span>
                    <span className="text-[10px] text-ink-4">se green</span>
                  </>
                )}
                {profit != null && (
                  <span className={`text-lg font-black ml-1 ${profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ({profit >= 0 ? '+' : ''}R${Math.abs(profit).toFixed(2)})
                  </span>
                )}
              </div>
            </div>
            <div className="text-center shrink-0">
              <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
              <div className="text-2xl font-black text-green-400">{oddCombined.toFixed(2)}</div>
            </div>
          </div>
        ) : (
          <div className="font-mono flex items-center justify-between">
            <div>
              <div className="text-[10px] text-ink-3 mb-0.5">Odd alvo</div>
              <div className="text-2xl font-black text-green-400">{oddCombined.toFixed(2)}</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-ink-3 mb-0.5">Retorno pot.</div>
              <div className="text-lg font-black text-ink-1">R${potReturn.toFixed(2)}</div>
              <div className="text-[10px] text-ink-4">base R${stake.toFixed(0)}</div>
            </div>
          </div>
        )}
      </div>

      {/* Legs */}
      <div className="px-5 py-3 space-y-2">
        {legs.map((leg, i) => {
          /* Mesma regra da múltipla: bilhete GREEN implica todas as pernas de
             pé (dedução), mas bilhete RED NÃO diz qual perna caiu. Alavancagem
             guarda as pernas em colunas numeradas e não tem coluna de resultado
             por perna, então aqui o estado só pode ser verde ou neutro · pintar
             as duas de vermelho seria inventar a que bateu. */
          const lr: 'GREEN' | undefined = pick.result === 'GREEN' ? 'GREEN' : undefined
          const boxClass = lr === 'GREEN'
            ? 'border-green-500/20 bg-green-500/5'
            : 'border-line bg-surface-1/60'
          const circleClass = lr === 'GREEN'
            ? 'bg-green-500/20 text-green-400'
            : 'bg-orange-500/10 text-orange-400'
          return (
          <div key={i} className={`rounded-md border px-3 py-2 ${boxClass}`}>
            <div className="flex items-center gap-2">
              <span className={`w-5 h-5 flex items-center justify-center rounded-full ${circleClass} text-[10px] font-black shrink-0`}>
                {lr === 'GREEN' ? '✓' : i + 1}
              </span>
              <div className="flex items-center gap-1.5 flex-1 min-w-0">
                <TeamLogo id={leg.homeId} name={leg.home ?? ''} size={20} />
                <span className="text-xs text-ink-2 font-semibold truncate">{leg.home}</span>
                <span className="text-ink-4 text-[10px] shrink-0">vs</span>
                <span className="text-xs text-ink-2 font-semibold truncate">{leg.away}</span>
                <TeamLogo id={leg.awayId} name={leg.away ?? ''} size={20} />
              </div>
              <span className={`font-mono font-black text-sm shrink-0 ${lr === 'GREEN' ? 'text-green-400' : 'text-orange-300'}`}>
                {Number(leg.odd).toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-1.5 ml-7 text-xs mt-1">
              <span className="font-semibold text-ink-2">{translateMarket(leg.market)}</span>
              {leg.line && <><span className="text-ink-4">·</span><span className="text-ink-2">{translateLine(leg.line)}</span></>}
              {leg.house && <><span className="text-ink-4">·</span><span className="text-ink-3">{leg.house}</span></>}
              <InfoTip text={explainMarket(leg.market, leg.line)} />
            </div>
          </div>
          )
        })}
      </div>

      {/* A alavancagem nao tem coluna de probabilidade: o que existe e' a
          media das confiancas das pernas. Passa como `confidence` pra
          PickProbability marcar o numero como "estimada", igual ela ja faz
          nos picks VIP antigos sem probabilidade. */}
      <PickProbability confidence={pick.confidence_media} />

      <PickReasoning text={shortReasoning(pick.reasoning_1)} />

      {/* Footer */}
      {pick.reasoning_1 && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!pick.result ? (e => {
          e.stopPropagation()
          /*
           * A banca de alavancagem e SEPARADA da banca do site: ela vive em
           * user_banca.alav_bankroll_init e se configura no painel laranja no
           * topo desta aba, nao em /banca.
           *
           * Isto aqui era `onConfigureBanca?.() ?? navigate('/banca')`, e o ??
           * testa o RESULTADO da chamada, nao se a funcao existe. Como
           * onConfigureBanca devolve undefined, o lado direito rodava SEMPRE:
           * trocava a aba e logo em seguida jogava o usuario em /banca, que e
           * a banca errada.
           */
          if (userBankroll == null) {
            if (onConfigureBanca) onConfigureBanca()
            else navigate('/banca')
          }
          else handleFollow(e as any)
        }) : undefined}
        betState={following || buscandoBilhete ? 'loading' : followed ? 'done' : 'idle'}
        hasBanca={userBankroll != null}
        onShare={handleShare}
        shareState={sharing ? 'loading' : shared ? 'done' : 'idle'}
      />
    </motion.div>
    <AnimatePresence>
    {showAnalysis && (
      <AnalysisModal
        onClose={() => setShowAnalysis(false)}
        data={{
          market: 'Alavancagem',
          line: [pick.line_1, pick.line_2, pick.line_3].filter(Boolean).join(' + '),
          odd: Number(pick.odd_combined),
          confidence: pick.confidence_media ?? null,
          probability: null,
          ev: pick.ev_combined ?? null,
          // A série vem PERNA A PERNA · não existe uma que descreva o bilhete.
          pickId: pick.id,
          pickType: 'alavancagem',
          legs: [
            { market: pick.market_1, line: pick.line_1, odd: pick.odd_1 },
            { market: pick.market_2, line: pick.line_2, odd: pick.odd_2 },
            { market: pick.market_3, line: pick.line_3, odd: pick.odd_3 },
          ].filter(l => l.market),
          reasoning: [pick.reasoning_1, pick.reasoning_2, pick.reasoning_3].filter(Boolean).join('\n\n'),
        }}
      />
    )}
    </AnimatePresence>

    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={modalOdd ?? Number(pick.odd_combined)}
        originalOdd={Number(pick.odd_combined)}
        suggestedHouse={pick.bet_house_1}
        hideUnits
        onConfirm={handleConfirm}
        onCancel={() => setShowModal(false)}
        loading={following}
        error={apiError}
      />
    )}
    </AnimatePresence>
    <AnimatePresence>
    {showSuccess && (
      <motion.div
        variants={toastUp} initial="hidden" animate="visible" exit="exit"
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-ink-1 text-sm font-semibold px-5 py-3 rounded-md shadow-lg whitespace-nowrap"
      >
        Pick registrado com sucesso!
      </motion.div>
    )}
    </AnimatePresence>
  </>
  )
}

// Seção header
// ─── Mercados com modelo proprio: faltas e defesas de goleiro ───────────────
// Os dois ficam numa aba so' em vez de duas: a barra ja tem 6 abas e rola
// horizontalmente no celular -- somar duas empurraria as ultimas pra fora da
// primeira tela em qualquer aparelho.
interface MercadoPick {
  id: number
  fixture_id?: number
  match_date: string
  match_datetime?: string
  home_team: string; away_team: string
  home_team_id?: number; away_team_id?: number
  league_id?: number; league_name?: string
  player_name?: string; team_name?: string
  market: string; market_type?: string; line: string
  odd: number; bet_house?: string
  prob_real?: number; edge?: number
  reasoning?: string
  stake_units?: number
  result?: string | null
  is_followed?: boolean
  user_stake_units?: number | null
  user_actual_odd?: number | null
  user_bet_house?: string | null
}

/*
 * Picks de mercado próprio renderizam pelo MESMO componente do VIP
 * (SuggestionCard), não por um card paralelo.
 *
 * Antes existia um MercadoCard só pra faltas/goleiros. Ele nasceu com a mesma
 * anatomia e foi divergindo: ficou sem stake sugerida em unidades e reais, sem
 * lucro potencial, sem o estado "Apostado Xu" de quem já registrou, sem a odd
 * real do usuário, sem o "Registrando…/Registrado" no botão, sem buscar odd ao
 * vivo antes de abrir o modal e sem o aviso de sucesso. Duplicar a anatomia do
 * card é justamente o que produz esse tipo de deriva, então o que sobra aqui é
 * só a tradução do formato do pipeline pro formato que o SuggestionCard já
 * consome.
 *
 * `ev` vai como FRAÇÃO porque é assim que o endpoint de lista entrega pros
 * outros tipos (picks_vip.ev = 0.3203 para 32%) · manter a mesma escala é o
 * que garante que os dois cards mostrem o mesmo número.
 */
function mercadoParaSuggestion(p: MercadoPick, tipo: 'faltas' | 'goleiros') {
  return {
    id: p.id,
    fixture_id: p.fixture_id,
    home_team_name: p.home_team,
    away_team_name: p.away_team,
    home_team_id: p.home_team_id,
    away_team_id: p.away_team_id,
    league_id: p.league_id,
    league_name: p.league_name,
    market: p.market,
    line: p.line,
    odd: Number(p.odd),
    bet_house: p.bet_house ?? '',
    /* prob_real É a probabilidade destes dois mercados: a tabela empírica
       (faltas) e a Binomial Negativa (goleiros) já devolvem probabilidade, não
       existe score composto separado pra virar "confiança". */
    confidence: p.prob_real != null ? Number(p.prob_real) : 0,
    probability: p.prob_real != null ? Number(p.prob_real) : null,
    market_type: p.market_type ?? tipo,
    ev: p.edge != null ? Number(p.edge) : undefined,
    /* Os dois vão separados de propósito: `match_date` é a DATA (coluna DATE)
       e `match_datetime` é o horário do jogo. Enquanto o card lia a hora de
       `match_date`, isto aqui era `p.match_datetime ?? p.match_date` -- e
       quando o fixture não estava mais na tabela `fixtures` caía na data pura
       e o card imprimia 21:00. */
    match_date: p.match_date,
    match_datetime: p.match_datetime ?? null,
    reasoning: p.reasoning,
    result: p.result ?? undefined,
    pick_type: tipo,
    is_followed: p.is_followed,
    user_stake_units: p.user_stake_units,
    user_actual_odd: p.user_actual_odd,
    user_bet_house: p.user_bet_house,
    /* stake_units do pipeline é a sugestão do próprio motor (calculate_stake),
       mesmo papel de suggested_stake_units nos outros tipos. */
    suggested_stake_units: p.stake_units,
  }
}

function MercadoSecao({ tipo, titulo, cor, explicacao, picks, carregando, banca }: {
  tipo: 'faltas' | 'goleiros'
  titulo: string; cor: string; explicacao: string
  picks: MercadoPick[] | null; carregando: boolean
  banca?: { bankroll_current: number; unit_value: number } | null
}) {
  // `mercadoParaSuggestion` monta um objeto novo a cada chamada. Chamando-a
  // direto no JSX, a prop `s` mudava de identidade em todo render e o memo do
  // SuggestionCard nunca acertava · o card era remontado por inteiro sempre que
  // qualquer estado da tela de Picks mudasse.
  const cards = useMemo(
    () => (picks ?? []).map(p => ({ id: p.id, s: mercadoParaSuggestion(p, tipo) })),
    [picks, tipo],
  )

  const vazio = !carregando && (!picks || picks.length === 0)

  return (
    <div>
      <SectionHeader color={cor} label={titulo} badge="VIP" />
      {/* Explicacao so' quando ha o que explicar. Secao vazia nao precisa de
          paragrafo sobre um mercado que nao esta ali. */}
      {!vazio && <p className="text-xs text-ink-3 leading-relaxed mb-4">{explicacao}</p>}
      {carregando ? (
        <PickLoading />
      ) : vazio ? (
        /* Uma linha, nao uma caixa. Defesas aparece em menos de 1% dos jogos,
           entao o estado vazio dele e' o que se ve praticamente TODO dia -- e
           uma caixa tracejada de 150px de altura anunciando "nao tem nada"
           ocupava mais tela que a secao que tem pick. Dia sem pick aqui e' o
           normal, e o normal nao merece destaque. */
        <p className="text-xs text-ink-4 leading-relaxed mb-2">
          Sem pick de {titulo.toLowerCase()} hoje.{' '}
          {tipo === 'goleiros'
            ? 'É um mercado raro, aparece em menos de 1% dos jogos.'
            : 'Aparece quando algum jogo do dia tiver margem suficiente no modelo.'}
        </p>
      ) : (
        <div className="lista-longa grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {cards.map(c => (
            <SuggestionCard key={c.id} s={c.s} banca={banca} />
          ))}
        </div>
      )}
    </div>
  )
}

function SectionHeader({ color, label, badge, action }: {
  color: string; label: string; badge?: string
  /** Ação opcional alinhada à direita. */
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className={`w-0.5 h-5 ${color} rounded-full block`} />
      <h2 className="text-sm font-bold text-ink-2">{label}</h2>
      {badge && <span className="badge-vip">{badge}</span>}
      {action && <div className="ml-auto shrink-0">{action}</div>}
    </div>
  )
}

/* Carregamento de bloco desta tela.
 *
 * Era um spinner centralizado numa caixa `p-16`. O problema não era o spinner
 * em si, era o salto: aquela caixa tem altura arbitrária e, quando o dado
 * chegava, virava uma grade de cards de outra altura, empurrando tudo abaixo.
 * O esqueleto já nasce com a forma da lista, então o conteúdo preenche o
 * espaço que já estava reservado em vez de reorganizar a tela. */
function PickLoading({ cards = 2 }: { cards?: number }) {
  return <SkeletonPickGrid cards={cards} />
}


interface PipelineStep { key: string; label: string; status: 'pending' | 'running' | 'done' | 'error' }

// Mostra o progresso da geração dos picks (quando o pipeline está rodando),
// com fallback para o card de "ainda não saíram" enquanto ele não começou.
function PipelineStatusCard() {
  const [status, setStatus] = useState<{ running: boolean; finished: boolean; steps: PipelineStep[] } | null>(null)

  /*
   * Ritmo depende de estar rodando ou não, e a aba escondida não pesquisa.
   *
   * Antes era um intervalo fixo de 6s que subia junto com o card e não parava
   * nunca. Quem abrisse a aba num dia sem picks e deixasse aberta ficava
   * pedindo o status dez vezes por minuto, para sempre, mesmo com o navegador
   * em segundo plano · e cada pedido passa pela checagem de sessão, que é uma
   * ida ao banco.
   *
   * O intervalo parado continua existindo de propósito: o pipeline roda na mão,
   * então ele pode começar com o usuário já na tela, e sem pesquisa nenhuma ele
   * só descobriria recarregando. 60s parado é o suficiente para isso; 10s
   * rodando é o suficiente para a barra de etapas andar sem parecer travada.
   */
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | null = null

    const agendar = (rodando: boolean) => {
      if (!active) return
      timer = setTimeout(poll, rodando ? 10_000 : 60_000)
    }

    const poll = () => {
      if (!active) return
      // Aba em segundo plano não gasta requisição: volta a pesquisar no
      // visibilitychange abaixo.
      if (document.hidden) { agendar(false); return }
      api.get('/admin/pipeline-status-public')
        .then(r => {
          if (!active) return
          setStatus(r.data)
          agendar(!!r.data?.running)
        })
        .catch(() => agendar(false))
    }

    const aoVoltar = () => {
      if (!document.hidden && active) {
        if (timer) clearTimeout(timer)
        poll()
      }
    }

    poll()
    document.addEventListener('visibilitychange', aoVoltar)
    return () => {
      active = false
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', aoVoltar)
    }
  }, [])

  if (!status?.running) {
    return <PicksPendingCard />
  }

  return (
    <div className="card p-8 border-line">
      <div className="flex flex-col items-center mb-6">
        <div className="relative mb-4">
          <span className="absolute inset-0 rounded-full bg-green-500/20 animate-ping" />
          <span className="relative flex items-center justify-center w-14 h-14 rounded-full bg-green-500/10 border border-green-500/30">
            <BrainCircuit className="w-7 h-7 text-green-400" />
          </span>
        </div>
        <p className="text-ink-1 font-bold text-base text-center">A IA está montando os picks de hoje</p>
        <p className="text-ink-3 text-sm mt-1 text-center">Analisando estatísticas, odds e forma recente dos times</p>
      </div>
      <div className="space-y-3 max-w-xs mx-auto">
        {status.steps.map(s => (
          <div key={s.key} className="flex items-center gap-3">
            <span className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 text-[11px] font-black ${
              s.status === 'done'    ? 'bg-green-500/15 text-green-400' :
              s.status === 'running' ? 'bg-yellow-500/15 text-yellow-400' :
              s.status === 'error'   ? 'bg-surface-3 text-ink-3' :
                                        'bg-surface-2 text-ink-4'
            }`}>
              {s.status === 'done' ? '✓' : s.status === 'running' ? (
                <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
              ) : '·'}
            </span>
            <span className={`text-sm ${
              s.status === 'done'    ? 'text-ink-2' :
              s.status === 'running' ? 'text-ink-1 font-semibold' :
                                        'text-ink-4'
            }`}>
              {s.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}


// VIP Lock Overlay
function VipLockOverlay({ color = 'yellow' }: { color?: 'yellow' | 'blue' | 'orange' | 'purple' }) {
  const cls = color === 'blue'
    ? { icon: 'text-blue-400',   ring: 'bg-blue-400/10 border-blue-400/20',     btn: 'bg-blue-500 hover:bg-blue-400 text-ink-1'    }
    : color === 'orange'
    ? { icon: 'text-orange-400', ring: 'bg-orange-400/10 border-orange-400/20', btn: 'bg-orange-500 hover:bg-orange-400 text-ink-1' }
    : color === 'purple'
    ? { icon: 'text-purple-400', ring: 'bg-purple-400/10 border-purple-400/20', btn: 'bg-purple-500 hover:bg-purple-400 text-ink-1' }
    : { icon: 'text-yellow-400', ring: 'bg-yellow-400/10 border-yellow-400/20', btn: 'bg-yellow-400 hover:bg-yellow-300 text-black' }
  return (
    <div className="relative rounded-lg overflow-hidden">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 select-none pointer-events-none" style={{ filter: 'blur(5px)', opacity: 0.35 }}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="card p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div className="h-3 bg-surface-3 rounded w-24" />
              <div className="h-5 bg-surface-3 rounded w-16" />
            </div>
            <div className="h-4 bg-surface-3 rounded w-3/4" />
            <div className="grid grid-cols-3 gap-2">
              <div className="h-10 bg-surface-2 rounded-lg" />
              <div className="h-10 bg-surface-2 rounded-lg" />
              <div className="h-10 bg-surface-2 rounded-lg" />
            </div>
            <div className="h-2 bg-surface-2 rounded-full" />
          </div>
        ))}
      </div>
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 backdrop-blur-sm rounded-lg">
        <div className="text-center px-6">
          <div className={`w-12 h-12 border rounded-full flex items-center justify-center mx-auto mb-3 ${cls.ring}`}>
            <svg className={`w-6 h-6 ${cls.icon}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <p className="font-display text-ink-1 font-bold text-base mb-1">Exclusivo para assinantes VIP</p>
          <p className="text-ink-2 text-xs mb-4 max-w-xs">10 a 20 picks por dia com análise completa da IA e resultados em tempo real.</p>
          <Link to="/checkout" className={`inline-block font-black px-6 py-2.5 rounded-md transition-colors text-sm ${cls.btn}`}>
            Assinar VIP
          </Link>
        </div>
      </div>
    </div>
  )
}



/*
 * Cards memoizados.
 *
 * Esta tela guarda todo o estado num componente só · `today`, `quickStats`,
 * `liveFixtures`, `recentResults`, `bancaSummary`, `userAlavSerie`, a aba, os
 * filtros e os modais. Cada resposta que chega repintava TODOS os cards, e no
 * iPhone isso aparece como travada no scroll enquanto a tela carrega.
 *
 * Os três recebem props estáveis: o objeto do pick vem direto de `today`, o
 * `banca` é o mesmo `bancaSummary`, `isLive` é booleano e `onConfigureBanca` já
 * era um useCallback. Então a comparação rasa do memo resolve · não precisa de
 * comparador próprio, e colocar um aqui só criaria uma segunda fonte de verdade
 * sobre quais props importam.
 */
const PickSeguroCard  = memo(PickSeguroCardBase)
const MultiplaCard    = memo(MultiplaCardBase)
const AlavancagemCard = memo(AlavancagemCardBase)

// Dashboard
export default function Picks() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, isVip, isAdmin, daysUntilExpiry } = useAuth()
  const canSeeVip = isVip || isAdmin
  const { hasNew, markSeen, liveCount, hasLive, clearLive } = useNotifications()

  const [tab, setTab]               = useState<Tab>('hoje')

  // Trava de "já visitou": uma vez aberta, a aba pesada continua montada (com
  // `hidden`) para não perder polling nem estado. Antes de visitar, ela nem
  // existe · é isso que mantém o chunk dela fora do carregamento da página.
  const jaAbriuMinhasApostas = useRef(false)
  const jaAbriuAoVivo        = useRef(false)
  if (tab === 'minhas_apostas') jaAbriuMinhasApostas.current = true
  if (tab === 'ao_vivo')        jaAbriuAoVivo.current = true

  // Estar nesta pagina ja significa ter visto os picks novos, entao o aviso
  // saiu do corpo da pagina e o assunto vive so' no sino. Marcar aqui (e nao
  // apenas no clique do link da Navbar, que era o unico outro gatilho) cobre
  // quem chega por URL direta, atalho do PWA ou toque numa notificacao push.
  // Depende de hasNew e nao do mount porque markSeen so' tem o id certo
  // depois que as notificacoes carregam.
  useEffect(() => {
    if (hasNew) markSeen()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasNew])

  useEffect(() => {
    const bruto = location.hash.replace('#', '')
    const hash = (ALIAS_ABA[bruto] ?? bruto) as Tab
    // 'ao_vivo' só é destino válido quando a aba existe · sem isso um link
    // antigo com #ao_vivo (ou o hash guardado no histórico do navegador)
    // abriria numa aba que não está na barra, e o usuário ficaria numa tela
    // sem como voltar clicando.
    const valid: Tab[] = ['hoje','pick_seguro','vip','multiplas','alavancagem','mercados','minhas_apostas','chat',
                          ...(LIVE_PICKS_ENABLED ? ['ao_vivo' as Tab] : [])]
    setTab(valid.includes(hash) ? hash : 'hoje')
  }, [location.hash])

  /*
   * O painel lateral de detalhe saiu daqui em 2026-08-14, a pedido do usuário.
   *
   * O card inteiro era um botão que o abria, e só o VIP e os mercados tinham
   * esse comportamento -- free, múltipla e alavancagem nunca abriram nada. Ou
   * seja: além de disparar sem querer (dentro do card já moram "Apostar",
   * "Compartilhar", "Entenda esta análise" e o ícone de informação), a mesma
   * batida de dedo fazia coisas diferentes dependendo do tipo do pick.
   *
   * A leitura aprofundada continua existindo em "Entenda esta análise", que é
   * um botão explícito e igual nos cinco cards. SuggestionDetail segue vivo
   * para Banca, Meus Picks e Resultados, onde é aberto a partir de uma LINHA
   * de lista -- ali o clique no item é a única ação possível, então não há
   * ambiguidade.
   */

  // Dados de hoje (free + VIP rápido)
  const [today, setToday]         = useState<any>(null)
  const [todayLoading, setTodayLoading] = useState(true)
  const [todayError, setTodayError]     = useState(false)
  const [liveFixtures, setLiveFixtures] = useState<Set<number>>(new Set())

  // Alavancagem
  const [alavFilters,  setAlavFilters]  = useState<AlavFilters>(defaultAlavFilters)
  const [alavancagem,  setAlavancagem]  = useState<any[]>([])
  // null = ainda nao buscou (a aba carrega sob demanda, ver o efeito por aba)
  // Busca, categoria, ordem e estado da aba Mercados. Filtragem é local: a aba
  // já baixa os dois conjuntos inteiros, são poucas dezenas de picks por dia.
  const [mercadoFiltro, setMercadoFiltro] = useState<MercadoFiltro>(FILTRO_INICIAL)
  /*
   * A aba Mercados é a aba do DIA, igual à de picks VIP.
   *
   * Lia /suggestions/faltas e /suggestions/goleiros com limit=50 e sem filtro
   * de data · ou seja, histórico: a aba do dia mostrava pick de semanas atrás
   * misturado com o de hoje, e a navegação por data no topo não mexia nela.
   * Agora sai de /suggestions/today, a mesma resposta que alimenta VIP,
   * múltipla e alavancagem, então os cinco tipos falam sempre do mesmo dia.
   */
  const faltas   = (today?.faltas   ?? null) as MercadoPick[] | null
  const goleiros = (today?.goleiros ?? null) as MercadoPick[] | null
  const faltasFiltradas   = useMemo(() => aplicarFiltro(faltas ?? [], mercadoFiltro), [faltas, mercadoFiltro])
  const goleirosFiltrados = useMemo(() => aplicarFiltro(goleiros ?? [], mercadoFiltro), [goleiros, mercadoFiltro])
  const [alavLoading,  setAlavLoading]  = useState(false)
  const [alavLoaded,   setAlavLoaded]   = useState(false)
  const [alavError,    setAlavError]    = useState(false)
  const [alavHasMore,    setAlavHasMore]    = useState(false)
  const [alavLoadingMore, setAlavLoadingMore] = useState(false)
  const [userAlavSerie, setUserAlavSerie] = useState<AlavSerie | null>(null)
  const [alavInitInput, setAlavInitInput] = useState('')
  const [alavInitSaving, setAlavInitSaving] = useState(false)
  const [alavInitError, setAlavInitError] = useState('')
  const [alavEncerrando, setAlavEncerrando] = useState(false)
  const [alavConfirmClose, setAlavConfirmClose] = useState(false)
  const [alavCloseMsg, setAlavCloseMsg] = useState('')
  const [bancaSummary, setBancaSummary] = useState<{ has_banca: boolean; bankroll_current: number; unit_value: number } | null>(null)
  const [showBancaModal, setShowBancaModal] = useState(false)

  const [quickStats, setQuickStats] = useState<any>(null)
  const [quickStatsPronto, setQuickStatsPronto] = useState(false)
  const [recentResults, setRecentResults] = useState<any[]>([])
  const [selectedOffset, setSelectedOffset] = useState(0)
  const [leagueFilter, setLeagueFilter] = useState<string>('')
  const [vipResultFilter, setVipResultFilter] = useState<string>('')

  function getBrasiliaDate(offset: number): Date {
    const d = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }))
    d.setDate(d.getDate() + offset)
    return d
  }

  function getBrasiliaDateIso(offset: number): string {
    const d = getBrasiliaDate(offset)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }

  const todayLabel   = getBrasiliaDate(selectedOffset).toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })
  const todayDateStr = getBrasiliaDate(selectedOffset).toLocaleDateString('pt-BR', { day: 'numeric', month: 'long', year: 'numeric' })

  useEffect(() => {
    setTodayLoading(true)
    setTodayError(false)
    const params = selectedOffset < 0 ? { date: getBrasiliaDateIso(selectedOffset) } : {}
    api.get('/suggestions/today', { params })
      .then(r => setToday(r.data))
      .catch(() => setTodayError(true))
      .finally(() => setTodayLoading(false))
  }, [selectedOffset])

  useEffect(() => {
    api.get('/suggestions/stats/quick')
      .then(r => setQuickStats(r.data))
      .catch(() => {})
      .finally(() => setQuickStatsPronto(true))
  }, [])

  /*
   * REVELAÇÃO COLETIVA DO TOPO · mesmo motivo da Home.
   *
   * A faixa "Performance da IA" fica ACIMA de todos os cards e só renderizava
   * quando `/suggestions/stats/quick` respondia. Como os picks vêm de outra
   * chamada, ela entrava depois e empurrava a tela inteira de picks para baixo,
   * às vezes com o usuário já lendo o primeiro card.
   *
   * Os dois pedidos continuam saindo juntos; o que espera é só a troca do
   * esqueleto pelo conteúdo. O erro conta como pronto (o `.finally` acima):
   * chamada que falhou não pode segurar a tela para sempre.
   */
  const topoPronto = !todayLoading && quickStatsPronto

  // Lucro acumulado em unidades. `profit` já vem somado dos seis pipelines em
  // /suggestions/stats/quick e já está em unidades (stake fixa de 1u por pick),
  // então aqui é só ler: nada de recalcular odd por odd no cliente.
  const lucroUnidades = Number(quickStats?.profit ?? 0)

  // Marca picks pendentes como "Ao Vivo" quando o jogo já começou (status real
  // da API-Football via /live/is-live), em vez de continuar mostrando
  // "Pendente" como se o jogo nem tivesse começado.
  useEffect(() => {
    if (!today) return
    const ids = new Set<number>()
    if (today.dica_do_dia && !today.dica_do_dia.result && today.dica_do_dia.fixture_id) {
      ids.add(today.dica_do_dia.fixture_id)
    }
    for (const s of today.vip ?? []) {
      if (!s.result && s.fixture_id) ids.add(s.fixture_id)
    }
    for (const m of today.multiplas ?? []) {
      if (m.result) continue
      for (const leg of m.legs ?? []) {
        if (leg.fixture_id) ids.add(leg.fixture_id)
      }
    }
    if (today.alavancagem && !today.alavancagem.result) {
      if (today.alavancagem.fixture_id_1) ids.add(today.alavancagem.fixture_id_1)
      if (today.alavancagem.fixture_id_2) ids.add(today.alavancagem.fixture_id_2)
    }
    if (ids.size === 0) { setLiveFixtures(new Set()); return }
    api.get('/live/is-live', { params: { fixture_ids: Array.from(ids).join(',') } })
      .then(r => setLiveFixtures(new Set(Object.entries(r.data).filter(([, v]) => v).map(([k]) => Number(k)))))
      .catch(() => {})
  }, [today])

  const isFixtureLive  = (fixtureId?: number) => !!fixtureId && liveFixtures.has(fixtureId)
  const isMultiplaLive = (m: any) => (m.legs ?? []).some((leg: any) => isFixtureLive(leg.fixture_id))
  const isAlavLive     = (pick: any) => isFixtureLive(pick.fixture_id_1) || isFixtureLive(pick.fixture_id_2)

  // Mesma razão do useMemo em MercadoSecao: `mercadoParaSuggestion` devolve um
  // objeto novo toda vez, e sem prender a identidade aqui o memo do
  // SuggestionCard não pega nada nesta aba.
  const faltasCards = useMemo<Array<{ id: number; s: any }>>(
    () => (today?.faltas ?? []).map((p: MercadoPick) => ({ id: p.id, s: mercadoParaSuggestion(p, 'faltas') })),
    [today?.faltas],
  )
  const goleirosCards = useMemo<Array<{ id: number; s: any }>>(
    () => (today?.goleiros ?? []).map((p: MercadoPick) => ({ id: p.id, s: mercadoParaSuggestion(p, 'goleiros') })),
    [today?.goleiros],
  )

  useEffect(() => {
    api.get('/suggestions/recent-results', { params: { limit: 40 } })
      .then(r => setRecentResults(r.data as any[]))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!canSeeVip) return
    api.get('/banca/alavancagem-serie').then(r => setUserAlavSerie(r.data)).catch(() => {})
  }, [canSeeVip])

  useEffect(() => {
    api.get('/banca/summary').then(r => {
      setBancaSummary(r.data)
      if (!r.data.has_banca && canSeeVip && !sessionStorage.getItem('pickia_banca_modal_shown')) {
        setShowBancaModal(true)
      }
    }).catch(() => {})
  }, [])


  const prefetchAba = useCallback((t: Tab) => {
    if (t === 'alavancagem' && canSeeVip && !alavLoaded) doFetchAlavancagem(defaultAlavFilters)
  }, [canSeeVip, alavLoaded])

  /* A aba pode ser aberta sem passar pelo prefetch: deep link com hash
     (#mercados) ou botão de outra parte da tela. */
  useEffect(() => {
    if (tab === 'alavancagem' && canSeeVip && !alavLoaded) doFetchAlavancagem(defaultAlavFilters)
  }, [tab, canSeeVip])


  /*
   * Leva o usuario ate o painel de banca da alavancagem.
   *
   * Trocar de aba sozinho nao resolvia: quem clica em "Configurar banca" num
   * card de alavancagem JA esta na aba de alavancagem, entao setTab nao movia
   * nada e a tela parecia nao responder.
   */
  const alavConfigRef = useRef<HTMLDivElement>(null)
  const irParaConfigAlavancagem = useCallback(() => {
    setTab('alavancagem')
    // espera a aba pintar antes de rolar
    setTimeout(() => {
      alavConfigRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      alavConfigRef.current?.querySelector('input')?.focus({ preventScroll: true })
    }, 120)
  }, [])

  const saveAlavInit = async () => {
    const val = parseFloat(alavInitInput)
    if (!val || val <= 0) return
    setAlavInitSaving(true)
    setAlavInitError('')
    try {
      await api.put('/banca/alavancagem-init', { bankroll_init: val })
      const r = await api.get('/banca/alavancagem-serie')
      setUserAlavSerie(r.data)
      setAlavInitInput('')
    } catch (e: any) {
      setAlavInitError(e.response?.data?.detail || 'Erro ao salvar. Tente novamente.')
    } finally {
      setAlavInitSaving(false)
    }
  }

  const encerrarCaminho = async () => {
    setAlavEncerrando(true)
    setAlavInitError('')
    try {
      const r = await api.post('/banca/alavancagem-encerrar')
      const s = await api.get('/banca/alavancagem-serie')
      setUserAlavSerie(s.data)
      setAlavConfirmClose(false)
      setAlavCloseMsg(
        `Caminho encerrado. R$${Number(r.data.realized_pnl).toFixed(2)} foram pra sua banca. ` +
        `O próximo começa em R$${Number(r.data.next_initial).toFixed(2)}.`,
      )
      // A banca principal mudou · o resumo em cache mostraria o valor velho.
      api.get('/banca/summary').then(b => setBancaSummary(b.data)).catch(() => {})
    } catch (e: any) {
      setAlavInitError(e.response?.data?.detail || 'Erro ao encerrar. Tente novamente.')
    } finally {
      setAlavEncerrando(false)
    }
  }

  const ALAV_PAGE_SIZE = 50

  function doFetchAlavancagem(f: AlavFilters) {
    setAlavLoading(true)
    setAlavError(false)
    const p: Record<string, string> = { limit: String(ALAV_PAGE_SIZE) }
    if (f.date_from) p.date_from = f.date_from
    if (f.date_to)   p.date_to   = f.date_to
    if (f.resultado !== 'all') p.resultado = f.resultado
    api.get('/suggestions/alavancagem', { params: p })
      .then(r => { setAlavancagem(r.data.items); setAlavHasMore(r.data.has_more); setAlavLoaded(true) })
      .catch(() => setAlavError(true))
      .finally(() => setAlavLoading(false))
  }

  function loadMoreAlavancagem() {
    if (alavLoadingMore || !alavHasMore) return
    setAlavLoadingMore(true)
    const p: Record<string, string> = { limit: String(ALAV_PAGE_SIZE), offset: String(alavancagem.length) }
    if (alavFilters.date_from) p.date_from = alavFilters.date_from
    if (alavFilters.date_to)   p.date_to   = alavFilters.date_to
    if (alavFilters.resultado !== 'all') p.resultado = alavFilters.resultado
    api.get('/suggestions/alavancagem', { params: p })
      .then(r => { setAlavancagem(prev => [...prev, ...r.data.items]); setAlavHasMore(r.data.has_more) })
      .catch(() => {})
      .finally(() => setAlavLoadingMore(false))
  }

  return (
    <PageShell
      title="Picks"
      description="Os picks da IA de hoje: VIP, free, múltiplas, alavancagem e mercados de faltas e defesas."
      noindex
      width="full"
      bar={{
        title: 'Picks',
        // O navegador de dia é controle, não legenda: sem isto ele ficava
        // escondido abaixo de sm, que é onde está a maioria dos usuários.
        subMobile: true,
        sub: tab === 'hoje' ? (
          /* Alvo de toque de verdade no celular. As setas tinham 14px com
             padding de 2px · abaixo de qualquer minimo de acessibilidade, e
             este e o controle mais usado da tela num site que vive no celular.
             No desktop o mouse nao precisa disso, entao o tamanho encolhe. */
          <span className="flex items-center gap-1 sm:gap-0.5 -my-1 sm:my-0">
            <button
              onClick={() => setSelectedOffset(o => o - 1)}
              aria-label="Dia anterior"
              className="text-ink-2 hover:text-ink-1 transition-colors p-2 sm:p-0.5 sm:-ml-0.5 rounded-md active:bg-surface-2"
            >
              <ChevronLeft className="w-5 h-5 sm:w-3.5 sm:h-3.5" />
            </button>
            <span className="text-ink-1 sm:text-ink-2 capitalize font-bold sm:font-medium text-sm sm:text-[11px]">
              {selectedOffset === 0 ? 'Hoje' : todayLabel}
            </span>
            <button
              onClick={() => setSelectedOffset(o => Math.min(0, o + 1))}
              disabled={selectedOffset >= 0}
              aria-label="Próximo dia"
              className="text-ink-2 hover:text-ink-1 disabled:opacity-20 transition-colors p-2 sm:p-0.5 rounded-md active:bg-surface-2"
            >
              <ChevronRight className="w-5 h-5 sm:w-3.5 sm:h-3.5" />
            </button>
            {selectedOffset < 0 && (
              <button
                onClick={() => setSelectedOffset(0)}
                className="ml-1 text-[10px] text-accent hover:text-accent-hover font-bold transition-colors"
              >
                · Hoje
              </button>
            )}
          </span>
        ) : (
          <span className="capitalize">{todayLabel}</span>
        ),
        actions: (
          <>
            {topoPronto && quickStats && (
              <span className="hidden sm:flex items-center gap-2 text-xs">
                <span className="text-ink-4">Lucro geral</span>
                <span className={`font-mono font-bold text-sm tabular-nums ${lucroUnidades >= 0 ? 'text-accent' : 'text-red-400'}`}>
                  {fmtUnits(lucroUnidades, 1)}
                </span>
                <span className="text-ink-4">· Win rate</span>
                <span className={`font-mono font-bold text-sm ${(quickStats.win_rate ?? 0) >= 55 ? 'text-accent' : 'text-ink-2'}`}>
                  {quickStats.win_rate ?? 0}%
                </span>
              </span>
            )}
            {/* O selo "AO VIVO" da barra saiu. Ele piscava permanentemente,
                sem depender de existir jogo rolando, entao nao informava nada
                e ainda competia com o badge AO VIVO de verdade, que fica no
                card do pick cujo jogo comecou. Dois vermelhos piscando com
                significados diferentes na mesma tela e' pior que nenhum. */}
          </>
        ),
      }}
    >
      <AnimatePresence>
      </AnimatePresence>

      {/* Modal de boas-vindas · configura banca */}
      {showBancaModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm px-4">
          <div className="bg-surface-1 border border-line rounded-lg max-w-md w-full p-6 shadow-2xl overflow-y-auto max-h-[92dvh]">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-md bg-yellow-400/10 border border-yellow-400/20 flex items-center justify-center shrink-0">
                <Wallet className="w-5 h-5 text-yellow-400" />
              </div>
              <div>
                <h2 className="text-ink-1 font-bold text-base">Configure sua banca</h2>
                <p className="text-ink-3 text-xs">Último passo para começar a usar</p>
              </div>
            </div>
            <p className="text-ink-2 text-sm leading-relaxed mb-5">
              Com a banca configurada você consegue <span className="text-ink-1 font-semibold">acompanhar seus picks</span>,
              ver seu <span className="text-green-400 font-semibold">lucro acumulado</span>,
              e receber <span className="text-yellow-400 font-semibold">sugestão de stake</span> em cada aposta.
              Leva menos de 30 segundos!
            </p>
            <div className="flex flex-col gap-2">
              <button
                onClick={() => {
                  sessionStorage.setItem('pickia_banca_modal_shown', '1')
                  setShowBancaModal(false)
                  navigate('/banca')
                }}
                className="w-full bg-yellow-400 hover:bg-yellow-300 text-black font-black text-sm py-3 rounded-md transition-colors"
              >
                Configurar banca agora
              </button>
              <button
                onClick={() => {
                  sessionStorage.setItem('pickia_banca_modal_shown', '1')
                  setShowBancaModal(false)
                }}
                className="w-full text-ink-3 hover:text-ink-2 text-xs py-2 transition-colors"
              >
                Fazer depois
              </button>
            </div>
          </div>
        </div>
      )}

        {/* Aparece só enquanto a análise do dia está rodando. */}
        <EngineStatus />

        {hasLive && tab !== 'minhas_apostas' && (
          <div className="mb-4 flex items-center justify-between bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse shrink-0" />
              <span className="text-red-300 text-sm font-semibold">
                {liveCount > 1 ? `${liveCount} jogos que você apostou estão ao vivo!` : 'Um jogo que você apostou está ao vivo!'}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => { clearLive(); setTab('minhas_apostas') }}
                className="text-xs font-bold text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-400/50 px-2.5 py-1 rounded-lg transition-colors"
              >
                Acompanhar
              </button>
              <button onClick={clearLive} className="text-ink-4 hover:text-ink-2 text-xs transition-colors">✕</button>
            </div>
          </div>
        )}

        {/* Greeting do usuário */}
        <UserGreeting user={user} isVip={isVip} isAdmin={isAdmin} daysUntilExpiry={daysUntilExpiry} />

        <TabBar
          tab={tab}
          setTab={(t) => {
            if (t === 'minhas_apostas') clearLive()
            /* Trocar de aba é uma espera igual à de trocar de página pra quem
               está usando, mas aqui não há mudança de rota pra barra do topo
               perceber sozinha (as abas são estado, o hash só entra no deep
               link) · por isso o aviso explícito. */
            if (t !== tab) sinalizarNavegacao()
            setTab(t)
          }}
          onPrefetch={prefetchAba}
          canSeeVip={canSeeVip}
          liveCount={liveCount}
          counts={{
            pick_seguro: today?.dica_do_dia && !today.dica_do_dia.result ? 1 : undefined,
            vip:         (today?.vip ?? []).filter((s: any) => !s.result).length || undefined,
            multiplas:   (today?.multiplas ?? []).filter((m: any) => !m.result).length || undefined,
            alavancagem: today?.alavancagem && !today.alavancagem.result ? 1 : undefined,
            mercados:    ([...(today?.faltas ?? []), ...(today?.goleiros ?? [])]
                            .filter((p: any) => !p.result).length) || undefined,
          }}
        />

        <AnimatePresence mode="wait">
        {tab === 'hoje' && (
          <motion.div key="hoje" variants={tabFade} initial="hidden" animate="visible" exit="exit">
            {!topoPronto ? <PickLoading /> : todayError ? (
            <div className="card p-10 text-center">
              <p className="text-ink-2 font-semibold mb-1">Erro ao carregar picks</p>
              <p className="text-ink-4 text-sm mb-4">Não foi possível conectar ao servidor. Verifique sua conexão.</p>
              <button
                onClick={() => { setTodayError(false); setTodayLoading(true); const p = selectedOffset < 0 ? { date: getBrasiliaDateIso(selectedOffset) } : {}; api.get('/suggestions/today', { params: p }).then(r => setToday(r.data)).catch(() => setTodayError(true)).finally(() => setTodayLoading(false)) }}
                className="text-sm text-green-400 hover:text-green-300 font-semibold transition-colors"
              >
                Tentar novamente
              </button>
            </div>
          ) : (
            <div className="space-y-8">

              {/* Stats da IA este mês.
                  O lucro em unidades fecha a fila, depois do Win %: a leitura
                  vai de volume (Picks, Green, Red) para taxa (Win %) e termina
                  no resultado. Ele já vinha em `/suggestions/stats/quick`
                  (campo `profit`) desde sempre; a tela só mostrava contagem e
                  porcentagem, escondendo justo o resultado. */}
              {quickStats && (
                <div>
                  <p className="text-[10px] text-ink-4 font-semibold mb-2">Performance da IA · Geral</p>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    {[
                      { label: 'Picks', value: String(quickStats.total ?? 0), color: 'text-ink-1' },
                      { label: 'Green',  value: String(quickStats.greens ?? 0), color: 'text-green-500' },
                      { label: 'Red',    value: String(quickStats.reds ?? 0),   color: 'text-red-400' },
                      { label: 'Win %',  value: `${quickStats.win_rate ?? 0}%`, color: (quickStats.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-ink-2' },
                      { label: 'Lucro',  value: fmtUnits(lucroUnidades, 1), color: lucroUnidades >= 0 ? 'text-green-500' : 'text-red-400' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="bg-surface-1 border border-line rounded-md p-3 text-center">
                        <div className={`font-mono text-xl font-black tabular-nums ${color}`}>{value}</div>
                        <div className="text-[10px] text-ink-3 mt-1">{label}</div>
                      </div>
                    ))}
                  </div>
                  {/* A legenda do plano de stake saiu daqui. Ela dizia "4u em
                      picks simples" logo acima de um card que manda apostar 5u,
                      porque os dois números falam de coisas diferentes: o plano
                      fixo mede o PLACAR da IA, o card sugere a stake pra banca
                      DAQUELE usuário. Explicar isso na tela custava mais texto
                      do que o número valia, e sem explicar virava contradição.
                      A premissa continua publicada nas telas de resultado, onde
                      não existe card de Kelly pra contradizer. */}
                </div>
              )}

              {/* Progresso da geração / countdown quando picks ainda não chegaram */}
              {selectedOffset === 0 && !today?.dica_do_dia && !(today?.vip?.length) && !(today?.multiplas?.length) && !today?.alavancagem && !(today?.faltas?.length) && !(today?.goleiros?.length) && (
                <PipelineStatusCard />
              )}

              {/* Horário de geração dos picks */}
              {(today?.vip?.[0]?.created_at || today?.dica_do_dia?.created_at) && (() => {
                const ts = today?.vip?.[0]?.created_at ?? today?.dica_do_dia?.created_at
                const hora = new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })
                return (
                  <p className="text-[11px] text-ink-4 text-right -mt-4 mb-2">
                    Picks gerados hoje às {hora}
                  </p>
                )
              })()}

              {/* Pick Seguro · visível para todos; some se não houver dica hoje */}
              {today?.dica_do_dia && (
                <section>
                  <SectionHeader color="bg-green-500" label="Pick do Dia · Free" />
                  <PickSeguroCard dica={today.dica_do_dia} compact banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(today.dica_do_dia.fixture_id)} />
                </section>
              )}

              {/* PICKS VIP DO DIA · free vê lock; some se vazio pra quem já tem acesso */}
              {(() => {
                const vips = today?.vip ?? []
                const pending = vips.filter((s: any) => !s.result)
                if (canSeeVip && vips.length === 0) return null
                return (
                  <section>
                    <SectionHeader
                      color="bg-yellow-400"
                      label="Picks VIP do Dia"
                      badge={canSeeVip && pending.length ? `${pending.length} pendente${pending.length > 1 ? 's' : ''}` : undefined}
                    />
                    {!canSeeVip ? <VipLockOverlay color="yellow" /> : (
                      <>
                        <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                          {vips.slice(0, 4).map((s: any) => (
                            <SuggestionCard key={s.id} s={s} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(s.fixture_id)} />
                          ))}
                        </motion.div>
                        {vips.length > 4 && (
                          <button
                            onClick={() => setTab('vip')}
                            className="mt-4 w-full text-center text-xs text-green-500 hover:text-green-400 transition-colors py-3 border border-line rounded-md hover:border-line-strong"
                          >
                            Ver todos os {vips.length} picks
                          </button>
                        )}
                      </>
                    )}
                  </section>
                )
              })()}

              {/* Múltipla do Dia · free vê lock; some se vazia pra quem já tem acesso */}
              {(() => {
                const multiplas = today?.multiplas ?? []
                if (canSeeVip && multiplas.length === 0) return null
                return (
                  <section>
                    <SectionHeader color="bg-blue-400" label="Múltipla do Dia" />
                    {!canSeeVip ? <VipLockOverlay color="blue" /> : (
                      /* Colunas seguem a quantidade real de múltiplas. O grid
                         fixo de 3-4 colunas foi feito pensando em vitrine cheia,
                         mas o dia normal tem UMA múltipla · ela caía em 1/3 da
                         tela e o card, que é o mais denso do site (duas pernas,
                         linha de stats, barra de probabilidade), truncava até o
                         nome dos times. Com uma só ela ganha largura de leitura;
                         o max-w impede que vire uma faixa gigante no ultrawide. */
                      <motion.div
                        variants={staggerContainer} initial="hidden" animate="visible"
                        className={`grid gap-4 ${
                          multiplas.length === 1 ? 'max-w-2xl'
                          : multiplas.length === 2 ? 'md:grid-cols-2'
                          : 'md:grid-cols-2 xl:grid-cols-3'
                        }`}
                      >
                        {multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isMultiplaLive(m)} />)}
                      </motion.div>
                    )}
                  </section>
                )
              })()}

              {/* Alavancagem · free vê lock; some se não houver pick pra quem já tem acesso */}
              {(canSeeVip ? !!today?.alavancagem : true) && (
                <section>
                  <SectionHeader color="bg-orange-400" label="Alavancagem" />
                  {!canSeeVip ? <VipLockOverlay color="orange" /> : (
                    <>
                      <div className="card p-4 border-orange-500/10 bg-orange-500/5 mb-3">
                        <p className="text-xs text-ink-2 leading-relaxed">
                          Banca composta: começa em{' '}
                          <span className="text-orange-400 font-bold">
                            {userAlavSerie?.configured ? `R$${userAlavSerie.initial_bankroll.toFixed(2)}` : 'sua banca cadastrada'}
                          </span>{' '}
                          e reinveste o lucro a cada GREEN. Reset automático no RED. Odds alvo 1.50.
                        </p>
                      </div>
                      <AlavancagemCard
                        pick={today.alavancagem}
                        userBankroll={userAlavSerie?.configured ? userAlavSerie.current_bankroll : undefined}
                        onConfigureBanca={irParaConfigAlavancagem}
                        isLive={isAlavLive(today.alavancagem)}
                      />
                      <button onClick={() => setTab('alavancagem')}
                        className="mt-3 w-full text-center text-xs text-orange-400 hover:text-orange-300 transition-colors py-3 border border-line rounded-md hover:border-line-strong">
                        Ver histórico da série
                      </button>
                    </>
                  )}
                </section>
              )}

              {/* Mercados do dia. So' renderiza quando ha' pick -- ao
                  contrario da aba Mercados, aqui um card de "nada hoje" por
                  mercado so' empurraria o conteudo util pra baixo. */}
              {canSeeVip && (today?.faltas?.length > 0 || today?.goleiros?.length > 0) && (
                <section>
                  <SectionHeader color="bg-purple-400" label="Mercados de hoje" badge="VIP" />
                  <div className="lista-longa grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                    {/* Era aqui que o card de mercado aparecia SEM ação nenhuma:
                        o MercadoCard antigo só mostrava o botão Apostar quando
                        recebia `onBet`, e nesta aba (a que o usuário abre
                        primeiro) ele era montado sem nenhuma prop além do pick.
                        Com SuggestionCard o card é o mesmo do VIP em qualquer
                        lugar que apareça. */}
                    {faltasCards.map(c => (
                      <SuggestionCard
                        key={`f-${c.id}`}
                        s={c.s}
                        banca={bancaSummary?.has_banca ? bancaSummary : null}
                      />
                    ))}
                    {goleirosCards.map(c => (
                      <SuggestionCard
                        key={`g-${c.id}`}
                        s={c.s}
                        banca={bancaSummary?.has_banca ? bancaSummary : null}
                      />
                    ))}
                  </div>
                  <button onClick={() => setTab('mercados')}
                    className="mt-3 w-full text-center text-xs text-purple-400 hover:text-purple-300 transition-colors py-3 border border-line rounded-md hover:border-line-strong">
                    Ver todos os mercados
                  </button>
                </section>
              )}

            </div>
          )
        }
          </motion.div>
        )}

        {tab === 'pick_seguro' && (
          <motion.div key="pick_seguro" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-green-500/20 bg-green-500/5">
              <p className="font-display text-sm font-bold text-green-400 mb-3">O que é o Pick do Dia Free?</p>
              <div className="space-y-2 text-sm text-ink-2 leading-relaxed">
                <p>
                  Um pick gratuito publicado diariamente pela <span className="text-ink-1 font-bold">IA</span>. Analisamos centenas de
                  jogos e selecionamos o <span className="text-green-400 font-bold">1 pick com maior confiança</span> para disponibilizar para todos os usuários.
                </p>
                <p>
                  Ideal para quem quer experimentar a qualidade das análises antes de assinar o VIP.
                  Inclui mercado, odd, casa de apostas e raciocínio da IA.
                </p>
                <div className="grid grid-cols-3 gap-3 mt-3">
                  {[
                    { label: 'Frequência',  value: 'Diário',  color: 'text-green-400' },
                    { label: 'Picks/dia',   value: '1',       color: 'text-ink-1'     },
                    { label: 'Custo',       value: 'Grátis',  color: 'text-green-400' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-surface-1 rounded-md p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-ink-4 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Pick de hoje */}
            {todayLoading ? <PickLoading /> : (
              <div>
                <SectionHeader color="bg-green-500" label={`Pick do Dia · ${todayDateStr}`} />
                {today?.dica_do_dia ? <PickSeguroCard dica={today.dica_do_dia} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(today.dica_do_dia.fixture_id)} /> : <PickSeguroEmpty />}
              </div>
            )}


            <button onClick={() => navigate('/resultados')}
              className="w-full text-center text-xs text-green-500 hover:text-green-400 transition-colors py-3 border border-line rounded-md hover:border-line-strong font-semibold">
              Ver todos os resultados
            </button>
          </motion.div>
        )}

        {tab === 'vip' && (
          <motion.div key="vip" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-yellow-400/20 bg-yellow-400/5">
              <p className="font-display text-sm font-bold text-yellow-400 mb-3">O que são os Picks VIP?</p>
              <div className="space-y-2 text-sm text-ink-2 leading-relaxed">
                <p>
                  Picks exclusivos gerados pela <span className="text-ink-1 font-bold">IA</span> com análise estatística avançada.
                  A cada dia a IA processa forma recente, confrontos diretos, odds de mercado e gera
                  {' '}<span className="text-yellow-400 font-bold">10 a 20 picks de alta confiança</span>.
                </p>
                <p>
                  Cada pick inclui análise completa: estatísticas dos times, forma dos últimos jogos, previsão por mercado,
                  odds e casa de apostas recomendada.
                </p>
                <div className="grid grid-cols-3 gap-3 mt-3">
                  {[
                    { label: 'Picks/dia',    value: '10–20',  color: 'text-yellow-400' },
                    { label: 'Mercados',     value: '5+',     color: 'text-ink-1'      },
                    { label: 'Análise IA',   value: 'Completa', color: 'text-green-400' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-surface-1 rounded-md p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-ink-4 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Picks do dia */}
            <div>
              <SectionHeader
                color="bg-yellow-400"
                label={`Picks do Dia · ${todayDateStr}`}
              />
              {!canSeeVip ? <VipLockOverlay color="yellow" /> : todayLoading ? <PickLoading /> : (() => {
                const vips = today?.vip ?? []
                const leagues = Array.from(new Set(vips.map((s: any) => s.league_name).filter(Boolean))) as string[]
                const byLeague = leagueFilter ? vips.filter((s: any) => s.league_name === leagueFilter) : vips
                const filteredVips = vipResultFilter
                  ? byLeague.filter((s: any) => vipResultFilter === 'pending' ? !s.result : s.result === vipResultFilter)
                  : byLeague
                const filterGroups: FilterGroup[] = [
                  ...(leagues.length > 1 ? [{
                    key: 'league', label: 'Liga',
                    options: [{ value: '', label: 'Todas' }, ...leagues.map(lg => ({ value: lg, label: lg }))],
                    value: leagueFilter, onChange: setLeagueFilter,
                  }] : []),
                  ...(vips.length > 1 ? [{
                    key: 'resultado', label: 'Resultado',
                    options: [{ value: '', label: 'Todos' }, { value: 'pending', label: 'Pendentes' }, { value: 'GREEN', label: 'Green' }, { value: 'RED', label: 'Red' }],
                    value: vipResultFilter, onChange: setVipResultFilter,
                  }] : []),
                ]
                return (
                  <>
                    {filterGroups.length > 0 && <FilterPanel accent="yellow" groups={filterGroups} resultado={filteredVips.length} />}
                    {filteredVips.length > 0 ? (
                      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                        {filteredVips.map((s: any) => (
                          <SuggestionCard key={s.id} s={s} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(s.fixture_id)} />
                        ))}
                      </motion.div>
                    ) : (
                      <div className="card p-8 text-center border-dashed">
                        <p className="text-ink-3 text-sm font-semibold">{leagueFilter || vipResultFilter ? 'Nenhum pick encontrado com esse filtro.' : 'Picks VIP do dia ainda não gerados.'}</p>
                        <p className="text-ink-4 text-xs mt-1">{leagueFilter || vipResultFilter ? '' : 'Os picks saem pela manhã. Volte mais tarde.'}</p>
                      </div>
                    )}
                  </>
                )
              })()}
            </div>


            <button onClick={() => navigate('/resultados')}
              className="w-full text-center text-xs text-yellow-400 hover:text-yellow-300 transition-colors py-3 border border-line rounded-md hover:border-line-strong font-semibold">
              Ver todos os resultados
            </button>
          </motion.div>
        )}

        {tab === 'multiplas' && (
          <motion.div key="multiplas" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-blue-400/20 bg-blue-400/5">
              <p className="font-display text-sm font-bold text-blue-400 mb-3">O que são as Múltiplas VIP?</p>
              <div className="space-y-2 text-sm text-ink-2 leading-relaxed">
                <p>
                  A IA combina <span className="text-ink-1 font-bold">2 a 3 seleções</span> de alta confiança em uma única aposta múltipla,
                  gerando odds combinadas entre <span className="text-blue-400 font-bold">2.00 e 4.00</span> com risco controlado.
                </p>
                <p>
                  Cada seleção da múltipla é analisada individualmente antes de compor a aposta.
                  Publicadas diariamente com raciocínio completo da IA para cada perna.
                </p>
                <div className="grid grid-cols-3 gap-3 mt-3">
                  {[
                    { label: 'Seleções',   value: '2–3',   color: 'text-blue-400'   },
                    { label: 'Odd alvo',   value: '2.00–4.00', color: 'text-green-400'  },
                    { label: 'Frequência', value: 'Diário', color: 'text-ink-1'     },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-surface-1 rounded-md p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-ink-4 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Múltiplas de hoje */}
            <div>
              <SectionHeader color="bg-blue-400" label={`Múltiplas do Dia · ${todayDateStr}`} />
              {!canSeeVip ? <VipLockOverlay color="blue" /> : todayLoading ? <PickLoading /> : (
                today?.multiplas?.length > 0 ? (
                  <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-4">
                    {today.multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isMultiplaLive(m)} />)}
                  </motion.div>
                ) : (
                  <div className="card p-8 text-center border-dashed">
                    <p className="text-ink-3 text-sm font-semibold">Múltipla do dia ainda não gerada.</p>
                    <p className="text-ink-4 text-xs mt-1">Publicada diariamente pela manhã.</p>
                  </div>
                )
              )}
            </div>


            <button onClick={() => navigate('/resultados')}
              className="w-full text-center text-xs text-blue-400 hover:text-blue-300 transition-colors py-3 border border-line rounded-md hover:border-line-strong font-semibold">
              Ver todos os resultados
            </button>
          </motion.div>
        )}

        {tab === 'alavancagem' && (
          <motion.div key="alavancagem" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="space-y-6">
            {/* Como funciona */}
            <div className="card p-5 border-orange-500/20 bg-orange-500/5">
              <p className="font-display text-sm font-bold text-orange-400 mb-3">Como funciona a Alavancagem?</p>
              <div className="space-y-2 text-sm text-ink-2 leading-relaxed">
                <p>
                  A banca começa em <span className="text-ink-1 font-bold">R$50</span> e o lucro de cada GREEN é
                  reinvestido integralmente na próxima aposta, sem retirar nada.
                </p>
                <p>
                  A cada <span className="text-red-400 font-bold">RED</span>, a banca reseta para R$50 e uma nova
                  série começa do zero. A IA seleciona 1 pick (ou combinada de 2 com alta correlação)
                  com <span className="text-ink-1 font-bold">odd combinada entre 1.45 e 1.90</span> para maximizar a consistência.
                </p>
                <p>
                  O objetivo é <span className="text-green-400 font-bold">encadear greens consecutivos</span> e multiplicar
                  a banca progressivamente durante o torneio. Uma sequência de 5 greens transforma R$50 em mais de R$300.
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                  {[
                    { label: 'Banca inicial', value: 'R$50',   color: 'text-orange-400' },
                    { label: 'Odd alvo',      value: '1.45–1.90', color: 'text-green-400'  },
                    { label: 'Reset no RED',  value: 'R$50',   color: 'text-red-400'    },
                    { label: '5 greens',      value: 'R$300+', color: 'text-ink-1'      },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-surface-1 rounded-md p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-ink-4 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Stats da série + Pick de hoje (bloqueado para free) */}
            {!canSeeVip ? (
              <div>
                <SectionHeader color="bg-orange-400" label={`Pick do Dia · ${todayDateStr}`} />
                <VipLockOverlay color="orange" />
              </div>
            ) : (
              <>
                {/* Como funciona, antes de qualquer numero. A alavancagem e o
                    unico produto do site que nao e "uma aposta, um resultado",
                    e sem explicar a regra o card vira um monte de valor solto. */}
                <details className="card p-4 border-orange-500/20 mb-4">
                  <summary className="cursor-pointer text-sm font-bold text-orange-400 select-none">
                    Como funciona a alavancagem
                  </summary>
                  <div className="mt-3 space-y-2 text-xs text-ink-2 leading-relaxed">
                    <p>
                      Não é uma aposta por dia, é um <b>caminho</b>. Você define um valor de
                      entrada e, a cada green, reaposta o bolo inteiro no pick do dia seguinte.
                      Cada etapa tem odd combinada entre 1.40 e 1.55.
                    </p>
                    <p>
                      O caminho fecha sozinho ao chegar em <b>{userAlavSerie?.meta ?? 6} greens</b>,
                      que multiplicam a entrada por cerca de 10. Aí o lucro vira dinheiro e entra
                      na sua banca. Você também pode encerrar antes, a qualquer momento: se quiser
                      parar no segundo green, para no segundo.
                    </p>
                    <p>
                      Se der <b>red</b> em qualquer etapa, o caminho acaba e você perde apenas o
                      valor de entrada, nunca o acumulado. O bolo que estava em jogo nunca saiu da
                      mesa, então nunca foi seu para perder. Um caminho novo começa em seguida, no
                      mesmo valor.
                    </p>
                    <p className="text-ink-3">
                      É por isso que o valor em andamento não conta na sua banca: ele está inteiro
                      apostado na próxima etapa. Em unidades, o caminho arrisca 1u e paga cerca de
                      +9u quando fecha.
                    </p>
                  </div>
                </details>

                {/* Pick de hoje */}
                {todayLoading ? <PickLoading /> : (
                  <div>
                    <SectionHeader color="bg-orange-400" label={`Pick do Dia · ${todayDateStr}`} />
                    {today?.alavancagem ? (
                      <AlavancagemCard
                        pick={today.alavancagem}
                        userBankroll={userAlavSerie?.configured ? userAlavSerie.current_bankroll : undefined}
                        onConfigureBanca={irParaConfigAlavancagem}
                        isLive={isAlavLive(today.alavancagem)}
                      />
                    ) : (
                      <div className="card p-8 text-center border-dashed border-orange-500/20">
                        <p className="text-ink-3 text-sm font-semibold">Pick de alavancagem não gerado para hoje.</p>
                        <p className="text-ink-4 text-xs mt-1">Publicado quando a análise do dia fecha.</p>
                      </div>
                    )}
                  </div>
                )}

                {/* Caminho DEPOIS do pick (16/08). Ele estava no topo e
                    empurrava a entrada do dia pra baixo da dobra · o caminho e'
                    o contexto, o pick e' o que se veio ver. */}
                {/* Config banca alavancagem */}
                <div ref={alavConfigRef} className="card p-5 border-orange-500/20 scroll-mt-24">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="font-display text-sm font-bold text-orange-400">Caminho de Alavancagem</p>
                      <p className="text-xs text-ink-3 mt-0.5">
                        Cada GREEN reaposta o bolo inteiro. Fecha sozinho em {userAlavSerie?.meta ?? 6} greens,
                        mas você pode encerrar antes quando quiser
                      </p>
                    </div>
                    {userAlavSerie?.configured && (
                      <div className="font-mono text-right">
                        <div className="text-2xl font-black text-orange-400">R${userAlavSerie.current_bankroll.toFixed(2)}</div>
                        <div className="text-xs text-ink-4">entrada: R${userAlavSerie.initial_bankroll.toFixed(2)}</div>
                      </div>
                    )}
                  </div>

                  {/* O ponto todo da tela: enquanto o caminho roda, esse número
                      não é saldo · está inteiro apostado na próxima entrada. */}
                  {userAlavSerie?.configured && (
                    <div className="mb-3 rounded-lg border border-orange-500/20 bg-orange-500/[0.06] px-3 py-2.5">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-[11px] text-ink-3">
                            {(userAlavSerie.open_profit ?? 0) > 0
                              ? <>Lucro em jogo: <span className="font-mono font-black text-orange-400">+R${(userAlavSerie.open_profit ?? 0).toFixed(2)}</span>
                                 {!!userAlavSerie.open_units && <span className="text-ink-4"> ({userAlavSerie.open_units >= 0 ? '+' : ''}{userAlavSerie.open_units.toFixed(2)}u)</span>}</>
                              : 'Caminho recém-começado'}
                          </p>
                          <p className="text-[11px] text-ink-4 mt-0.5 leading-snug">
                            Não conta na sua banca enquanto o caminho estiver rodando.
                            {' '}Se der RED você perde só os R${userAlavSerie.initial_bankroll.toFixed(2)} da entrada.
                          </p>
                        </div>
                        {userAlavSerie.can_close && !alavConfirmClose && (
                          <button
                            onClick={() => { setAlavConfirmClose(true); setAlavCloseMsg('') }}
                            className="shrink-0 bg-orange-500 hover:bg-orange-400 text-ink-1 font-black px-3 py-2 rounded-md text-xs transition-colors"
                          >
                            Encerrar
                          </button>
                        )}
                      </div>

                      {alavConfirmClose && (
                        <div className="mt-3 pt-3 border-t border-orange-500/20">
                          <p className="text-xs text-ink-2 leading-snug">
                            Encerrar agora leva <span className="font-mono font-black text-green-400">+R${(userAlavSerie.open_profit ?? 0).toFixed(2)}</span> pra sua banca
                            {' '}e recomeça um caminho novo em R${userAlavSerie.initial_bankroll.toFixed(2)}.
                          </p>
                          <div className="flex gap-2 mt-2.5">
                            <button
                              onClick={encerrarCaminho}
                              disabled={alavEncerrando}
                              className="bg-green-500 hover:bg-green-400 disabled:opacity-50 text-surface-0 font-black px-3 py-2 rounded-md text-xs transition-colors"
                            >
                              {alavEncerrando ? 'Encerrando...' : 'Confirmar e sacar'}
                            </button>
                            <button
                              onClick={() => setAlavConfirmClose(false)}
                              className="px-3 py-2 rounded-md border border-line-strong text-ink-3 hover:text-ink-1 text-xs font-bold transition-colors"
                            >
                              Continuar o caminho
                            </button>
                          </div>
                        </div>
                      )}

                      {alavCloseMsg && (
                        <p className="text-xs text-green-400 font-semibold mt-2 leading-snug">{alavCloseMsg}</p>
                      )}
                    </div>
                  )}

                  {/* Progresso até a meta. O caminho fecha sozinho ao bater, e
                      esse é o ponto: composto que não para é lucro que nunca
                      existe, porque um RED lá na frente transforma tudo em pó. */}
                  {userAlavSerie?.configured && !!userAlavSerie.meta && (() => {
                    const feitos = userAlavSerie.greens_no_caminho ?? 0
                    const meta = userAlavSerie.meta!
                    const faltam = Math.max(0, meta - feitos)
                    return (
                      <div className="mb-4 rounded-lg border border-orange-500/20 bg-orange-500/[0.04] px-4 py-3">
                        <div className="flex items-baseline justify-between gap-3 mb-2">
                          <span className="text-xs text-ink-3">Progresso do caminho</span>
                          <span className="font-mono text-sm">
                            <span className="text-orange-400 font-black text-lg">{feitos}</span>
                            <span className="text-ink-4"> de {meta} greens</span>
                          </span>
                        </div>
                        {/* Degraus com numero dentro · a fileira de tracinhos de
                            1,5px era pequena demais pra contar de relance, que e
                            a unica coisa que se quer saber aqui. */}
                        <div className="flex gap-1.5">
                          {Array.from({ length: meta }).map((_, i) => (
                            <span
                              key={i}
                              className={`flex-1 h-7 rounded-md flex items-center justify-center text-[11px] font-black transition-colors ${
                                i < feitos
                                  ? 'bg-orange-400 text-surface-0'
                                  : 'bg-surface-2 text-ink-4 border border-line'
                              }`}
                            >
                              {i + 1}
                            </span>
                          ))}
                        </div>
                        <p className="text-[11px] text-ink-4 mt-2 leading-snug">
                          {faltam === 0
                            ? 'Meta batida · o caminho fecha e o lucro vai pra sua banca.'
                            : `Faltam ${faltam} ${faltam === 1 ? 'green' : 'greens'} pra fechar sozinho. Você pode encerrar antes quando quiser.`}
                        </p>
                      </div>
                    )
                  })()}

                  {/* Passos do caminho atual · a escada que levou até o bolo de hoje */}
                  {!!userAlavSerie?.steps?.length && (
                    <div className="mb-3 flex flex-wrap items-center gap-1.5">
                      <span className="text-[10px] text-ink-4 font-mono">R${userAlavSerie.initial_bankroll.toFixed(0)}</span>
                      {userAlavSerie.steps.map(s => (
                        <span key={s.pick_id} className="flex items-center gap-1">
                          <span className="text-ink-4 text-[10px]">&rsaquo;</span>
                          <span
                            title={`${s.match} · odd ${s.odd.toFixed(2)}`}
                            className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                              s.result === 'GREEN'
                                ? 'bg-green-500/10 text-green-400'
                                : 'bg-red-500/10 text-red-400 line-through'
                            }`}
                          >
                            R${s.after.toFixed(0)}
                          </span>
                        </span>
                      ))}
                    </div>
                  )}

                  {!!userAlavSerie?.history?.length && (
                    <details className="mb-3">
                      <summary className="cursor-pointer text-[11px] text-ink-3 hover:text-ink-1 select-none font-semibold">
                        Caminhos anteriores ({userAlavSerie.history.length})
                      </summary>
                      <ul className="mt-2 divide-y divide-line/50">
                        {userAlavSerie.history.map(h => (
                          <li key={h.id} className="py-2 flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-[11px] text-ink-2">
                                R${h.initial.toFixed(0)} <span className="text-ink-4">para</span> R${h.final.toFixed(0)}
                                <span className={`ml-2 font-bold ${
                                  h.end_reason === 'red' ? 'text-red-400'
                                  : h.end_reason === 'meta' ? 'text-green-400' : 'text-orange-400'}`}>
                                  {h.end_reason === 'red' ? 'estourou'
                                   : h.end_reason === 'meta' ? 'bateu a meta' : 'encerrado por você'}
                                </span>
                              </p>
                              <p className="text-[10px] text-ink-4">
                                {/* "Peguei esse caminho?" · caminho sem green seguido existe
                                    no banco mas nunca foi jogado. */}
                                {h.greens > 0
                                  ? `${h.greens} ${h.greens === 1 ? 'green seu' : 'greens seus'}`
                                  : 'você não seguiu nenhum pick deste caminho'}
                                {h.ended_at && ` · ${h.ended_at.slice(8, 10)}/${h.ended_at.slice(5, 7)}`}
                              </p>
                            </div>
                            <span className={`font-mono text-xs font-bold shrink-0 ${h.realized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {h.realized >= 0 ? '+' : ''}R${h.realized.toFixed(2)}
                              <span className="block text-[10px] text-ink-4 font-normal text-right">
                                {h.units >= 0 ? '+' : ''}{h.units.toFixed(2)}u
                              </span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

                  {!!userAlavSerie?.realized_total && (
                    <p className="text-[11px] text-ink-4 mb-3">
                      Já realizado em caminhos encerrados:{' '}
                      <span className={`font-mono font-bold ${userAlavSerie.realized_total >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {userAlavSerie.realized_total >= 0 ? '+' : ''}R${userAlavSerie.realized_total.toFixed(2)}
                      </span>
                      {userAlavSerie.realized_units != null && (
                        <span className="text-ink-4"> ({userAlavSerie.realized_units >= 0 ? '+' : ''}{userAlavSerie.realized_units.toFixed(2)}u)</span>
                      )}
                    </p>
                  )}
                  {(!userAlavSerie?.configured || alavInitInput) ? (
                    <div className="flex gap-2 mt-2">
                      <input
                        type="number"
                        min="1"
                        step="10"
                        placeholder={userAlavSerie?.configured ? `Atual: R$${userAlavSerie.initial_bankroll.toFixed(0)}` : 'Ex: 100'}
                        value={alavInitInput}
                        onChange={e => setAlavInitInput(e.target.value)}
                        className="input font-mono flex-1 text-sm"
                      />
                      <button
                        onClick={saveAlavInit}
                        disabled={alavInitSaving || !alavInitInput}
                        className="bg-orange-500 hover:bg-orange-400 disabled:opacity-50 text-ink-1 font-black px-4 py-2 rounded-md text-sm transition-colors"
                      >
                        {alavInitSaving ? '...' : userAlavSerie?.configured ? 'Alterar' : 'Definir'}
                      </button>
                      {userAlavSerie?.configured && (
                        <button onClick={() => setAlavInitInput('')} aria-label="Cancelar" className="px-3 py-2 rounded-md border border-line-strong text-ink-3 hover:text-ink-1 transition-colors"><XIcon className="w-4 h-4" /></button>
                      )}
                    </div>
                  ) : (
                    <button
                      onClick={() => setAlavInitInput(String(userAlavSerie.initial_bankroll))}
                      className="text-[11px] px-3 py-2 rounded-md border border-line-strong text-ink-2 hover:text-ink-1 hover:border-orange-400/40 font-bold transition-colors"
                    >
                      Alterar valor inicial
                    </button>
                  )}
                  {alavInitError && (
                    <p className="text-xs text-red-400 mt-2">{alavInitError}</p>
                  )}
                </div>

                {/* Stats da série */}
                {(() => {
                  const oldest = [...alavancagem].reverse()
                  let bestStreak = 0, tempStreak = 0, resets = 0
                  for (const a of oldest) {
                    if (a.result === 'GREEN')    { tempStreak++; if (tempStreak > bestStreak) bestStreak = tempStreak }
                    else if (a.result === 'RED') { resets++; tempStreak = 0 }
                  }
                  let currentStreak = 0
                  for (const a of alavancagem) {
                    if (!a.result) continue
                    if (a.result === 'GREEN') currentStreak++
                    else break
                  }
                  const userBankroll  = userAlavSerie?.configured ? userAlavSerie.current_bankroll : null
                  const initialBankroll = userAlavSerie?.configured ? userAlavSerie.initial_bankroll : 50

                  return (
                    <div>
                      <SectionHeader color="bg-orange-400" label="Progresso da Série" />
                      {alavLoading ? (
                        <div className="flex justify-center py-6"><Spinner tone="orange" /></div>
                      ) : alavError ? (
                        <div className="card p-8 text-center border-dashed">
                          <p className="text-ink-2 text-sm font-semibold mb-1">Erro ao carregar a série</p>
                          <p className="text-ink-4 text-xs mb-3">Não foi possível conectar ao servidor.</p>
                          <button onClick={() => doFetchAlavancagem(alavFilters)} className="text-xs text-orange-400 hover:text-orange-300 font-semibold transition-colors">
                            Tentar novamente
                          </button>
                        </div>
                      ) : !alavancagem.length ? (
                        <div className="card p-8 text-center border-dashed border-orange-500/20">
                          <p className="text-ink-3 text-sm font-semibold">Série ainda não iniciada.</p>
                          <p className="text-ink-4 text-xs mt-1">Os stats aparecem assim que os primeiros picks forem gerados.</p>
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                          {[
                            {
                              label: 'Sua banca atual',
                              value: userBankroll != null ? `R$${userBankroll.toFixed(2)}` : '',
                              color: userBankroll != null && userBankroll > initialBankroll ? 'text-green-400' : 'text-orange-400',
                              sub: userBankroll != null && userBankroll > initialBankroll ? `+R$${(userBankroll - initialBankroll).toFixed(2)}` : userAlavSerie?.configured ? 'Início da série' : 'Cadastre sua banca',
                            },
                            { label: 'Resets (RED)', value: String(resets), color: resets > 0 ? 'text-red-400' : 'text-ink-3', sub: resets === 0 ? 'Nenhum ainda' : `${resets} reinício${resets > 1 ? 's' : ''}` },
                            { label: 'Série Atual', value: currentStreak > 0 ? `${currentStreak} green${currentStreak > 1 ? 's' : ''}` : '', color: currentStreak >= 3 ? 'text-green-400' : currentStreak > 0 ? 'text-green-500' : 'text-ink-3', sub: currentStreak > 0 ? 'seguidos' : 'Aguardando' },
                            { label: 'Melhor Série', value: bestStreak > 0 ? `${bestStreak} green${bestStreak > 1 ? 's' : ''}` : '', color: 'text-yellow-400', sub: bestStreak > 0 ? 'recorde da série' : 'Ainda sem greens' },
                          ].map(({ label, value, color, sub }) => (
                            <div key={label} className="card p-4 text-center">
                              <div className={`font-mono text-xl font-black ${color}`}>{value}</div>
                              <div className="text-xs text-ink-3 font-semibold mt-0.5">{label}</div>
                              <div className="text-[10px] text-ink-4 mt-0.5">{sub}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })()}

                {/* Caminho da série */}
                {!alavLoading && alavancagem.length > 0 && (
                  <div>
                    <SectionHeader color="bg-orange-400" label="Caminho da Série" />
                    {alavHasMore && (
                      <button
                        onClick={loadMoreAlavancagem}
                        disabled={alavLoadingMore}
                        className="w-full text-center text-xs text-ink-3 hover:text-ink-2 disabled:opacity-50 transition-colors py-2 mb-3 border border-line rounded-md hover:border-line-strong font-semibold"
                      >
                        {alavLoadingMore ? 'Carregando...' : 'Carregar picks mais antigos'}
                      </button>
                    )}
                    <div className="space-y-0">
                      {[...alavancagem].reverse().map((pick: any, idx: number, arr: any[]) => {
                        const res = pick.result
                        const date = pick.match_date
                          ? new Date(pick.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                          : ''
                        const bankBefore = pick.bankroll_before != null ? Number(pick.bankroll_before) : null
                        const bankAfter  = pick.bankroll_after  != null ? Number(pick.bankroll_after)  : null
                        const profit     = bankBefore != null && bankAfter != null ? bankAfter - bankBefore : null
                        return (
                          <div key={pick.id} className="flex gap-3">
                            <div className="flex flex-col items-center w-8 shrink-0">
                              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-black border ${
                                !res
                                  ? 'bg-orange-500 border-orange-400 text-black'
                                  : res === 'GREEN' ? 'bg-green-500/20 border-green-500/40 text-green-400'
                                  : 'bg-red-500/20 border-red-500/40 text-red-400'
                              }`}>
                                {res === 'GREEN' ? '✓' : res === 'RED' ? '✗' : <Clock className="w-3 h-3" />}
                              </div>
                              {idx < arr.length - 1 && (
                                <div className={`w-0.5 flex-1 my-1 min-h-[16px] ${res === 'GREEN' ? 'bg-green-500/30' : res === 'RED' ? 'bg-red-500/30' : 'bg-surface-2'}`} />
                              )}
                            </div>
                            <div
                              className={`flex-1 mb-2 rounded-md border px-3 py-2.5 cursor-pointer hover:border-orange-500/40 transition-colors ${
                                !res ? 'border-orange-500/40 bg-orange-500/5' : 'border-line bg-surface-1'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex-1 min-w-0">
                                  {/* Sem escudo aqui de proposito. picks_alavancagem
                                      nao tem coluna de team_id: o id so' chega quando a
                                      fixture ainda existe pra enriquecer, e fixture velha
                                      e' purgada. O resultado era metade da lista com
                                      escudo e metade sem, que le como imagem quebrada.
                                      Nenhum escudo e' consistente; metade nao e'. */}
                                  <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
                                    <span className="text-xs font-bold text-ink-1 truncate">{pick.home_team_1}</span>
                                    <span className="text-ink-4 text-[10px]">vs</span>
                                    <span className="text-xs font-bold text-ink-1 truncate">{pick.away_team_1}</span>
                                  </div>
                                  <div className="text-[10px] text-ink-3">{date}</div>
                                </div>
                                <div className="font-mono text-right shrink-0 space-y-0.5">
                                  {bankBefore != null && (
                                    <div className="text-[10px] text-ink-4">R${bankBefore.toFixed(2)}</div>
                                  )}
                                  {profit != null && (
                                    <div className={`text-xs font-black ${profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                      {profit >= 0 ? '+' : ''}R${profit.toFixed(2)}
                                    </div>
                                  )}
                                  {bankAfter != null && (
                                    <div className="text-[10px] text-ink-3">Banca: R${bankAfter.toFixed(2)}</div>
                                  )}
                                  {!res && bankBefore != null && (
                                    <div className="text-[10px] text-orange-400 font-semibold">Em aberto</div>
                                  )}
                                </div>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </>
            )}


            <button onClick={() => navigate('/resultados')}
              className="w-full text-center text-xs text-orange-400 hover:text-orange-300 transition-colors py-3 border border-line rounded-md hover:border-line-strong font-semibold">
              Ver todos os resultados
            </button>
          </motion.div>
        )}

        {tab === 'mercados' && (
          <motion.div key="mercados" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="space-y-8">
            {!canSeeVip ? (
              <div>
                <SectionHeader color="bg-purple-400" label="Mercados" />
                <VipLockOverlay color="purple" />
              </div>
            ) : (
              <>
                {/* Mesmo painel da aba VIP, logo acima · a aba tinha controles
                    próprios (busca inline, três filas de pill, um select de
                    ordenação) e parecia outra ferramenta dentro da mesma
                    página. A contagem de cada categoria fica no rótulo, que é
                    onde ela responde "tem quantos de faltas hoje?". */}
                <FilterPanel
                  accent="green"
                  busca={{
                    value: mercadoFiltro.busca,
                    onChange: v => setMercadoFiltro({ ...mercadoFiltro, busca: v }),
                    placeholder: 'Buscar time, goleiro ou linha',
                  }}
                  groups={[
                    {
                      key: 'categoria', label: 'Mercado',
                      options: [
                        { value: 'todos',    label: `Todos (${(faltas?.length ?? 0) + (goleiros?.length ?? 0)})` },
                        { value: 'faltas',   label: `Faltas (${faltas?.length ?? 0})` },
                        { value: 'goleiros', label: `Defesas (${goleiros?.length ?? 0})` },
                      ],
                      value: mercadoFiltro.categoria,
                      onChange: v => setMercadoFiltro({ ...mercadoFiltro, categoria: v as MercadoFiltro['categoria'] }),
                    },
                    {
                      key: 'estado', label: 'Situação',
                      options: [
                        { value: 'todos',      label: 'Todos' },
                        { value: 'pendentes',  label: 'Pendentes' },
                        { value: 'resolvidos', label: 'Resolvidos' },
                      ],
                      value: mercadoFiltro.estado,
                      onChange: v => setMercadoFiltro({ ...mercadoFiltro, estado: v as MercadoFiltro['estado'] }),
                    },
                  ]}
                  ordem={{
                    options: [
                      { value: 'margem', label: 'Maior margem' },
                      { value: 'odd',    label: 'Maior odd' },
                      { value: 'data',   label: 'Data do jogo' },
                    ],
                    value: mercadoFiltro.ordem,
                    onChange: v => setMercadoFiltro({ ...mercadoFiltro, ordem: v as MercadoFiltro['ordem'] }),
                  }}
                  resultado={faltasFiltradas.length + goleirosFiltrados.length}
                />

                {/* Nada bateu o filtro. Sem isso as duas seções apareciam com o
                    vazio genérico de "nenhum pick ainda", que é outra coisa:
                    ali não existe pick, aqui existe e o filtro escondeu. */}
                {faltasFiltradas.length === 0 && goleirosFiltrados.length === 0 && !todayLoading && (faltas?.length || goleiros?.length) ? (
                  <EmptyState
                    Icon={SearchX}
                    title="Nenhum mercado com esses filtros"
                    description="Tente outro time, outra linha, ou volte para todos os mercados do dia."
                    action={{ children: 'Limpar filtros', variant: 'ghost', onClick: () => setMercadoFiltro(FILTRO_INICIAL) }}
                    compact
                  />
                ) : (
                  <>
                    {mercadoFiltro.categoria !== 'goleiros' && (
                      <MercadoSecao
                        tipo="faltas"
                        titulo="Faltas"
                        cor="bg-purple-400"
                        explicacao="Total de faltas do jogo. A previsão combina o histórico de faltas dos dois times com o do árbitro, e a probabilidade sai da taxa medida em jogos reais nessa faixa de previsão."
                        picks={faltas === null ? null : faltasFiltradas}
                        carregando={todayLoading}
                        banca={bancaSummary?.has_banca ? bancaSummary : null}
                      />
                    )}
                    {mercadoFiltro.categoria !== 'faltas' && (
                      <MercadoSecao
                        tipo="goleiros"
                        titulo="Defesas de goleiro"
                        cor="bg-sky-400"
                        explicacao="Quantas defesas um goleiro específico faz no jogo. O sinal principal é o volume de chutes no alvo que o adversário costuma produzir."
                        picks={goleiros === null ? null : goleirosFiltrados}
                        carregando={todayLoading}
                        banca={bancaSummary?.has_banca ? bancaSummary : null}
                      />
                    )}
                  </>
                )}
              </>
            )}
          </motion.div>
        )}
        </AnimatePresence>
        {/* Ao Vivo · o produto novo (oportunidades do Motor Live).
            Fora do AnimatePresence acima pelo mesmo motivo de Minhas Apostas:
            as duas abas mantêm polling próprio e não podem ser desmontadas e
            remontadas a cada troca de aba. */}
        {/* Não montado quando a aba está desligada · o feed faz polling
            próprio, e um componente escondido com `hidden` continuaria
            batendo em /live-picks/feed de graça pra todo VIP. */}
        {/* O chunk só é buscado na primeira vez que a aba abre. Depois disso a
            aba continua montada com `hidden`, como era antes · ela tem polling
            próprio e estado que não pode ser perdido a cada troca de aba. */}
        {LIVE_PICKS_ENABLED && jaAbriuAoVivo.current && (
          <div className={tab !== 'ao_vivo' ? 'hidden' : ''}>
            <Suspense fallback={<PickLoading />}>
              <LivePicksFeed isActive={tab === 'ao_vivo'} />
            </Suspense>
          </div>
        )}

        {/* Minhas Apostas · o que o usuário decidiu seguir, pré-jogo e ao vivo.
            Fica montada depois da primeira visita (o `hidden` preserva o estado
            e o polling próprio dela), mas só é baixada quando o usuário chega. */}
        {jaAbriuMinhasApostas.current && (
          <div className={tab !== 'minhas_apostas' ? 'hidden' : ''}>
            <Suspense fallback={<PickLoading />}>
              <LivePicks isActive={tab === 'minhas_apostas'} unitValue={bancaSummary?.unit_value} />
            </Suspense>
          </div>
        )}



    </PageShell>
  )
}

