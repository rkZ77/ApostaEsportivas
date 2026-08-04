import { useEffect, useState, useCallback, useMemo } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { toastUp, fadeInUp, staggerContainer, tabFade } from '../lib/motion'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import SuggestionCard from '../components/SuggestionCard'
import ApostaModal from '../components/ApostaModal'
import SuggestionDetail from '../components/SuggestionDetail'
import PageShell from '../components/PageShell'
import Avatar from '../components/Avatar'
import { LiveDot, Spinner, EmptyState, Badge, PickTypeBadge, ResultBadge } from '../components/ui'
import MercadosControls, { aplicarFiltro, FILTRO_INICIAL, type MercadoFiltro } from '../components/MercadosControls'
import FavoriteButton from '../components/FavoriteButton'
import EngineStatus from '../components/EngineStatus'
import AnalysisModal from '../components/AnalysisModal'
import { PickCardFooter, PickExplainButton, PickConfidence, PickStats, PickReasoning } from '../components/PickCardParts'
import { useFavorites } from '../context/FavoritesContext'
import LivePicks from '../components/LivePicks'
import PicksPendingCard from '../components/PicksPendingCard'
import { UserCircle, Crown, Rocket, Wallet, Clock, ChevronLeft, ChevronRight, BrainCircuit, Share2, Check as CheckIcon, Loader2, SearchX } from 'lucide-react'
import { calcFreeStake, calcMultiplaStake, calcProfitUnits } from '../utils/stakeUtils'
import { getResultStyle, PICK_TYPE_CLS, PICK_TYPE_BORDER } from '../utils/resultStyle'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { translateMarket, translateLine, translateTeamName, explainMarket } from '../utils/marketTranslate'
import FilterPanel, { FilterGroup } from '../components/FilterPanel'
import InfoTip from '../components/InfoTip'
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
const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id?: number) =>
  id ? (LOCAL_LEAGUE_LOGOS[id] ?? `/api/proxy/league/${id}.png`) : null

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
type Tab = 'hoje' | 'pick_seguro' | 'vip' | 'multiplas' | 'alavancagem' | 'mercados' | 'aovivo' | 'chat'

const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

interface AlavFilters { date_from: string; date_to: string; resultado: string }
const defaultAlavFilters: AlavFilters = { date_from: '', date_to: TODAY, resultado: 'all' }

// Tab bar
function TabBar({ tab, setTab, canSeeVip, counts, liveCount }: {
  tab: Tab; setTab: (t: Tab) => void; canSeeVip: boolean
  counts?: Partial<Record<Tab, number>>
  liveCount?: number
}) {
  const tabs: { key: Tab; label: string; badge?: string; badgeCls?: string; premiumOnly?: boolean }[] = [
    { key: 'hoje',         label: 'Hoje'            },
    { key: 'pick_seguro',  label: 'Picks Free',      badge: 'FREE', badgeCls: 'bg-green-500/10 text-green-400 border-green-500/20' },
    { key: 'vip',          label: 'Picks VIP',       premiumOnly: true },
    { key: 'multiplas',    label: 'Múltiplas',       premiumOnly: true },
    { key: 'alavancagem',  label: 'Alavancagem',      premiumOnly: true },
    { key: 'mercados',     label: 'Mercados',         premiumOnly: true },
    {
      key: 'aovivo' as Tab, label: 'Minhas Apostas',
      badge: (liveCount ?? 0) > 0 ? String(liveCount) : 'LIVE',
      badgeCls: (liveCount ?? 0) > 0
        ? 'bg-red-500/20 text-red-300 border-red-400/40 animate-pulse'
        : 'bg-red-500/10 text-red-400 border-red-500/20',
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
        {tabs.map(t => {
          const count = counts?.[t.key]
          return (
            <motion.button
              key={t.key}
              whileTap={{ scale: 0.95 }}
              onClick={() => setTab(t.key)}
              className={`relative px-3 sm:px-4 py-3 text-xs sm:text-sm font-semibold mr-1 whitespace-nowrap flex-shrink-0 transition-colors ${
                tab === t.key ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {t.label}
              {t.badge && (
                <span className={`ml-1.5 text-[10px] border px-1.5 py-0.5 rounded font-bold uppercase ${t.badgeCls ?? 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20'}`}>
                  {t.badge}
                </span>
              )}
              {t.premiumOnly && canSeeVip && (
                <span className="ml-1.5 text-[10px] bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 px-1.5 py-0.5 rounded font-bold uppercase">
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

  const planStatusColor = isAdmin ? 'text-purple-400'
    : isTrial ? 'text-amber-400'
    : isVip ? 'text-yellow-400'
    : 'text-ink-2'

  // Countdown ao vivo
  const [countdown, setCountdown] = useState('')
  useEffect(() => {
    if (!user?.expires_at || (!isVip && !isTrial)) { setCountdown(''); return }
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

        {/* Assinatura inline */}
        <div className="mt-2 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-ink-3 text-xs">Status atual:</span>
            <span className={`text-xs font-black ${planStatusColor}`}>{planLabel}</span>
          </div>
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

// Quick stats
function QuickStats({ stats }: { stats: any }) {
  if (!stats) return null
  const streak     = stats.streak ?? 0
  const streakType = stats.streak_type
  const profit     = Number(stats.profit ?? 0)
  const winRate    = stats.win_rate ?? 0

  const items = [
    {
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
      label: 'Win Rate',
      value: `${winRate}%`,
      color: winRate >= 55 ? 'text-green-500' : winRate >= 45 ? 'text-yellow-400' : 'text-red-400',
      iconColor: 'text-green-500',
      sub: winRate >= 55 ? 'Acima da média' : 'Este mês',
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
      label: 'Lucro/mês',
      value: `${profit >= 0 ? '+' : ''}${profit.toFixed(1)}u`,
      color: profit >= 0 ? 'text-green-500' : 'text-red-400',
      iconColor: profit >= 0 ? 'text-green-500' : 'text-red-400',
      sub: profit >= 0 ? 'Positivo' : 'Negativo',
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
      ),
      label: 'Picks/mês',
      value: String(stats.total ?? 0),
      color: 'text-ink-2',
      iconColor: 'text-blue-400',
      sub: 'Finalizados',
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" />
        </svg>
      ),
      label: 'Sequência',
      value: streak > 0 ? (streakType === 'green' ? `+${streak}` : `-${streak}`) : '',
      color: streakType === 'green' ? 'text-green-500' : streakType === 'red' ? 'text-red-400' : 'text-ink-3',
      iconColor: streakType === 'green' ? 'text-orange-400' : 'text-ink-4',
      sub: streakType === 'green' ? 'Greens seguidos' : streakType === 'red' ? 'Reds seguidos' : 'Sem sequência',
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      {items.map(({ icon, label, value, color, iconColor, sub }) => (
        <div key={label} className="card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-ink-4 font-semibold uppercase">{label}</span>
            <span className={iconColor}>{icon}</span>
          </div>
          <div className={`font-mono text-2xl font-black ${color}`}>{value}</div>
          <div className="text-xs text-ink-4 mt-0.5">{sub}</div>
        </div>
      ))}
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

function PickSeguroCard({ dica, compact = false, onClick, banca, isLive = false }: { dica: any; compact?: boolean; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null; isLive?: boolean }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const navigate = useNavigate()
  const pct = Math.round((dica.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState(dica.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalOdd, setModalOdd] = useState(Number(dica.odd))
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()
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
      result: dica.result,
      profit: dica.result ? calcProfitUnits(dica.result, Number(dica.odd), dica.user_stake_units ?? stakeSuggestion?.units ?? 1, dica.user_actual_odd) : null,
    })
  }

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    let odd = Number(dica.odd)
    if (dica.fixture_id) {
      setFollowing(true)
      try {
        const { data } = await api.get('/live/pick-odd', {
          params: { fixture_id: dica.fixture_id, market_type: dica.market_type ?? '', line: dica.line ?? '' },
        })
        if (data?.odd) odd = Number(data.odd)
      } catch {
        // sem odd atualizada · segue com a odd ja salva no pick
      } finally {
        setFollowing(false)
      }
    }
    setModalOdd(odd)
    setShowModal(true)
  }

  const handleConfirm = async (actualOdd: number, betHouse: string, stakeUnits: number) => {
    setFollowing(true)
    setApiError(null)
    try {
      await api.post('/banca/follow', { pick_id: dica.id, pick_type: 'free', stake_units: stakeUnits, actual_odd: actualOdd, bet_house: betHouse })
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

  const isCopa = dica.league_id === 1
  const resultStyle = getResultStyle(dica.result)

  return (
  <>
    <motion.div
      variants={fadeInUp}
      whileHover={onClick ? { y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' } : undefined}
      whileTap={onClick ? { scale: 0.985 } : undefined}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className={`pick-card group ${isCopa ? 'border-yellow-500/20' : 'border-green-500/20'} ${onClick ? (isCopa ? 'hover:border-yellow-500/40 cursor-pointer' : 'hover:border-green-500/40 cursor-pointer') : ''}`}
      onClick={onClick}
    >
      <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent to-transparent ${isCopa ? 'via-yellow-500' : 'via-green-500'}`} />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-black ${isCopa ? 'text-yellow-500' : 'text-green-400'}`}>Pick do Dia</span>
          <span className="badge-free">FREE</span>
          {dica.league_name && (
            <div className="flex items-center gap-1">
              <LeagueLogo id={dica.league_id} name={dica.league_name} />
              <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{dica.league_name}</span>
            </div>
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

      {/* Hero: Odd | Stake | Retorno */}
      <div className="font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
          <div className="text-3xl font-black text-green-400">{Number(dica.odd).toFixed(2)}</div>
          <div className="text-[10px] text-ink-4 mt-0.5">{dica.bet_house}</div>
        </div>
        {stakeSuggestion && !dica.result ? (
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
            const u = dica.user_stake_units ?? stakeSuggestion?.units ?? 1
            const p = calcProfitUnits(dica.result, Number(dica.odd), u, dica.user_actual_odd)
            const color = p >= 0 ? 'text-green-400' : 'text-red-400'
            const profitR = banca ? Math.abs(p) * banca.unit_value : null
            return (
              <>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">Lucro</div>
                  <div className={`text-xl font-black ${color}`}>
                    {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  </div>
                  {u > 1 && <div className="text-[10px] text-ink-4">({u}u)</div>}
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">Em reais</div>
                  {profitR != null ? (
                    <div className={`text-xl font-black ${color}`}>
                      {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                    </div>
                  ) : (
                    <div className="text-xl font-black text-ink-4">-</div>
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
                <div className="text-[10px] text-ink-3 mb-0.5">Confiança</div>
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

      {/* Confiança bar */}
      <div className="px-5 pb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-ink-4">Confiança</span>
          <span className={pct >= 75 ? 'text-green-400 font-bold' : 'text-ink-3'}>{pct}%</span>
        </div>
        <div className="bg-surface-2 rounded-full h-1 overflow-hidden">
          <div
            className={`h-1 rounded-full ${pct >= 75 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-ink-4'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Reasoning snippet */}
      {fato && (
        <div className="mx-5 mb-3 px-3 py-2 bg-surface-1 border border-line rounded-md">
          <span className="text-[10px] text-ink-4 font-black uppercase">Fato · </span>
          <span className="text-[11px] text-ink-2 leading-relaxed line-clamp-2">{fato}</span>
        </div>
      )}

      {/* Footer */}
      {dica.reasoning && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!dica.result ? (banca ? handleFollow : () => navigate('/banca')) : undefined}
        betState={following ? 'loading' : followed ? 'done' : 'idle'}
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
          odd: Number(dica.odd),
          confidence: dica.confidence,
          probability: dica.probability ?? null,
          ev: dica.ev ?? null,
          reasoning: dica.reasoning,
        }}
      />
    )}
    </AnimatePresence>

    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={modalOdd}
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
  const hour = new Date().getHours()
  const msg = hour < 12
    ? 'O Pick do Dia chega até às 12h (normalmente bem antes).'
    : 'Nenhum Pick do Dia disponível para hoje.'

  return (
    <div className="card p-10 text-center border-dashed">
      <p className="text-ink-3 text-sm font-semibold mb-1">Pick do Dia indisponível</p>
      <p className="text-ink-4 text-xs">{msg}</p>
      {hour < 12 && <p className="text-ink-4 text-xs mt-2">Publicado todos os dias até às 12h</p>}
    </div>
  )
}

// Múltipla card
function MultiplaCard({ m, onClick, banca, isLive = false }: { m: any; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null; isLive?: boolean }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const navigate = useNavigate()
  let legs: any[] = []
  try { legs = typeof m.legs === 'string' ? JSON.parse(m.legs) : (m.legs ?? []) } catch { legs = [] }

  const pct = Math.round((m.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState<boolean>(!!m.is_followed)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()
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
      result: m.result,
      profit: m.result ? calcProfitUnits(m.result, Number(m.total_odd), m.user_stake_units ?? stakeSuggestion?.units ?? 1, m.user_actual_odd) : null,
    })
  }

  const handleFollow = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following || followed) return
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
      whileHover={{ y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' }}
      whileTap={{ scale: 0.985 }}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className={`pick-card group cursor-pointer ${PICK_TYPE_BORDER.multipla}`}
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
          <div className="text-3xl font-black text-green-400">{Number(m.total_odd).toFixed(2)}</div>
        </div>
        {stakeSuggestion && !m.result ? (
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
            const u = m.user_stake_units ?? stakeSuggestion?.units ?? 1
            const p = calcProfitUnits(m.result, Number(m.total_odd), u, m.user_actual_odd)
            const color = p >= 0 ? 'text-green-400' : 'text-red-400'
            const profitR = banca ? Math.abs(p) * banca.unit_value : null
            return (
              <>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">Lucro</div>
                  <div className={`text-xl font-black ${color}`}>
                    {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  </div>
                  {u > 1 && <div className="text-[10px] text-ink-4">({u}u)</div>}
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">Em reais</div>
                  {profitR != null ? (
                    <div className={`text-xl font-black ${color}`}>
                      {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                    </div>
                  ) : (
                    <div className="text-xl font-black text-ink-4">-</div>
                  )}
                </div>
              </>
            )
          })()
        ) : (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">Confiança</div>
            <div className={`text-2xl font-black ${pct >= 70 ? 'text-green-400' : 'text-ink-2'}`}>{pct}%</div>
          </div>
        )}
      </div>

      {/* Legs */}
      <div className="px-5 py-3 space-y-2">
        {legs.map((leg: any, i: number) => {
          // Se overall GREEN, todas GREEN. Se overall RED, legs sem GREEN explícito são RED
          const lr = (
            m.result === 'GREEN' ? 'GREEN' :
            m.result === 'RED'   ? (leg.result === 'GREEN' ? 'GREEN' : 'RED') :
            leg.result ?? undefined
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

      {/* Confiança bar */}
      <div className="px-5 pb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-ink-4">Confiança combinada</span>
          <span className={pct >= 70 ? 'text-green-400 font-bold' : 'text-ink-3'}>{pct}%</span>
        </div>
        <div className="bg-surface-2 rounded-full h-1 overflow-hidden">
          <div className={`h-1 rounded-full ${pct >= 70 ? 'bg-blue-500' : 'bg-surface-3'}`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Fato da IA */}
      {shortReasoning(m.reasoning) && (
        <div className="mx-5 mb-3 px-3 py-2 bg-surface-1 border border-line rounded-md">
          <span className="text-[10px] text-ink-4 font-black uppercase">Fato · </span>
          <span className="text-[11px] text-ink-2 leading-relaxed line-clamp-2">{shortReasoning(m.reasoning)}</span>
        </div>
      )}

      {/* Footer */}
      {m.reasoning && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!m.result ? (banca ? handleFollow : () => navigate('/banca')) : undefined}
        betState={following ? 'loading' : followed ? 'done' : 'idle'}
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
        }}
      />
    )}
    </AnimatePresence>
    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={Number(m.total_odd)}
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
function AlavancagemCard({ pick, onClick, userBankroll, onConfigureBanca, isLive = false }: { pick: any; onClick?: () => void; userBankroll?: number; onConfigureBanca?: () => void; isLive?: boolean }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const navigate    = useNavigate()
  const isCombo     = pick.tipo === 'dupla' || pick.tipo === 'tripla' || pick.tipo === 'combinacao'
  const comboLabel  = pick.tipo === 'tripla' ? 'Tripla' : pick.tipo === 'dupla' ? 'Dupla' : 'Combinada'
  const oddCombined = Number(pick.odd_combined ?? 0)
  // stake monetário: bankroll do usuário > bankroll_before salvo > fallback 50
  const stake       = userBankroll != null ? userBankroll : Number(pick.bankroll_before ?? pick.stake ?? 50)
  const potReturn   = oddCombined > 0 ? stake * oddCombined : Number(pick.potential_return ?? 0)
  const confPct     = Math.round((pick.confidence_media ?? 0) * 100)
  // profit calculado do bankroll real × odd (não usa o campo profit do DB que pode estar em unidades)
  const profit = pick.result === 'GREEN'
    ? stake * (oddCombined - 1)
    : pick.result === 'RED'
    ? -stake
    : null
  const [followed, setFollowed] = useState<boolean>(!!pick.is_followed)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()

  const handleFollow = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following || followed) return
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
      whileHover={{ y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' }}
      whileTap={{ scale: 0.985 }}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className={`pick-card group cursor-pointer ${PICK_TYPE_BORDER.alavancagem}`}
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
          const boxClass = pick.result === 'GREEN'
            ? 'border-green-500/20 bg-green-500/5'
            : pick.result === 'RED'
            ? 'border-red-500/20 bg-red-500/5'
            : 'border-line bg-surface-1/60'
          const circleClass = pick.result === 'GREEN'
            ? 'bg-green-500/20 text-green-400'
            : pick.result === 'RED'
            ? 'bg-red-500/20 text-red-400'
            : 'bg-orange-500/10 text-orange-400'
          return (
          <div key={i} className={`rounded-md border px-3 py-2 ${boxClass}`}>
            <div className="flex items-center gap-2">
              <span className={`w-5 h-5 flex items-center justify-center rounded-full ${circleClass} text-[10px] font-black shrink-0`}>
                {pick.result === 'GREEN' ? '✓' : pick.result === 'RED' ? '✗' : i + 1}
              </span>
              <div className="flex items-center gap-1.5 flex-1 min-w-0">
                <TeamLogo id={leg.homeId} name={leg.home ?? ''} size={20} />
                <span className="text-xs text-ink-2 font-semibold truncate">{leg.home}</span>
                <span className="text-ink-4 text-[10px] shrink-0">vs</span>
                <span className="text-xs text-ink-2 font-semibold truncate">{leg.away}</span>
                <TeamLogo id={leg.awayId} name={leg.away ?? ''} size={20} />
              </div>
              <span className={`font-mono font-black text-sm shrink-0 ${pick.result === 'GREEN' ? 'text-green-400' : pick.result === 'RED' ? 'text-red-400' : 'text-orange-300'}`}>
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

      {/* Confiança */}
      <div className="px-5 pb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-ink-4">Confiança</span>
          <span className={confPct >= 70 ? 'text-orange-400 font-bold' : 'text-ink-3'}>{confPct}%</span>
        </div>
        <div className="bg-surface-2 rounded-full h-1 overflow-hidden">
          <div className={`h-1 rounded-full ${confPct >= 70 ? 'bg-orange-500' : 'bg-surface-3'}`} style={{ width: `${confPct}%` }} />
        </div>
      </div>

      {/* Fato da IA */}
      {shortReasoning(pick.reasoning_1) && (
        <div className="mx-5 mb-3 px-3 py-2 bg-surface-1 border border-line rounded-md">
          <span className="text-[10px] text-ink-4 font-black uppercase">Fato · </span>
          <span className="text-[11px] text-ink-2 leading-relaxed line-clamp-2">{shortReasoning(pick.reasoning_1)}</span>
        </div>
      )}

      {/* Footer */}
      {pick.reasoning_1 && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!pick.result ? (e => {
          e.stopPropagation()
          if (userBankroll == null) { onConfigureBanca?.() ?? navigate('/banca') }
          else handleFollow(e as any)
        }) : undefined}
        betState={following ? 'loading' : followed ? 'done' : 'idle'}
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
          reasoning: [pick.reasoning_1, pick.reasoning_2, pick.reasoning_3].filter(Boolean).join('\n\n'),
        }}
      />
    )}
    </AnimatePresence>

    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={Number(pick.odd_combined)}
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
  match_date: string
  home_team: string; away_team: string
  home_team_id?: number; away_team_id?: number
  player_name?: string; team_name?: string
  market: string; line: string
  odd: number; bet_house?: string
  prob_real?: number; edge?: number
  reasoning?: string
  stake_units?: number
  result?: string | null
}

/*
 * Card de mercado (faltas e defesas).
 *
 * Reescrito pra ter a MESMA anatomia dos outros cinco cards: cabeçalho com
 * badge e horário, tira de números, times, confiança, raciocínio e rodapé com
 * Apostar / Entenda / Compartilhar. Antes era o mais divergente do conjunto
 * (padding e raio próprios, números em caixinhas separadas) e o único sem
 * nenhuma ação: dava pra ler o pick e não dava pra registrar.
 */
function MercadoCard({ p, tipo, banca, onBet }: {
  p: MercadoPick
  tipo: 'faltas' | 'goleiros'
  banca?: { bankroll_current: number; unit_value: number } | null
  onBet?: (p: MercadoPick, tipo: 'faltas' | 'goleiros') => void
}) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const prob = p.prob_real != null ? Number(p.prob_real) * 100 : null
  const edge = p.edge != null ? Number(p.edge) * 100 : null

  const kickoff = new Date(`${p.match_date}T12:00:00`)
    .toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })

  return (
    <>
    <div className={`pick-card ${PICK_TYPE_BORDER[tipo]}`}>

      {/* Cabeçalho */}
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <PickTypeBadge type={tipo} />
          <span className="flex items-center gap-1 text-[10px] text-ink-4 shrink-0">
            <Clock className="w-3 h-3" />
            {kickoff}
          </span>
          {p.bet_house && <span className="text-[10px] text-ink-4 truncate">{p.bet_house}</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {p.result ? <ResultBadge result={p.result} /> : <Badge tone="neutral">Pendente</Badge>}
          <FavoriteButton
            kind="market"
            refId={tipo}
            label={tipo === 'goleiros' ? 'Defesas de goleiro' : 'Faltas'}
            size="sm"
          />
        </div>
      </div>

      <PickStats
        items={[
          { label: 'Odd', value: Number(p.odd).toFixed(2), tone: 'accent' },
          { label: 'Probabilidade', value: prob != null ? `${prob.toFixed(0)}%` : '·' },
          {
            label: 'Margem',
            value: edge != null ? `${edge > 0 ? '+' : ''}${edge.toFixed(1)}%` : '·',
            tone: edge != null && edge > 0 ? 'accent' : 'default',
          },
        ]}
      />

      {/* Times e linha */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={p.home_team_id} name={p.home_team} size={20} />
          <span className="text-sm font-semibold text-ink-1 truncate">{p.home_team}</span>
          <span className="text-ink-4 text-xs shrink-0">x</span>
          <span className="text-sm font-semibold text-ink-1 truncate">{p.away_team}</span>
          <TeamLogo id={p.away_team_id} name={p.away_team} size={20} />
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3 flex-wrap">
          <span className="font-semibold text-ink-2">
            {tipo === 'goleiros' ? 'Defesas do goleiro' : 'Faltas no jogo'}
          </span>
          <span>·</span>
          <span className="text-ink-1 font-semibold">{p.line}</span>
          {tipo === 'goleiros' && p.team_name && (
            <><span>·</span><span>{p.team_name}</span></>
          )}
        </div>
      </div>

      {/* prob_real faz as vezes de confiança aqui: é o número que o modelo
          desses dois mercados produz. */}
      {p.prob_real != null && <PickConfidence confidence={Number(p.prob_real)} />}

      <PickReasoning text={p.reasoning} />

      {(p.reasoning || p.prob_real != null) && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!p.result && onBet ? () => onBet(p, tipo) : undefined}
        hasBanca={!!banca}
      />
    </div>

    <AnimatePresence>
    {showAnalysis && (
      <AnalysisModal
        onClose={() => setShowAnalysis(false)}
        data={{
          market: tipo === 'goleiros' ? 'Defesas do goleiro' : 'Faltas no jogo',
          line: p.line,
          odd: Number(p.odd),
          confidence: p.prob_real ?? null,
          probability: p.prob_real ?? null,
          ev: edge,
          reasoning: p.reasoning,
        }}
      />
    )}
    </AnimatePresence>
    </>
  )
}

function MercadoSecao({ tipo, titulo, cor, explicacao, picks, carregando, banca, onBet }: {
  tipo: 'faltas' | 'goleiros'
  titulo: string; cor: string; explicacao: string
  picks: MercadoPick[] | null; carregando: boolean
  banca?: { bankroll_current: number; unit_value: number } | null
  onBet?: (p: MercadoPick, tipo: 'faltas' | 'goleiros') => void
}) {
  return (
    <div>
      <SectionHeader color={cor} label={titulo} badge="VIP" />
      <p className="text-xs text-ink-3 leading-relaxed mb-4">{explicacao}</p>
      {carregando ? (
        <PickLoading />
      ) : !picks || picks.length === 0 ? (
        <div className="card">
          <EmptyState
            title={`Nenhum pick de ${titulo.toLowerCase()} ainda`}
            description={tipo === 'goleiros'
              ? 'Defesas é um mercado raro: aparece em menos de 1% dos jogos. Dia sem pick é o normal aqui.'
              : 'Aparece quando algum jogo do dia tiver margem suficiente no modelo.'}
            compact
          />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {picks.map(p => <MercadoCard key={p.id} p={p} tipo={tipo} banca={banca} onBet={onBet} />)}
        </div>
      )}
    </div>
  )
}

function SectionHeader({ color, label, badge }: { color: string; label: string; badge?: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className={`w-0.5 h-5 ${color} rounded-full block`} />
      <h2 className="text-sm font-bold text-ink-2">{label}</h2>
      {badge && <span className="badge-vip">{badge}</span>}
    </div>
  )
}

/* Carregamento de bloco desta tela: spinner do sistema dentro de um .card,
   pra lista em carregamento ocupar a mesma caixa da lista carregada. */
function PickLoading() {
  return (
    <div className="card p-16 flex items-center justify-center">
      <Spinner size="lg" />
    </div>
  )
}


interface PipelineStep { key: string; label: string; status: 'pending' | 'running' | 'done' | 'error' }

// Mostra o progresso da geração dos picks (quando o pipeline está rodando),
// com fallback para o card de "ainda não saíram" enquanto ele não começou.
function PipelineStatusCard() {
  const [status, setStatus] = useState<{ running: boolean; finished: boolean; steps: PipelineStep[] } | null>(null)

  useEffect(() => {
    let active = true
    const poll = () => {
      api.get('/admin/pipeline-status-public').then(r => { if (active) setStatus(r.data) }).catch(() => {})
    }
    poll()
    const t = setInterval(poll, 6000)
    return () => { active = false; clearInterval(t) }
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

// Constantes resultado / fonte
const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.',
}

interface NormalizedPick {
  id: number; pickType: string; matchDate: string
  homeName: string; awayName?: string; homeId?: number; awayId?: number
  market?: string; line?: string; odd?: number; betHouse?: string
  result?: string; profit?: number; isMonetary?: boolean
}

function normalizePickRow(row: any, pickType: string): NormalizedPick {
  const base = { id: row.id, pickType, matchDate: row.match_date, result: row.result || undefined }
  if (pickType === 'vip') return { ...base,
    homeName: row.home_team_name ?? row.home_team ?? '',
    awayName: row.away_team_name ?? row.away_team ?? '',
    homeId: row.home_team_id, awayId: row.away_team_id,
    market: row.market, line: row.line,
    odd: row.odd ? Number(row.odd) : undefined, betHouse: row.bet_house,
    profit: row.profit != null ? Number(row.profit) : undefined,
  }
  if (pickType === 'free') return { ...base,
    homeName: row.home_team ?? row.home_team_name ?? '',
    awayName: row.away_team ?? row.away_team_name ?? '',
    homeId: row.home_team_id, awayId: row.away_team_id,
    market: row.market, line: row.line,
    odd: row.odd ? Number(row.odd) : undefined, betHouse: row.bet_house,
    profit: row.profit != null ? Number(row.profit) : undefined,
  }
  if (pickType === 'multipla') {
    let legs: any[] = []
    try { legs = typeof row.legs === 'string' ? JSON.parse(row.legs) : (row.legs ?? []) } catch { legs = [] }
    // legs_count vem do endpoint recent-results (backend apaga legs antes de retornar)
    const legsCount = row.legs_count ?? legs.length
    const f = legs[0]
    // usa home_team_name pré-normalizado pelo backend quando legs não está disponível
    const firstTeam = row.home_team_name || (f && (f.home ?? f.home_team)) || ''
    const label = firstTeam
      ? (legsCount > 1 ? `${firstTeam} +${legsCount - 1}` : firstTeam)
      : 'Múltipla'
    return { ...base,
      homeName: label, homeId: f?.home_team_id,
      market: row.market ?? (legsCount > 0 ? `Múltipla · ${legsCount} seleções` : 'Múltipla'),
      odd: row.total_odd ? Number(row.total_odd) : row.odd ? Number(row.odd) : undefined,
      profit: row.profit != null ? Number(row.profit) : undefined,
    }
  }
  if (pickType === 'alavancagem') {
    const odd   = row.odd_combined ? Number(row.odd_combined) : row.odd ? Number(row.odd) : undefined
    const bk    = Number(row.bankroll_before ?? row.stake ?? 50)
    // Calcula profit monetário a partir do bankroll real (não do campo profit que pode estar em unidades)
    const monetaryProfit = row.result === 'GREEN' && odd ? bk * (odd - 1)
      : row.result === 'RED' ? -bk
      : row.profit != null ? Number(row.profit)
      : undefined
    return { ...base,
      homeName: row.home_team_1 ?? row.home_team_name ?? '',
      awayName: row.away_team_1 ?? row.away_team_name ?? '',
      homeId: row.home_team_id_1 ?? row.home_team_id,
      awayId: row.away_team_id_1 ?? row.away_team_id,
      market: row.market_1 ?? row.market,
      line: row.line_1 ?? row.line,
      odd,
      betHouse: row.bet_house_1 ?? row.bet_house,
      isMonetary: true, profit: monetaryProfit,
    }
  }
  // já normalizado (recent-results / mixed)
  return { ...base,
    homeName: row.home_team_name ?? '',
    awayName: row.away_team_name ?? '',
    homeId: row.home_team_id, awayId: row.away_team_id,
    market: row.market, line: row.line,
    odd: row.odd ? Number(row.odd) : undefined, betHouse: row.bet_house,
    isMonetary: (row.pick_type ?? pickType) === 'alavancagem',
    profit: row.profit != null ? Number(row.profit) : undefined,
  }
}

// Tabela padronizada de picks
function PicksTable({
  rows, pickType, showSource = false, onOpen, footerAction,
}: {
  rows: any[]; pickType: string; showSource?: boolean
  onOpen: (id: number, type: string) => void
  footerAction?: { label: string; onClick: () => void }
}) {
  if (!rows.length) return null
  return (
    <div className="card overflow-hidden p-0">
      <div className="divide-y divide-line/60">
        {rows.map(row => {
          const pt = showSource ? (row.pick_type ?? pickType) : pickType
          const p  = normalizePickRow(row, pt)
          return (
            <button
              key={`${pt}-${p.id}`}
              onClick={() => onOpen(p.id, pt)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-2/40 transition-colors text-left"
            >
              <div className="w-12 shrink-0 text-center">
                <span className="text-xs text-ink-3">
                  {new Date(p.matchDate).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                </span>
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                  {showSource && (
                    <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[pt] ?? ''}`}>
                      {SOURCE_LBL[pt] ?? pt}
                    </span>
                  )}
                  <TeamLogo id={p.homeId} name={p.homeName} size={16} />
                  <span className="text-sm font-semibold text-ink-1 truncate">{p.homeName}</span>
                  {p.awayName && (
                    <>
                      <span className="text-ink-4 text-xs shrink-0">vs</span>
                      <span className="text-sm font-semibold text-ink-1 truncate">{p.awayName}</span>
                      <TeamLogo id={p.awayId} name={p.awayName} size={16} />
                    </>
                  )}
                </div>
                <p className="text-xs text-ink-3 truncate">
                  {p.market}{p.line ? <> · <span className="text-ink-2">{p.line}</span></> : ''}
                  {p.odd ? ` · Odd ${p.odd.toFixed(2)}` : ''}
                  {p.betHouse ? ` · ${p.betHouse}` : ''}
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {p.result ? (() => {
                  const rs = getResultStyle(p.result)
                  return (
                    <span className={`text-xs font-black px-2 py-0.5 rounded-lg border ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-ink-3'}`}>
                      {rs ? rs.label : p.result}
                    </span>
                  )
                })() : (
                  <span className="text-xs font-black px-2 py-0.5 rounded-lg text-yellow-400 bg-yellow-400/10 border border-yellow-400/20">
                    Pendente
                  </span>
                )}
                {p.profit != null ? (
                  <span className={`font-mono text-sm font-black w-14 text-right ${p.profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                    {p.profit >= 0 ? '+' : ''}{p.isMonetary ? 'R$' : ''}{Math.abs(p.profit).toFixed(2)}{!p.isMonetary ? 'u' : ''}
                  </span>
                ) : (
                  <span className="text-sm font-black w-14 text-right text-ink-4"></span>
                )}
              </div>
            </button>
          )
        })}
      </div>
      {footerAction && (
        <div className="px-4 py-3 border-t border-line">
          <button onClick={footerAction.onClick}
            className="w-full text-center text-xs text-green-500 hover:text-green-400 transition-colors font-semibold">
            {footerAction.label}
          </button>
        </div>
      )}
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
      <div className="grid gap-4 md:grid-cols-2 select-none pointer-events-none" style={{ filter: 'blur(5px)', opacity: 0.35 }}>
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



// Dashboard
export default function Picks() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, isVip, isAdmin, daysUntilExpiry } = useAuth()
  const canSeeVip = isVip || isAdmin
  const { hasNew, markSeen, liveCount, hasLive, clearLive } = useNotifications()

  const [tab, setTab]               = useState<Tab>('hoje')

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
    const hash = location.hash.replace('#', '') as Tab
    const valid: Tab[] = ['hoje','pick_seguro','vip','multiplas','alavancagem','mercados','aovivo','chat']
    setTab(valid.includes(hash) ? hash : 'hoje')
  }, [location.hash])

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedPickType, setSelectedPickType] = useState<string>('vip')

  const openDetail = (id: number, pickType = 'vip') => {
    setSelectedId(id)
    setSelectedPickType(pickType)
  }

  // Dados de hoje (free + VIP rápido)
  const [today, setToday]         = useState<any>(null)
  const [todayLoading, setTodayLoading] = useState(true)
  const [todayError, setTodayError]     = useState(false)
  const [liveFixtures, setLiveFixtures] = useState<Set<number>>(new Set())

  // Alavancagem
  const [alavFilters,  setAlavFilters]  = useState<AlavFilters>(defaultAlavFilters)
  const [alavancagem,  setAlavancagem]  = useState<any[]>([])
  // null = ainda nao buscou (a aba carrega sob demanda, ver o efeito por aba)
  const [faltas,    setFaltas]    = useState<MercadoPick[] | null>(null)
  const [goleiros,  setGoleiros]  = useState<MercadoPick[] | null>(null)
  const [mercadosLoading, setMercadosLoading] = useState(false)
  // Busca, categoria, ordem e estado da aba Mercados. Filtragem é local: a aba
  // já baixa os dois conjuntos inteiros, são poucas dezenas de picks por dia.
  const [mercadoFiltro, setMercadoFiltro] = useState<MercadoFiltro>(FILTRO_INICIAL)
  const { isFavorite, favorites } = useFavorites()

  /*
   * Registrar aposta de mercado (faltas e defesas).
   *
   * Reusa o ApostaModal dos outros tipos em vez de um fluxo proprio: a
   * confirmacao de odd real e casa de aposta e a mesma, e duas telas de
   * confirmacao diferentes pro mesmo ato so confundiriam.
   */
  const [mercadoBet, setMercadoBet] = useState<{ p: MercadoPick; tipo: 'faltas' | 'goleiros' } | null>(null)
  const [mercadoBetLoading, setMercadoBetLoading] = useState(false)
  const [mercadoBetError, setMercadoBetError] = useState<string | null>(null)

  const handleMercadoBet = useCallback((p: MercadoPick, tipo: 'faltas' | 'goleiros') => {
    setMercadoBetError(null)
    setMercadoBet({ p, tipo })
  }, [])

  const confirmMercadoBet = async (actualOdd: number, betHouse: string, stakeUnits: number) => {
    if (!mercadoBet) return
    setMercadoBetLoading(true)
    setMercadoBetError(null)
    try {
      await api.post('/banca/follow', {
        pick_id: mercadoBet.p.id,
        pick_type: mercadoBet.tipo,
        stake_units: stakeUnits,
        actual_odd: actualOdd,
        bet_house: betHouse,
      })
      setMercadoBet(null)
    } catch (err: any) {
      setMercadoBetError(err?.response?.data?.detail ?? 'Erro ao registrar aposta. Tente novamente.')
    } finally {
      setMercadoBetLoading(false)
    }
  }
  // Um pick de mercado conta como favorito se o time da casa, o visitante ou
  // o próprio tipo de mercado estiver favoritado.
  const mercadoEhFavorito = useCallback((p: MercadoPick & { tipo?: string }) => (
    (p.home_team_id != null && isFavorite('team', p.home_team_id)) ||
    (p.away_team_id != null && isFavorite('team', p.away_team_id))
  ), [isFavorite])
  const temFavoritos = favorites.some(f => f.kind === 'team')
  const faltasFiltradas   = useMemo(() => aplicarFiltro(faltas ?? [], mercadoFiltro, mercadoEhFavorito), [faltas, mercadoFiltro, mercadoEhFavorito])
  const goleirosFiltrados = useMemo(() => aplicarFiltro(goleiros ?? [], mercadoFiltro, mercadoEhFavorito), [goleiros, mercadoFiltro, mercadoEhFavorito])
  const [alavLoading,  setAlavLoading]  = useState(false)
  const [alavLoaded,   setAlavLoaded]   = useState(false)
  const [alavError,    setAlavError]    = useState(false)
  const [alavHasMore,    setAlavHasMore]    = useState(false)
  const [alavLoadingMore, setAlavLoadingMore] = useState(false)
  const [userAlavSerie, setUserAlavSerie] = useState<{ configured: boolean; current_bankroll: number; initial_bankroll: number } | null>(null)
  const [alavInitInput, setAlavInitInput] = useState('')
  const [alavInitSaving, setAlavInitSaving] = useState(false)
  const [alavInitError, setAlavInitError] = useState('')
  const [bancaSummary, setBancaSummary] = useState<{ has_banca: boolean; bankroll_current: number; unit_value: number } | null>(null)
  const [showBancaModal, setShowBancaModal] = useState(false)

  const [quickStats, setQuickStats] = useState<any>(null)
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
  }, [])

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

  useEffect(() => {
    if (tab === 'alavancagem'  && canSeeVip && !alavLoaded) doFetchAlavancagem(defaultAlavFilters)
    // Busca os dois em paralelo: sao independentes, e serializar somaria a
    // latencia de duas chamadas antes de pintar qualquer coisa na tela.
    if (tab === 'mercados' && canSeeVip && faltas === null && !mercadosLoading) {
      setMercadosLoading(true)
      Promise.all([
        api.get('/suggestions/faltas',   { params: { limit: 50 } }).then(r => r.data?.items ?? []).catch(() => []),
        api.get('/suggestions/goleiros', { params: { limit: 50 } }).then(r => r.data?.items ?? []).catch(() => []),
      ])
        .then(([f, g]) => { setFaltas(f); setGoleiros(g) })
        .finally(() => setMercadosLoading(false))
    }
  }, [tab, canSeeVip])


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
      width="wide"
      bar={{
        title: 'Picks',
        sub: tab === 'hoje' ? (
          <span className="flex items-center gap-0.5">
            <button
              onClick={() => setSelectedOffset(o => o - 1)}
              aria-label="Dia anterior"
              className="text-ink-3 hover:text-ink-2 transition-colors p-0.5 -ml-0.5"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="text-ink-2 capitalize font-medium">
              {selectedOffset === 0 ? 'Hoje' : todayLabel}
            </span>
            <button
              onClick={() => setSelectedOffset(o => Math.min(0, o + 1))}
              disabled={selectedOffset >= 0}
              aria-label="Próximo dia"
              className="text-ink-3 hover:text-ink-2 disabled:opacity-20 transition-colors p-0.5"
            >
              <ChevronRight className="w-3.5 h-3.5" />
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
            {quickStats && (
              <span className="hidden sm:flex items-center gap-2 text-xs">
                <span className="text-ink-4">Win rate geral</span>
                <span className={`font-mono font-bold text-sm ${(quickStats.win_rate ?? 0) >= 55 ? 'text-accent' : 'text-ink-2'}`}>
                  {quickStats.win_rate ?? 0}%
                </span>
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <LiveDot />
              <span className="text-accent text-xs font-bold">AO VIVO</span>
            </span>
          </>
        ),
      }}
    >
      <AnimatePresence>
      {mercadoBet && (
        <ApostaModal
          pickOdd={Number(mercadoBet.p.odd)}
          suggestedUnits={mercadoBet.p.stake_units ?? 1}
          suggestedHouse={mercadoBet.p.bet_house}
          onConfirm={confirmMercadoBet}
          onCancel={() => setMercadoBet(null)}
          loading={mercadoBetLoading}
          error={mercadoBetError}
        />
      )}
      </AnimatePresence>

      <AnimatePresence>
      {selectedId && <SuggestionDetail id={selectedId} pickType={selectedPickType} onClose={() => setSelectedId(null)} banca={bancaSummary?.has_banca ? bancaSummary : null} />}
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

        {hasLive && tab !== 'aovivo' && (
          <div className="mb-4 flex items-center justify-between bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse shrink-0" />
              <span className="text-red-300 text-sm font-semibold">
                {liveCount > 1 ? `${liveCount} jogos que você apostou estão ao vivo!` : 'Um jogo que você apostou está ao vivo!'}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => { clearLive(); setTab('aovivo') }}
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
          setTab={(t) => { if (t === 'aovivo') clearLive(); setTab(t) }}
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
            {todayLoading ? <PickLoading /> : todayError ? (
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

              {/* Stats da IA este mês */}
              {quickStats && (
                <div>
                  <p className="text-[10px] text-ink-4 uppercase font-semibold mb-2">Performance da IA · Geral</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Picks', value: String(quickStats.total ?? 0), color: 'text-ink-1' },
                      { label: 'Green',  value: String(quickStats.greens ?? 0), color: 'text-green-500' },
                      { label: 'Red',    value: String(quickStats.reds ?? 0),   color: 'text-red-400' },
                      { label: 'Win %',  value: `${quickStats.win_rate ?? 0}%`, color: (quickStats.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-ink-2' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="bg-surface-1 border border-line rounded-md p-3 text-center">
                        <div className={`font-mono text-xl font-black ${color}`}>{value}</div>
                        <div className="text-[10px] text-ink-3 uppercase mt-1">{label}</div>
                      </div>
                    ))}
                  </div>
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
                  <PickSeguroCard dica={today.dica_do_dia} compact onClick={() => openDetail(today.dica_do_dia.id, 'free')} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(today.dica_do_dia.fixture_id)} />
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
                        <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid gap-4 md:grid-cols-2">
                          {vips.slice(0, 4).map((s: any) => (
                            <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(s.fixture_id)} />
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
                      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid gap-4 md:grid-cols-2">
                        {multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isMultiplaLive(m)} />)}
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
                        onClick={() => openDetail(today.alavancagem.id, 'alavancagem')}
                        userBankroll={userAlavSerie?.configured ? userAlavSerie.current_bankroll : undefined}
                        onConfigureBanca={() => setTab('alavancagem')}
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
                  <div className="grid gap-4 md:grid-cols-2">
                    {(today?.faltas ?? []).map((p: MercadoPick) => (
                      <MercadoCard key={`f-${p.id}`} p={p} tipo="faltas" />
                    ))}
                    {(today?.goleiros ?? []).map((p: MercadoPick) => (
                      <MercadoCard key={`g-${p.id}`} p={p} tipo="goleiros" />
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
                {today?.dica_do_dia ? <PickSeguroCard dica={today.dica_do_dia} onClick={() => openDetail(today.dica_do_dia.id, 'free')} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(today.dica_do_dia.fixture_id)} /> : <PickSeguroEmpty />}
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
                    {filterGroups.length > 0 && <FilterPanel accent="yellow" groups={filterGroups} />}
                    {filteredVips.length > 0 ? (
                      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid gap-4 md:grid-cols-2">
                        {filteredVips.map((s: any) => (
                          <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isFixtureLive(s.fixture_id)} />
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
                    {today.multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} banca={bancaSummary?.has_banca ? bancaSummary : null} isLive={isMultiplaLive(m)} />)}
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
                {/* Config banca alavancagem */}
                <div className="card p-5 border-orange-500/20">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="font-display text-sm font-bold text-orange-400">Banca Alavancagem</p>
                      <p className="text-xs text-ink-3 mt-0.5">Separada da sua banca principal. Reinveste a cada GREEN, reseta no RED</p>
                    </div>
                    {userAlavSerie?.configured && (
                      <div className="font-mono text-right">
                        <div className="text-2xl font-black text-orange-400">R${userAlavSerie.current_bankroll.toFixed(2)}</div>
                        <div className="text-xs text-ink-4">início: R${userAlavSerie.initial_bankroll.toFixed(2)}</div>
                      </div>
                    )}
                  </div>
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
                        <button onClick={() => setAlavInitInput('')} className="px-3 py-2 rounded-md border border-line-strong text-ink-3 text-sm hover:text-ink-1 transition-colors">✕</button>
                      )}
                    </div>
                  ) : (
                    <button
                      onClick={() => setAlavInitInput(String(userAlavSerie.initial_bankroll))}
                      className="text-xs text-ink-4 hover:text-orange-400 transition-colors underline"
                    >
                      Alterar valor inicial
                    </button>
                  )}
                  {alavInitError && (
                    <p className="text-xs text-red-400 mt-2">{alavInitError}</p>
                  )}
                </div>

                {/* Pick de hoje */}
                {todayLoading ? <PickLoading /> : (
                  <div>
                    <SectionHeader color="bg-orange-400" label={`Pick do Dia · ${todayDateStr}`} />
                    {today?.alavancagem ? (
                      <AlavancagemCard
                        pick={today.alavancagem}
                        onClick={() => openDetail(today.alavancagem.id, 'alavancagem')}
                        userBankroll={userAlavSerie?.configured ? userAlavSerie.current_bankroll : undefined}
                        onConfigureBanca={() => setTab('alavancagem')}
                        isLive={isAlavLive(today.alavancagem)}
                      />
                    ) : (
                      <div className="card p-8 text-center border-dashed border-orange-500/20">
                        <p className="text-ink-3 text-sm font-semibold">Pick de alavancagem não gerado para hoje.</p>
                        <p className="text-ink-4 text-xs mt-1">Publicado diariamente até às 12h.</p>
                      </div>
                    )}
                  </div>
                )}

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
                              onClick={() => openDetail(pick.id, 'alavancagem')}
                              className={`flex-1 mb-2 rounded-md border px-3 py-2.5 cursor-pointer hover:border-orange-500/40 transition-colors ${
                                !res ? 'border-orange-500/40 bg-orange-500/5' : 'border-line bg-surface-1'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1 flex-wrap mb-0.5">
                                    <TeamLogo id={pick.home_team_id_1} name={pick.home_team_1 ?? ''} size={14} />
                                    <span className="text-xs font-bold text-ink-1 truncate">{pick.home_team_1}</span>
                                    <span className="text-ink-4 text-[10px]">vs</span>
                                    <TeamLogo id={pick.away_team_id_1} name={pick.away_team_1 ?? ''} size={14} />
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
                <MercadosControls
                  filtro={mercadoFiltro}
                  onChange={setMercadoFiltro}
                  totalFaltas={faltas?.length ?? 0}
                  totalGoleiros={goleiros?.length ?? 0}
                  visiveis={faltasFiltradas.length + goleirosFiltrados.length}
                  temFavoritos={temFavoritos}
                />

                {/* Nada bateu o filtro. Sem isso as duas seções apareciam com o
                    vazio genérico de "nenhum pick ainda", que é outra coisa:
                    ali não existe pick, aqui existe e o filtro escondeu. */}
                {faltasFiltradas.length === 0 && goleirosFiltrados.length === 0 && !mercadosLoading && (faltas?.length || goleiros?.length) ? (
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
                        carregando={mercadosLoading}
                        banca={bancaSummary?.has_banca ? bancaSummary : null}
                        onBet={handleMercadoBet}
                      />
                    )}
                    {mercadoFiltro.categoria !== 'faltas' && (
                      <MercadoSecao
                        tipo="goleiros"
                        titulo="Defesas de goleiro"
                        cor="bg-sky-400"
                        explicacao="Quantas defesas um goleiro específico faz no jogo. O sinal principal é o volume de chutes no alvo que o adversário costuma produzir."
                        picks={goleiros === null ? null : goleirosFiltrados}
                        carregando={mercadosLoading}
                        banca={bancaSummary?.has_banca ? bancaSummary : null}
                        onBet={handleMercadoBet}
                      />
                    )}
                  </>
                )}
              </>
            )}
          </motion.div>
        )}
        </AnimatePresence>
        <div className={tab !== 'aovivo' ? 'hidden' : ''}>
          <LivePicks isActive={tab === 'aovivo'} unitValue={bancaSummary?.unit_value} />
        </div>



    </PageShell>
  )
}

