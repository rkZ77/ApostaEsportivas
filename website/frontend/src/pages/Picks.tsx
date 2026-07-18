import { useEffect, useState, useCallback } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import SuggestionCard from '../components/SuggestionCard'
import ApostaModal from '../components/ApostaModal'
import SuggestionDetail from '../components/SuggestionDetail'
import Navbar from '../components/Navbar'
import Avatar from '../components/Avatar'
import Footer from '../components/Footer'
import LivePicks from '../components/LivePicks'
import { UserCircle, Crown, Rocket, Wallet, Clock, ChevronLeft, ChevronRight, BrainCircuit, Share2, Check as CheckIcon, Loader2 } from 'lucide-react'
import { calcFreeStake, calcMultiplaStake, calcProfitUnits } from '../utils/stakeUtils'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { translateMarket, translateLine, translateTeamName } from '../utils/marketTranslate'
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
type Tab = 'hoje' | 'pick_seguro' | 'vip' | 'multiplas' | 'alavancagem' | 'aovivo' | 'chat'

const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

interface VipFilters {
  date_from: string; date_to: string; market_type: string
  resultado: string; min_conf: string; bet_house: string; order_by: string
}
const defaultVipFilters: VipFilters = {
  date_from: TODAY, date_to: TODAY, market_type: 'all',
  resultado: 'all', min_conf: '0', bet_house: 'all', order_by: 'confidence',
}

const THIRTY_AGO = (() => {
  const d = new Date(); d.setDate(d.getDate() - 30)
  return d.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
})()

interface PickFreeFilters { date_from: string; date_to: string; resultado: string }
const defaultPickFreeFilters: PickFreeFilters = { date_from: THIRTY_AGO, date_to: TODAY, resultado: 'all' }

interface MFilters { date_from: string; date_to: string; resultado: string; order_by: string }
const defaultMFilters: MFilters = { date_from: THIRTY_AGO, date_to: TODAY, resultado: 'all', order_by: 'match_date' }

interface AlavFilters { date_from: string; date_to: string; resultado: string }
const defaultAlavFilters: AlavFilters = { date_from: '', date_to: TODAY, resultado: 'all' }

const MARKET_LABELS: Record<string, string> = {
  all: 'Todos mercados', goals: 'Gols', corners: 'Escanteios',
  cards: 'Cartões', result: '1X2', btts: 'Ambas marcam',
}
const RESULT_LABELS: Record<string, string> = {
  all: 'Todos', pending: 'Pendente', GREEN: 'Green',
  RED: 'Red', PUSH: 'Push', 'HALF-WIN': '½ Win', 'HALF-LOSS': '½ Loss',
}

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
      {/* fade direita indicando scroll */}
      <div className="pointer-events-none absolute right-0 top-0 h-full w-10 bg-gradient-to-l from-black to-transparent z-10" />
      <div className="flex border-b border-zinc-800 px-4 overflow-x-auto scrollbar-none">
        {tabs.map(t => {
          const count = counts?.[t.key]
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 sm:px-4 py-3 text-xs sm:text-sm font-semibold border-b-2 transition-colors mr-1 whitespace-nowrap flex-shrink-0 ${
                tab === t.key
                  ? 'border-green-500 text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t.label}
              {t.badge && (
                <span className={`ml-1.5 text-[10px] border px-1.5 py-0.5 rounded font-bold uppercase tracking-wide ${t.badgeCls ?? 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20'}`}>
                  {t.badge}
                </span>
              )}
              {t.premiumOnly && canSeeVip && (
                <span className="ml-1.5 text-[10px] bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 px-1.5 py-0.5 rounded font-bold uppercase tracking-wide">
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
            </button>
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

  const planBadgeColor = isAdmin ? 'text-purple-400 bg-purple-400/10 border-purple-400/20'
    : isTrial ? 'text-amber-400 bg-amber-400/10 border-amber-400/20'
    : isVip ? 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
    : 'text-zinc-400 bg-zinc-800 border-zinc-700'
  const planLabel = isAdmin ? 'ADMIN' : isTrial ? 'TRIAL' : isVip ? 'VIP' : 'FREE'

  const planStatusColor = isAdmin ? 'text-purple-400'
    : isTrial ? 'text-amber-400'
    : isVip ? 'text-yellow-400'
    : 'text-zinc-400'

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
          <h2 className="text-white font-black text-lg leading-tight">Olá, {firstName}!</h2>
          <span className={`text-xs font-black px-2.5 py-0.5 rounded-full border ${planBadgeColor}`}>{planLabel}</span>
        </div>
        <p className="text-zinc-500 text-xs mt-0.5 truncate">{user.email}</p>

        {/* Assinatura inline */}
        <div className="mt-2 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-500 text-xs">Status atual:</span>
            <span className={`text-xs font-black ${planStatusColor}`}>{planLabel}</span>
          </div>
          {countdown && (
            <span className="text-zinc-400 text-xs">
              Expira em <span className="font-bold text-white tabular-nums">{countdown}</span>
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
      color: 'text-zinc-300',
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
      color: streakType === 'green' ? 'text-green-500' : streakType === 'red' ? 'text-red-400' : 'text-zinc-500',
      iconColor: streakType === 'green' ? 'text-orange-400' : 'text-zinc-600',
      sub: streakType === 'green' ? 'Greens seguidos' : streakType === 'red' ? 'Reds seguidos' : 'Sem sequência',
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      {items.map(({ icon, label, value, color, iconColor, sub }) => (
        <div key={label} className="card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-zinc-600 font-semibold uppercase tracking-wider">{label}</span>
            <span className={iconColor}>{icon}</span>
          </div>
          <div className={`text-2xl font-black ${color}`}>{value}</div>
          <div className="text-xs text-zinc-700 mt-0.5">{sub}</div>
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

function PickSeguroCard({ dica, compact = false, onClick, banca }: { dica: any; compact?: boolean; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null }) {
  const navigate = useNavigate()
  const pct = Math.round((dica.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState(dica.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalOdd, setModalOdd] = useState(Number(dica.odd))
  const [apiError, setApiError] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()
  // Prioridade: suggested_stake_units do backend → calcFreeStake fallback (max 2%)
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
    <div
      className={`relative overflow-hidden bg-zinc-950 border rounded-2xl transition-all duration-200 group ${isCopa ? 'border-yellow-500/20' : 'border-green-500/20'} ${onClick ? (isCopa ? 'hover:border-yellow-500/40 cursor-pointer' : 'hover:border-green-500/40 cursor-pointer') : ''}`}
      onClick={onClick}
    >
      <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent to-transparent ${isCopa ? 'via-yellow-500' : 'via-green-500'}`} />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-black ${isCopa ? 'text-yellow-500' : 'text-green-400'}`}>Pick do Dia</span>
          <span className="badge-free">FREE</span>
          {dica.league_name && (
            <div className="flex items-center gap-1">
              <LeagueLogo id={dica.league_id} name={dica.league_name} />
              <span className="text-[10px] text-zinc-600 truncate max-w-[90px]">{dica.league_name}</span>
            </div>
          )}
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label} {resultStyle.emoji}
          </span>
        ) : (
          <span className="text-[10px] text-zinc-500 border border-zinc-800 px-2 py-1 rounded-lg">Pendente</span>
        )}
      </div>

      {/* Hero: Odd | Stake | Retorno */}
      <div className="flex items-stretch divide-x divide-zinc-800/60 border-b border-zinc-800/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-zinc-500 mb-0.5">Odd</div>
          <div className="text-3xl font-black text-green-400">{Number(dica.odd).toFixed(2)}</div>
          <div className="text-[10px] text-zinc-600 mt-0.5">{dica.bet_house}</div>
        </div>
        {stakeSuggestion && !dica.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-green-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-zinc-600">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-white">+{((Number(dica.odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
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
                  <div className="text-[10px] text-zinc-500 mb-0.5">Lucro</div>
                  <div className={`text-xl font-black ${color}`}>
                    {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  </div>
                  {u > 1 && <div className="text-[10px] text-zinc-600">({u}u)</div>}
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-zinc-500 mb-0.5">Em reais</div>
                  {profitR != null ? (
                    <div className={`text-xl font-black ${color}`}>
                      {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                    </div>
                  ) : (
                    <div className="text-xl font-black text-zinc-600">-</div>
                  )}
                </div>
              </>
            )
          })()
        ) : (
          <div className="flex-1 px-4 py-3 text-center">
            {dica.ev != null ? (
              <>
                <div className="text-[10px] text-zinc-500 mb-0.5">EV</div>
                <div className={`text-xl font-black ${Number(dica.ev) >= 0 ? 'text-green-400' : 'text-orange-400'}`}>
                  {Number(dica.ev) >= 0 ? '+' : ''}{(Number(dica.ev) * 100).toFixed(1)}%
                </div>
              </>
            ) : (
              <>
                <div className="text-[10px] text-zinc-500 mb-0.5">Confiança</div>
                <div className={`text-xl font-black ${pct >= 75 ? 'text-green-400' : 'text-zinc-300'}`}>{pct}%</div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Times + mercado */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={dica.home_team_id} name={dica.home_team ?? ''} size={22} />
          <span className="text-sm font-bold text-white truncate">{dica.home_team}</span>
          <span className="text-zinc-600 text-xs shrink-0">vs</span>
          <span className="text-sm font-bold text-white truncate">{dica.away_team}</span>
          <TeamLogo id={dica.away_team_id} name={dica.away_team ?? ''} size={22} />
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="font-semibold text-zinc-300">{dica.market}</span>
          {dica.line && <><span>·</span><span>{dica.line}</span></>}
        </div>
      </div>

      {/* Confiança bar */}
      <div className="px-5 pb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-zinc-600">Confiança</span>
          <span className={pct >= 75 ? 'text-green-400 font-bold' : 'text-zinc-500'}>{pct}%</span>
        </div>
        <div className="bg-zinc-800 rounded-full h-1 overflow-hidden">
          <div
            className={`h-1 rounded-full ${pct >= 75 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-zinc-500'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Reasoning snippet */}
      {fato && (
        <div className="mx-5 mb-3 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-xl">
          <span className="text-[10px] text-zinc-600 font-black uppercase tracking-wider">Fato · </span>
          <span className="text-[11px] text-zinc-400 leading-relaxed line-clamp-2">{fato}</span>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-5 py-3 border-t border-zinc-800/60">
        {!dica.result ? (
          <button
            onClick={banca ? handleFollow : () => navigate('/banca')}
            disabled={following || followed}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : banca
                ? 'border-zinc-700 text-zinc-400 hover:border-green-500/50 hover:text-green-400 hover:bg-green-500/5'
                : 'border-yellow-500/30 text-yellow-400 hover:border-yellow-500/60 hover:bg-yellow-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Registrado' : banca ? 'Apostar' : 'Configurar banca'}
          </button>
        ) : <span />}
        <div className="flex items-center gap-3 ml-auto">
          <button
            onClick={handleShare}
            disabled={sharing}
            className="flex items-center gap-1.5 text-xs font-bold text-green-400 bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60"
            title="Compartilhar pick"
          >
            {sharing
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /><span>Gerando...</span></>
              : shared
              ? <><CheckIcon className="w-3.5 h-3.5 text-green-400" /><span className="text-green-400">Compartilhado</span></>
              : <><Share2 className="w-3.5 h-3.5" /><span>Compartilhar</span></>
            }
          </button>
          {onClick && (
            <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">
              Ver detalhes
            </span>
          )}
        </div>
      </div>
    </div>
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
    {showSuccess && (
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg whitespace-nowrap">
        Pick registrado com sucesso!
      </div>
    )}
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
      <p className="text-zinc-500 text-sm font-semibold mb-1">Pick do Dia indisponível</p>
      <p className="text-zinc-600 text-xs">{msg}</p>
      {hour < 12 && <p className="text-zinc-700 text-xs mt-2">Publicado todos os dias até às 12h</p>}
    </div>
  )
}

// Múltipla card
function MultiplaCard({ m, onClick, banca }: { m: any; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null }) {
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
  // Prioridade: suggested_stake_units do backend → calcMultiplaStake fallback (max 2.5%)
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
    <div
      className="relative overflow-hidden bg-zinc-950 border border-zinc-800 hover:border-blue-500/30 rounded-2xl cursor-pointer transition-all duration-200 group"
      onClick={onClick}
    >
      {/* Accent bar */}
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-blue-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2">
          <span className="text-xs font-black text-blue-400">Múltipla</span>
          <span className="badge-vip">VIP</span>
          <span className="text-[10px] text-zinc-600">
            {new Date(m.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}
            {' · '}{legs.length} seleções
          </span>
          {legs.length >= 2 && legs[0]?.home && legs[1]?.home && (
            <span className="text-[9px] text-zinc-500 truncate max-w-[140px]">
              {legs[0].home} · {legs[1].home}
            </span>
          )}
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label} {resultStyle.emoji}
          </span>
        ) : (
          <span className="text-[10px] text-zinc-500 border border-zinc-800 px-2 py-1 rounded-lg">Pendente</span>
        )}
      </div>

      {/* Odd hero + retorno */}
      <div className="flex items-center gap-0 divide-x divide-zinc-800/60 border-b border-zinc-800/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-zinc-500 mb-0.5">Odd combinada</div>
          <div className="text-3xl font-black text-green-400">{Number(m.total_odd).toFixed(2)}</div>
        </div>
        {stakeSuggestion && !m.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-blue-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-zinc-600">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-white">+{((Number(m.total_odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
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
                  <div className="text-[10px] text-zinc-500 mb-0.5">Lucro</div>
                  <div className={`text-xl font-black ${color}`}>
                    {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  </div>
                  {u > 1 && <div className="text-[10px] text-zinc-600">({u}u)</div>}
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-zinc-500 mb-0.5">Em reais</div>
                  {profitR != null ? (
                    <div className={`text-xl font-black ${color}`}>
                      {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                    </div>
                  ) : (
                    <div className="text-xl font-black text-zinc-600">-</div>
                  )}
                </div>
              </>
            )
          })()
        ) : (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-zinc-500 mb-0.5">Confiança</div>
            <div className={`text-2xl font-black ${pct >= 70 ? 'text-green-400' : 'text-zinc-300'}`}>{pct}%</div>
          </div>
        )}
      </div>

      {/* Legs */}
      <div className="px-5 py-3 space-y-2">
        {legs.map((leg: any, i: number) => {
          // Se overall GREEN → todas GREEN. Se overall RED → legs sem GREEN explícito são RED
          const lr = (
            m.result === 'GREEN' ? 'GREEN' :
            m.result === 'RED'   ? (leg.result === 'GREEN' ? 'GREEN' : 'RED') :
            leg.result ?? undefined
          ) as 'GREEN' | 'RED' | undefined
          const circleClass = lr === 'GREEN'
            ? 'bg-green-500/20 text-green-400'
            : lr === 'RED'
            ? 'bg-red-500/20 text-red-400'
            : 'bg-blue-500/10 text-blue-400'
          const rowClass = lr === 'GREEN'
            ? 'bg-green-500/5 rounded-lg px-2 -mx-2'
            : lr === 'RED'
            ? 'bg-red-500/5 rounded-lg px-2 -mx-2'
            : ''
          return (
          <div key={i} className={`space-y-1 ${rowClass}`}>
            <div className="flex items-center gap-2">
              <span className={`w-5 h-5 flex items-center justify-center rounded-full ${circleClass} text-[10px] font-black shrink-0`}>
                {lr === 'GREEN' ? '✓' : lr === 'RED' ? '✗' : i + 1}
              </span>
              <div className="flex items-center gap-1.5 flex-1 min-w-0">
                <TeamLogo id={leg.home_team_id} name={leg.home ?? leg.home_team ?? ''} size={20} />
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.home ?? leg.home_team}</span>
                <span className="text-zinc-600 text-[10px] shrink-0">vs</span>
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.away ?? leg.away_team}</span>
                <TeamLogo id={leg.away_team_id} name={leg.away ?? leg.away_team ?? ''} size={20} />
              </div>
              <span className={`font-black text-sm shrink-0 ${lr === 'GREEN' ? 'text-green-400' : lr === 'RED' ? 'text-red-400' : 'text-green-400'}`}>
                {Number(leg.odd).toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-1.5 ml-7 text-xs">
              <span className="font-semibold text-zinc-300">{translateMarket(leg.market)}</span>
              {leg.line && <><span className="text-zinc-600">·</span><span className="text-zinc-400">{translateLine(leg.line)}</span></>}
            </div>
          </div>
          )
        })}
      </div>

      {/* Confiança bar */}
      <div className="px-5 pb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-zinc-600">Confiança combinada</span>
          <span className={pct >= 70 ? 'text-green-400 font-bold' : 'text-zinc-500'}>{pct}%</span>
        </div>
        <div className="bg-zinc-800 rounded-full h-1 overflow-hidden">
          <div className={`h-1 rounded-full ${pct >= 70 ? 'bg-blue-500' : 'bg-zinc-600'}`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Fato da IA */}
      {shortReasoning(m.reasoning) && (
        <div className="mx-5 mb-3 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-xl">
          <span className="text-[10px] text-zinc-600 font-black uppercase tracking-wider">Fato · </span>
          <span className="text-[11px] text-zinc-400 leading-relaxed line-clamp-2">{shortReasoning(m.reasoning)}</span>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-5 py-3 border-t border-zinc-800/60">
        {!m.result ? (
          <button
            onClick={banca ? handleFollow : () => navigate('/banca')}
            disabled={following || followed}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : banca
                ? 'border-zinc-700 text-zinc-400 hover:border-blue-500/40 hover:text-blue-400 hover:bg-blue-500/5'
                : 'border-yellow-500/30 text-yellow-400 hover:border-yellow-500/60 hover:bg-yellow-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Registrado' : banca ? 'Apostar' : 'Configurar banca'}
          </button>
        ) : <span />}
        <div className="flex items-center gap-3 ml-auto">
          <button
            onClick={handleShare}
            disabled={sharing}
            className="flex items-center gap-1.5 text-xs font-bold text-green-400 bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60"
            title="Compartilhar pick"
          >
            {sharing
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /><span>Gerando...</span></>
              : shared
              ? <><CheckIcon className="w-3.5 h-3.5 text-green-400" /><span className="text-green-400">Compartilhado</span></>
              : <><Share2 className="w-3.5 h-3.5" /><span>Compartilhar</span></>
            }
          </button>
          <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">Ver detalhes</span>
        </div>
      </div>
    </div>
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
    {showSuccess && (
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg whitespace-nowrap">
        Pick registrado com sucesso!
      </div>
    )}
  </>
  )
}

// Alavancagem card
function AlavancagemCard({ pick, onClick, userBankroll, onConfigureBanca }: { pick: any; onClick?: () => void; userBankroll?: number; onConfigureBanca?: () => void }) {
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
    <div
      className="relative overflow-hidden bg-zinc-950 border border-orange-500/20 hover:border-orange-500/40 rounded-2xl cursor-pointer transition-all duration-200 group"
      onClick={onClick}
    >
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-orange-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-black text-orange-400">Alavancagem</span>
          <span className="badge-vip">VIP</span>
          {isCombo && <span className="text-[10px] text-blue-400 border border-blue-400/20 bg-blue-400/10 px-2 py-0.5 rounded-md font-bold">{comboLabel}</span>}
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label} {resultStyle.emoji}
          </span>
        ) : (
          <span className="text-[10px] text-yellow-500 border border-yellow-500/20 bg-yellow-500/10 px-2 py-1 rounded-lg font-bold">Pendente</span>
        )}
      </div>

      {/* Bankroll progression */}
      <div className="px-5 py-3 border-b border-zinc-800/60">
        {userBankroll != null ? (
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <div className="text-[10px] text-zinc-500 mb-1">Sua banca alavancagem</div>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-black text-orange-400">R${stake.toFixed(2)}</span>
                {!pick.result && (
                  <>
                    <span className="text-zinc-600 text-sm">·</span>
                    <span className="text-lg font-black text-white">R${potReturn.toFixed(2)}</span>
                    <span className="text-[10px] text-zinc-600">se green</span>
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
              <div className="text-[10px] text-zinc-500 mb-0.5">Odd</div>
              <div className="text-2xl font-black text-green-400">{oddCombined.toFixed(2)}</div>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] text-zinc-500 mb-0.5">Odd alvo</div>
              <div className="text-2xl font-black text-green-400">{oddCombined.toFixed(2)}</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-zinc-500 mb-0.5">Retorno pot.</div>
              <div className="text-lg font-black text-white">R${potReturn.toFixed(2)}</div>
              <div className="text-[10px] text-zinc-600">base R${stake.toFixed(0)}</div>
            </div>
          </div>
        )}
      </div>

      {/* Legs */}
      <div className="px-5 py-3 space-y-2">
        {legs.map((leg, i) => (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-orange-500/10 text-orange-400 text-[10px] font-black shrink-0">
                {i + 1}
              </span>
              <div className="flex items-center gap-1.5 flex-1 min-w-0">
                <TeamLogo id={leg.homeId} name={leg.home ?? ''} size={20} />
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.home}</span>
                <span className="text-zinc-600 text-[10px] shrink-0">vs</span>
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.away}</span>
                <TeamLogo id={leg.awayId} name={leg.away ?? ''} size={20} />
              </div>
              <span className="text-green-400 font-black text-sm shrink-0">{Number(leg.odd).toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-1.5 ml-7 text-xs">
              <span className="font-semibold text-zinc-300">{translateMarket(leg.market)}</span>
              {leg.line && <><span className="text-zinc-600">·</span><span className="text-zinc-400">{translateLine(leg.line)}</span></>}
              {leg.house && <><span className="text-zinc-600">·</span><span className="text-zinc-500">{leg.house}</span></>}
            </div>
          </div>
        ))}
      </div>

      {/* Confiança */}
      <div className="px-5 pb-3">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-zinc-600">Confiança</span>
          <span className={confPct >= 70 ? 'text-orange-400 font-bold' : 'text-zinc-500'}>{confPct}%</span>
        </div>
        <div className="bg-zinc-800 rounded-full h-1 overflow-hidden">
          <div className={`h-1 rounded-full ${confPct >= 70 ? 'bg-orange-500' : 'bg-zinc-600'}`} style={{ width: `${confPct}%` }} />
        </div>
      </div>

      {/* Fato da IA */}
      {shortReasoning(pick.reasoning_1) && (
        <div className="mx-5 mb-3 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-xl">
          <span className="text-[10px] text-zinc-600 font-black uppercase tracking-wider">Fato · </span>
          <span className="text-[11px] text-zinc-400 leading-relaxed line-clamp-2">{shortReasoning(pick.reasoning_1)}</span>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-5 py-3 border-t border-zinc-800/60">
        {!pick.result ? (
          <button
            onClick={e => {
              e.stopPropagation()
              if (userBankroll == null) { onConfigureBanca?.() ?? navigate('/banca') }
              else handleFollow(e as any)
            }}
            disabled={following || followed}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : userBankroll != null
                ? 'border-zinc-700 text-zinc-400 hover:border-orange-500/40 hover:text-orange-400 hover:bg-orange-500/5'
                : 'border-yellow-500/30 text-yellow-400 hover:border-yellow-500/60 hover:bg-yellow-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Registrado' : userBankroll != null ? 'Apostar' : 'Configurar banca'}
          </button>
        ) : <span />}
        <div className="flex items-center gap-3 ml-auto">
          <button
            onClick={handleShare}
            disabled={sharing}
            className="flex items-center gap-1.5 text-xs font-bold text-green-400 bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60"
            title="Compartilhar pick"
          >
            {sharing
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /><span>Gerando...</span></>
              : shared
              ? <><CheckIcon className="w-3.5 h-3.5 text-green-400" /><span className="text-green-400">Compartilhado</span></>
              : <><Share2 className="w-3.5 h-3.5" /><span>Compartilhar</span></>
            }
          </button>
          <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">Ver detalhes</span>
        </div>
      </div>
    </div>
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
    {showSuccess && (
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg whitespace-nowrap">
        Pick registrado com sucesso!
      </div>
    )}
  </>
  )
}

// Seção header
function SectionHeader({ color, label, badge }: { color: string; label: string; badge?: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className={`w-0.5 h-5 ${color} rounded-full block`} />
      <h2 className="text-sm font-black text-zinc-300">{label}</h2>
      {badge && <span className="badge-vip">{badge}</span>}
    </div>
  )
}

// Spinner
function Spinner() {
  return (
    <div className="card p-16 flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div>
  )
}

function CountdownTo7AM() {
  const [timeLeft, setTimeLeft] = useState<string | null>(null)

  useEffect(() => {
    const update = () => {
      const brNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }))
      if (brNow.getHours() >= 12) { setTimeLeft(null); return }
      const target = new Date(brNow)
      target.setHours(12, 0, 0, 0)
      if (brNow >= target) target.setDate(target.getDate() + 1)
      const diff = target.getTime() - brNow.getTime()
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setTimeLeft(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`)
    }
    update()
    const t = setInterval(update, 1000)
    return () => clearInterval(t)
  }, [])

  if (timeLeft === null) return null

  return (
    <div className="card p-8 text-center border-zinc-800">
      <p className="text-sm text-zinc-500 font-bold mb-4">Picks chegam até às 12h · Brasília</p>
      <div className="text-4xl font-black text-green-400 tabular-nums tracking-tight mb-3">{timeLeft}</div>
      <p className="text-zinc-500 text-sm">A IA está analisando os jogos de hoje...</p>
    </div>
  )
}

interface PipelineStep { key: string; label: string; status: 'pending' | 'running' | 'done' | 'error' }

// Mostra o progresso da geração dos picks (quando o pipeline diário está rodando),
// com fallback para o contador regressivo enquanto ele ainda não começou.
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
    return <CountdownTo7AM />
  }

  return (
    <div className="card p-8 border-zinc-800">
      <div className="flex flex-col items-center mb-6">
        <div className="relative mb-4">
          <span className="absolute inset-0 rounded-full bg-green-500/20 animate-ping" />
          <span className="relative flex items-center justify-center w-14 h-14 rounded-full bg-green-500/10 border border-green-500/30">
            <BrainCircuit className="w-7 h-7 text-green-400" />
          </span>
        </div>
        <p className="text-white font-bold text-base text-center">A IA está montando os picks de hoje</p>
        <p className="text-zinc-500 text-sm mt-1 text-center">Analisando estatísticas, odds e forma recente dos times</p>
      </div>
      <div className="space-y-3 max-w-xs mx-auto">
        {status.steps.map(s => (
          <div key={s.key} className="flex items-center gap-3">
            <span className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 text-[11px] font-black ${
              s.status === 'done'    ? 'bg-green-500/15 text-green-400' :
              s.status === 'running' ? 'bg-yellow-500/15 text-yellow-400' :
              s.status === 'error'   ? 'bg-zinc-700 text-zinc-500' :
                                        'bg-zinc-800 text-zinc-600'
            }`}>
              {s.status === 'done' ? '✓' : s.status === 'running' ? (
                <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
              ) : '·'}
            </span>
            <span className={`text-sm ${
              s.status === 'done'    ? 'text-zinc-400' :
              s.status === 'running' ? 'text-white font-semibold' :
                                        'text-zinc-600'
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
      <div className="divide-y divide-zinc-800/60">
        {rows.map(row => {
          const pt = showSource ? (row.pick_type ?? pickType) : pickType
          const p  = normalizePickRow(row, pt)
          return (
            <button
              key={`${pt}-${p.id}`}
              onClick={() => onOpen(p.id, pt)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/40 transition-colors text-left"
            >
              <div className="w-12 shrink-0 text-center">
                <span className="text-xs text-zinc-500">
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
                  <span className="text-sm font-semibold text-white truncate">{p.homeName}</span>
                  {p.awayName && (
                    <>
                      <span className="text-zinc-600 text-xs shrink-0">vs</span>
                      <span className="text-sm font-semibold text-white truncate">{p.awayName}</span>
                      <TeamLogo id={p.awayId} name={p.awayName} size={16} />
                    </>
                  )}
                </div>
                <p className="text-xs text-zinc-500 truncate">
                  {p.market}{p.line ? <> · <span className="text-zinc-400">{p.line}</span></> : ''}
                  {p.odd ? ` · Odd ${p.odd.toFixed(2)}` : ''}
                  {p.betHouse ? ` · ${p.betHouse}` : ''}
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {p.result ? (() => {
                  const rs = getResultStyle(p.result)
                  return (
                    <span className={`text-xs font-black px-2 py-0.5 rounded-lg border ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-zinc-500'}`}>
                      {rs ? rs.label : p.result}
                    </span>
                  )
                })() : (
                  <span className="text-xs font-black px-2 py-0.5 rounded-lg text-yellow-400 bg-yellow-400/10 border border-yellow-400/20">
                    Pendente
                  </span>
                )}
                {p.profit != null ? (
                  <span className={`text-sm font-black w-14 text-right ${p.profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                    {p.profit >= 0 ? '+' : ''}{p.isMonetary ? 'R$' : ''}{Math.abs(p.profit).toFixed(2)}{!p.isMonetary ? 'u' : ''}
                  </span>
                ) : (
                  <span className="text-sm font-black w-14 text-right text-zinc-700"></span>
                )}
              </div>
            </button>
          )
        })}
      </div>
      {footerAction && (
        <div className="px-4 py-3 border-t border-zinc-800">
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
function VipLockOverlay({ color = 'yellow' }: { color?: 'yellow' | 'blue' | 'orange' }) {
  const cls = color === 'blue'
    ? { icon: 'text-blue-400',   ring: 'bg-blue-400/10 border-blue-400/20',     btn: 'bg-blue-500 hover:bg-blue-400 text-white'    }
    : color === 'orange'
    ? { icon: 'text-orange-400', ring: 'bg-orange-400/10 border-orange-400/20', btn: 'bg-orange-500 hover:bg-orange-400 text-white' }
    : { icon: 'text-yellow-400', ring: 'bg-yellow-400/10 border-yellow-400/20', btn: 'bg-yellow-400 hover:bg-yellow-300 text-black' }
  return (
    <div className="relative rounded-2xl overflow-hidden">
      <div className="grid gap-4 md:grid-cols-2 select-none pointer-events-none" style={{ filter: 'blur(5px)', opacity: 0.35 }}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="card p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div className="h-3 bg-zinc-700 rounded w-24" />
              <div className="h-5 bg-zinc-700 rounded w-16" />
            </div>
            <div className="h-4 bg-zinc-700 rounded w-3/4" />
            <div className="grid grid-cols-3 gap-2">
              <div className="h-10 bg-zinc-800 rounded-lg" />
              <div className="h-10 bg-zinc-800 rounded-lg" />
              <div className="h-10 bg-zinc-800 rounded-lg" />
            </div>
            <div className="h-2 bg-zinc-800 rounded-full" />
          </div>
        ))}
      </div>
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 backdrop-blur-sm rounded-2xl">
        <div className="text-center px-6">
          <div className={`w-12 h-12 border rounded-full flex items-center justify-center mx-auto mb-3 ${cls.ring}`}>
            <svg className={`w-6 h-6 ${cls.icon}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <p className="text-white font-black text-base mb-1">Exclusivo para assinantes VIP</p>
          <p className="text-zinc-400 text-xs mb-4 max-w-xs">10 a 20 picks por dia com análise completa da IA e resultados em tempo real.</p>
          <Link to="/checkout" className={`inline-block font-black px-6 py-2.5 rounded-xl transition-colors text-sm ${cls.btn}`}>
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

  useEffect(() => {
    const hash = location.hash.replace('#', '') as Tab
    const valid: Tab[] = ['hoje','pick_seguro','vip','multiplas','alavancagem','aovivo','chat']
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

  // Tips VIP com filtros
  const [vipFilters, setVipFilters] = useState<VipFilters>(defaultVipFilters)
  const [vipRows,    setVipRows]    = useState<any[]>([])
  const [vipLoading, setVipLoading] = useState(false)
  const [meta,       setMeta]       = useState<{ bet_houses: string[]; market_types: string[] }>({ bet_houses: [], market_types: [] })
  const [vipLoaded,  setVipLoaded]  = useState(false)

  // Pick do Dia histórico
  const [pfFilters,  setPfFilters]  = useState<PickFreeFilters>(defaultPickFreeFilters)
  const [pfRows,     setPfRows]     = useState<any[]>([])
  const [pfLoading,  setPfLoading]  = useState(false)
  const [pfLoaded,   setPfLoaded]   = useState(false)

  // Múltiplas
  const [mFilters,  setMFilters]  = useState<MFilters>(defaultMFilters)
  const [multiplas, setMultiplas] = useState<any[]>([])
  const [mLoading,  setMLoading]  = useState(false)
  const [mLoaded,   setMLoaded]   = useState(false)

  // Alavancagem
  const [alavFilters,  setAlavFilters]  = useState<AlavFilters>(defaultAlavFilters)
  const [alavancagem,  setAlavancagem]  = useState<any[]>([])
  const [alavLoading,  setAlavLoading]  = useState(false)
  const [alavLoaded,   setAlavLoaded]   = useState(false)
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

  useEffect(() => {
    api.get('/suggestions/recent-results', { params: { limit: 40 } })
      .then(r => setRecentResults(r.data as any[]))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!canSeeVip) return
    api.get('/suggestions/vip/meta').then(r => setMeta(r.data)).catch(() => {})
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
    if (tab === 'pick_seguro'  && !pfLoaded)                doFetchPickFree(defaultPickFreeFilters)
    if (tab === 'vip'          && canSeeVip && !vipLoaded)  fetchVip(defaultVipFilters)
    if (tab === 'multiplas'    && canSeeVip && !mLoaded)    doFetchMultiplas(defaultMFilters)
    if (tab === 'alavancagem'  && canSeeVip && !alavLoaded) doFetchAlavancagem(defaultAlavFilters)
  }, [tab, canSeeVip])


  const fetchVip = useCallback((f: VipFilters) => {
    setVipLoading(true)
    const params: Record<string, string> = { order_by: f.order_by, limit: '100' }
    if (f.date_from) params.date_from = f.date_from
    if (f.date_to)   params.date_to   = f.date_to
    if (f.market_type !== 'all') params.market_type = f.market_type
    if (f.resultado  !== 'all') params.resultado    = f.resultado
    if (f.min_conf   !== '0')   params.min_conf     = f.min_conf
    if (f.bet_house  !== 'all') params.bet_house    = f.bet_house
    api.get('/suggestions/vip', { params })
      .then(r => { setVipRows(r.data); setVipLoaded(true) })
      .catch(() => setVipRows([]))
      .finally(() => setVipLoading(false))
  }, [])

  function doFetchPickFree(f: PickFreeFilters) {
    setPfLoading(true)
    const p: Record<string, string> = {}
    if (f.date_from) p.date_from = f.date_from
    if (f.date_to)   p.date_to   = f.date_to
    if (f.resultado !== 'all') p.resultado = f.resultado
    api.get('/suggestions/picks-free', { params: p })
      .then(r => { setPfRows(r.data); setPfLoaded(true) })
      .catch(() => setPfRows([]))
      .finally(() => setPfLoading(false))
  }

  function doFetchMultiplas(f: MFilters) {
    setMLoading(true)
    const p: Record<string, string> = { order_by: f.order_by }
    if (f.date_from) p.date_from = f.date_from
    if (f.date_to)   p.date_to   = f.date_to
    if (f.resultado !== 'all') p.resultado = f.resultado
    api.get('/suggestions/multiplas', { params: p })
      .then(r => { setMultiplas(r.data); setMLoaded(true) })
      .catch(() => setMultiplas([]))
      .finally(() => setMLoading(false))
  }

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

  function doFetchAlavancagem(f: AlavFilters) {
    setAlavLoading(true)
    const p: Record<string, string> = {}
    if (f.date_from) p.date_from = f.date_from
    if (f.date_to)   p.date_to   = f.date_to
    if (f.resultado !== 'all') p.resultado = f.resultado
    api.get('/suggestions/alavancagem', { params: p })
      .then(r => { setAlavancagem(r.data); setAlavLoaded(true) })
      .catch(() => setAlavancagem([]))
      .finally(() => setAlavLoading(false))
  }

  const setVf = (key: keyof VipFilters, val: string) =>
    setVipFilters(f => ({ ...f, [key]: val }))

  const vipTotal   = vipRows.length
  const vipGreens  = vipRows.filter(r => r.result === 'GREEN').length
  const vipPending = vipRows.filter(r => !r.result).length
  const vipLucro   = vipRows.reduce((acc, r) => acc + (Number(r.profit) || 0), 0)

  return (
    <div className="min-h-screen bg-black">
      {selectedId && <SuggestionDetail id={selectedId} pickType={selectedPickType} onClose={() => setSelectedId(null)} banca={bancaSummary?.has_banca ? bancaSummary : null} />}

      {/* Modal de boas-vindas · configura banca */}
      {showBancaModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm px-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-yellow-400/10 border border-yellow-400/20 flex items-center justify-center shrink-0">
                <Wallet className="w-5 h-5 text-yellow-400" />
              </div>
              <div>
                <h2 className="text-white font-black text-base">Configure sua banca</h2>
                <p className="text-zinc-500 text-xs">Último passo para começar a usar</p>
              </div>
            </div>
            <p className="text-zinc-400 text-sm leading-relaxed mb-5">
              Com a banca configurada você consegue <span className="text-white font-semibold">acompanhar seus picks</span>,
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
                className="w-full bg-yellow-400 hover:bg-yellow-300 text-black font-black text-sm py-3 rounded-xl transition-colors"
              >
                Configurar banca agora
              </button>
              <button
                onClick={() => {
                  sessionStorage.setItem('pickia_banca_modal_shown', '1')
                  setShowBancaModal(false)
                }}
                className="w-full text-zinc-500 hover:text-zinc-400 text-xs py-2 transition-colors"
              >
                Fazer depois
              </button>
            </div>
          </div>
        </div>
      )}

      <Navbar />

      {/* Cabeçalho */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-base font-black text-white tracking-tight">Picks</h1>
            {tab === 'hoje' ? (
              <div className="flex items-center gap-0.5 mt-0.5">
                <button
                  onClick={() => setSelectedOffset(o => o - 1)}
                  className="text-zinc-500 hover:text-zinc-300 transition-colors p-0.5 -ml-0.5"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="text-zinc-400 text-xs capitalize font-medium">
                  {selectedOffset === 0 ? 'Hoje' : todayLabel}
                </span>
                <button
                  onClick={() => setSelectedOffset(o => Math.min(0, o + 1))}
                  disabled={selectedOffset >= 0}
                  className="text-zinc-500 hover:text-zinc-300 disabled:opacity-20 transition-colors p-0.5"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
                {selectedOffset < 0 && (
                  <button
                    onClick={() => setSelectedOffset(0)}
                    className="ml-1 text-[10px] text-green-400 hover:text-green-300 font-bold transition-colors"
                  >
                    · Hoje
                  </button>
                )}
              </div>
            ) : (
              <p className="text-zinc-500 text-xs capitalize mt-0.5">{todayLabel}</p>
            )}
          </div>
          <div className="flex items-center gap-4">
            {quickStats && (
              <div className="hidden sm:flex items-center gap-3 text-xs">
                <span className="text-zinc-600">Win rate geral</span>
                <span className={`font-black text-sm ${(quickStats.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-400'}`}>
                  {quickStats.win_rate ?? 0}%
                </span>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
              <span className="text-green-500 text-xs font-bold">AO VIVO</span>
            </div>
          </div>
        </div>
      </div>

      <main className="max-w-6xl mx-auto px-4 py-6">
        {hasNew && (
          <div className="mb-4 flex items-center justify-between bg-green-500/10 border border-green-500/25 rounded-xl px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse shrink-0" />
              <span className="text-green-400 text-sm font-semibold">Novos picks disponíveis hoje!</span>
            </div>
            <button onClick={markSeen} className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">
              Fechar
            </button>
          </div>
        )}

        {hasLive && tab !== 'aovivo' && (
          <div className="mb-4 flex items-center justify-between bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
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
              <button onClick={clearLive} className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">✕</button>
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
          }}
        />

        {tab === 'hoje' && (
          <>
            {todayLoading ? <Spinner /> : todayError ? (
            <div className="card p-10 text-center">
              <p className="text-zinc-400 font-semibold mb-1">Erro ao carregar picks</p>
              <p className="text-zinc-600 text-sm mb-4">Não foi possível conectar ao servidor. Verifique sua conexão.</p>
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
                  <p className="text-[10px] text-zinc-600 uppercase tracking-wider font-semibold mb-2">Performance da IA · Geral</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Picks', value: String(quickStats.total ?? 0), color: 'text-white' },
                      { label: 'Green',  value: String(quickStats.greens ?? 0), color: 'text-green-500' },
                      { label: 'Red',    value: String(quickStats.reds ?? 0),   color: 'text-red-400' },
                      { label: 'Win %',  value: `${quickStats.win_rate ?? 0}%`, color: (quickStats.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-400' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 text-center">
                        <div className={`text-xl font-black ${color}`}>{value}</div>
                        <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">{label}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Progresso da geração / countdown quando picks ainda não chegaram */}
              {selectedOffset === 0 && !today?.dica_do_dia && !(today?.vip?.length) && !(today?.multiplas?.length) && !today?.alavancagem && (
                <PipelineStatusCard />
              )}

              {/* Horário de geração dos picks */}
              {(today?.vip?.[0]?.created_at || today?.dica_do_dia?.created_at) && (() => {
                const ts = today?.vip?.[0]?.created_at ?? today?.dica_do_dia?.created_at
                const hora = new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })
                return (
                  <p className="text-[11px] text-zinc-600 text-right -mt-4 mb-2">
                    Picks gerados hoje às {hora}
                  </p>
                )
              })()}

              {/* Pick Seguro · visível para todos; some se não houver dica hoje */}
              {today?.dica_do_dia && (
                <section>
                  <SectionHeader color="bg-green-500" label="Pick do Dia · Free" />
                  <PickSeguroCard dica={today.dica_do_dia} compact onClick={() => openDetail(today.dica_do_dia.id, 'free')} banca={bancaSummary?.has_banca ? bancaSummary : null} />
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
                        <div className="grid gap-4 md:grid-cols-2">
                          {vips.slice(0, 4).map((s: any) => (
                            <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} banca={bancaSummary?.has_banca ? bancaSummary : null} />
                          ))}
                        </div>
                        {vips.length > 4 && (
                          <button
                            onClick={() => setTab('vip')}
                            className="mt-4 w-full text-center text-xs text-green-500 hover:text-green-400 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700"
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
                      <div className="grid gap-4 md:grid-cols-2">
                        {multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} banca={bancaSummary?.has_banca ? bancaSummary : null} />)}
                      </div>
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
                        <p className="text-xs text-zinc-400 leading-relaxed">
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
                      />
                      <button onClick={() => setTab('alavancagem')}
                        className="mt-3 w-full text-center text-xs text-orange-400 hover:text-orange-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700">
                        Ver histórico da série
                      </button>
                    </>
                  )}
                </section>
              )}


            </div>
          )
        }
          </>
        )}

        {tab === 'pick_seguro' && (
          <div className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-green-500/20 bg-green-500/5">
              <p className="text-sm font-black text-green-400 mb-3">O que é o Pick do Dia Free?</p>
              <div className="space-y-2 text-sm text-zinc-400 leading-relaxed">
                <p>
                  Um pick gratuito publicado diariamente pela <span className="text-white font-bold">IA</span>. Analisamos centenas de
                  jogos e selecionamos o <span className="text-green-400 font-bold">1 pick com maior confiança</span> para disponibilizar para todos os usuários.
                </p>
                <p>
                  Ideal para quem quer experimentar a qualidade das análises antes de assinar o VIP.
                  Inclui mercado, odd, casa de apostas e raciocínio da IA.
                </p>
                <div className="grid grid-cols-3 gap-3 mt-3">
                  {[
                    { label: 'Frequência',  value: 'Diário',  color: 'text-green-400' },
                    { label: 'Picks/dia',   value: '1',       color: 'text-white'     },
                    { label: 'Custo',       value: 'Grátis',  color: 'text-green-400' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-zinc-900 rounded-xl p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-zinc-600 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Pick de hoje */}
            {todayLoading ? <Spinner /> : (
              <div>
                <SectionHeader color="bg-green-500" label={`Pick do Dia · ${todayDateStr}`} />
                {today?.dica_do_dia ? <PickSeguroCard dica={today.dica_do_dia} onClick={() => openDetail(today.dica_do_dia.id, 'free')} banca={bancaSummary?.has_banca ? bancaSummary : null} /> : <PickSeguroEmpty />}
              </div>
            )}


            <button onClick={() => navigate('/results')}
              className="w-full text-center text-xs text-green-500 hover:text-green-400 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700 font-semibold">
              Ver todos os resultados
            </button>
          </div>
        )}

        {tab === 'vip' && (
          <div className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-yellow-400/20 bg-yellow-400/5">
              <p className="text-sm font-black text-yellow-400 mb-3">O que são os Picks VIP?</p>
              <div className="space-y-2 text-sm text-zinc-400 leading-relaxed">
                <p>
                  Picks exclusivos gerados pela <span className="text-white font-bold">IA</span> com análise estatística avançada.
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
                    { label: 'Mercados',     value: '5+',     color: 'text-white'      },
                    { label: 'Análise IA',   value: 'Completa', color: 'text-green-400' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-zinc-900 rounded-xl p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-zinc-600 mt-0.5">{label}</div>
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
              {!canSeeVip ? <VipLockOverlay color="yellow" /> : todayLoading ? <Spinner /> : (() => {
                const vips = today?.vip ?? []
                const leagues = Array.from(new Set(vips.map((s: any) => s.league_name).filter(Boolean))) as string[]
                const byLeague = leagueFilter ? vips.filter((s: any) => s.league_name === leagueFilter) : vips
                const filteredVips = vipResultFilter
                  ? byLeague.filter((s: any) => vipResultFilter === 'pending' ? !s.result : s.result === vipResultFilter)
                  : byLeague
                const RESULT_FILTERS: [string, string][] = [['', 'Todos'], ['pending', 'Pendentes'], ['GREEN', 'Green'], ['RED', 'Red']]
                return (
                  <>
                    {leagues.length > 1 && (
                      <div className="flex gap-2 flex-wrap mb-3">
                        <button
                          onClick={() => setLeagueFilter('')}
                          className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors ${!leagueFilter ? 'bg-yellow-400/15 border-yellow-400/40 text-yellow-400' : 'border-zinc-800 text-zinc-500 hover:border-zinc-700'}`}
                        >
                          Todas
                        </button>
                        {leagues.map(lg => (
                          <button
                            key={lg}
                            onClick={() => setLeagueFilter(lg === leagueFilter ? '' : lg)}
                            className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors ${leagueFilter === lg ? 'bg-yellow-400/15 border-yellow-400/40 text-yellow-400' : 'border-zinc-800 text-zinc-500 hover:border-zinc-700'}`}
                          >
                            {lg}
                          </button>
                        ))}
                      </div>
                    )}
                    {vips.length > 1 && (
                      <div className="flex gap-2 flex-wrap mb-4">
                        {RESULT_FILTERS.map(([k, l]) => (
                          <button
                            key={k}
                            onClick={() => setVipResultFilter(k === vipResultFilter ? '' : k)}
                            className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors ${vipResultFilter === k ? 'bg-yellow-400/15 border-yellow-400/40 text-yellow-400' : 'border-zinc-800 text-zinc-500 hover:border-zinc-700'}`}
                          >
                            {l}
                          </button>
                        ))}
                      </div>
                    )}
                    {filteredVips.length > 0 ? (
                      <div className="grid gap-4 md:grid-cols-2">
                        {filteredVips.map((s: any) => (
                          <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} banca={bancaSummary?.has_banca ? bancaSummary : null} />
                        ))}
                      </div>
                    ) : (
                      <div className="card p-8 text-center border-dashed">
                        <p className="text-zinc-500 text-sm font-semibold">{leagueFilter || vipResultFilter ? 'Nenhum pick encontrado com esse filtro.' : 'Picks VIP do dia ainda não gerados.'}</p>
                        <p className="text-zinc-600 text-xs mt-1">{leagueFilter || vipResultFilter ? '' : 'Os picks saem pela manhã. Volte mais tarde.'}</p>
                      </div>
                    )}
                  </>
                )
              })()}
            </div>


            <button onClick={() => navigate('/results')}
              className="w-full text-center text-xs text-yellow-400 hover:text-yellow-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700 font-semibold">
              Ver todos os resultados
            </button>
          </div>
        )}

        {tab === 'multiplas' && (
          <div className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-blue-400/20 bg-blue-400/5">
              <p className="text-sm font-black text-blue-400 mb-3">O que são as Múltiplas VIP?</p>
              <div className="space-y-2 text-sm text-zinc-400 leading-relaxed">
                <p>
                  A IA combina <span className="text-white font-bold">3 a 5 seleções</span> de alta confiança em uma única aposta múltipla,
                  gerando odds combinadas acima de <span className="text-blue-400 font-bold">3.00</span> com risco controlado.
                </p>
                <p>
                  Cada seleção da múltipla é analisada individualmente antes de compor a aposta.
                  Publicadas diariamente com raciocínio completo da IA para cada perna.
                </p>
                <div className="grid grid-cols-3 gap-3 mt-3">
                  {[
                    { label: 'Seleções',   value: '3–5',   color: 'text-blue-400'   },
                    { label: 'Odd alvo',   value: '3.00+', color: 'text-green-400'  },
                    { label: 'Frequência', value: 'Diário', color: 'text-white'     },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-zinc-900 rounded-xl p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-zinc-600 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Múltiplas de hoje */}
            <div>
              <SectionHeader color="bg-blue-400" label={`Múltiplas do Dia · ${todayDateStr}`} />
              {!canSeeVip ? <VipLockOverlay color="blue" /> : todayLoading ? <Spinner /> : (
                today?.multiplas?.length > 0 ? (
                  <div className="space-y-4">
                    {today.multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} banca={bancaSummary?.has_banca ? bancaSummary : null} />)}
                  </div>
                ) : (
                  <div className="card p-8 text-center border-dashed">
                    <p className="text-zinc-500 text-sm font-semibold">Múltipla do dia ainda não gerada.</p>
                    <p className="text-zinc-600 text-xs mt-1">Publicada diariamente pela manhã.</p>
                  </div>
                )
              )}
            </div>


            <button onClick={() => navigate('/results')}
              className="w-full text-center text-xs text-blue-400 hover:text-blue-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700 font-semibold">
              Ver todos os resultados
            </button>
          </div>
        )}

        {tab === 'alavancagem' && (
          <div className="space-y-6">
            {/* Como funciona */}
            <div className="card p-5 border-orange-500/20 bg-orange-500/5">
              <p className="text-sm font-black text-orange-400 mb-3">Como funciona a Alavancagem?</p>
              <div className="space-y-2 text-sm text-zinc-400 leading-relaxed">
                <p>
                  A banca começa em <span className="text-white font-bold">R$50</span> e o lucro de cada GREEN é
                  reinvestido integralmente na próxima aposta, sem retirar nada.
                </p>
                <p>
                  A cada <span className="text-red-400 font-bold">RED</span>, a banca reseta para R$50 e uma nova
                  série começa do zero. A IA seleciona 1 pick (ou combinada de 2 com alta correlação)
                  com <span className="text-white font-bold">odd alvo 1.50</span> para maximizar a consistência.
                </p>
                <p>
                  O objetivo é <span className="text-green-400 font-bold">encadear greens consecutivos</span> e multiplicar
                  a banca progressivamente durante o torneio. Uma sequência de 5 greens transforma R$50 em mais de R$300.
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                  {[
                    { label: 'Banca inicial', value: 'R$50',   color: 'text-orange-400' },
                    { label: 'Odd alvo',      value: '1.50',   color: 'text-green-400'  },
                    { label: 'Reset no RED',  value: 'R$50',   color: 'text-red-400'    },
                    { label: '5 greens',      value: 'R$300+', color: 'text-white'      },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-zinc-900 rounded-xl p-3 text-center">
                      <div className={`text-lg font-black ${color}`}>{value}</div>
                      <div className="text-xs text-zinc-600 mt-0.5">{label}</div>
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
                      <p className="text-sm font-black text-orange-400">Banca Alavancagem</p>
                      <p className="text-xs text-zinc-500 mt-0.5">Separada da sua banca principal. Reinveste a cada GREEN, reseta no RED</p>
                    </div>
                    {userAlavSerie?.configured && (
                      <div className="text-right">
                        <div className="text-2xl font-black text-orange-400">R${userAlavSerie.current_bankroll.toFixed(2)}</div>
                        <div className="text-xs text-zinc-600">início: R${userAlavSerie.initial_bankroll.toFixed(2)}</div>
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
                        className="input flex-1 text-sm"
                      />
                      <button
                        onClick={saveAlavInit}
                        disabled={alavInitSaving || !alavInitInput}
                        className="bg-orange-500 hover:bg-orange-400 disabled:opacity-50 text-white font-black px-4 py-2 rounded-xl text-sm transition-colors"
                      >
                        {alavInitSaving ? '...' : userAlavSerie?.configured ? 'Alterar' : 'Definir'}
                      </button>
                      {userAlavSerie?.configured && (
                        <button onClick={() => setAlavInitInput('')} className="px-3 py-2 rounded-xl border border-zinc-700 text-zinc-500 text-sm hover:text-white transition-colors">✕</button>
                      )}
                    </div>
                  ) : (
                    <button
                      onClick={() => setAlavInitInput(String(userAlavSerie.initial_bankroll))}
                      className="text-xs text-zinc-600 hover:text-orange-400 transition-colors underline"
                    >
                      Alterar valor inicial
                    </button>
                  )}
                  {alavInitError && (
                    <p className="text-xs text-red-400 mt-2">{alavInitError}</p>
                  )}
                </div>

                {/* Pick de hoje */}
                {todayLoading ? <Spinner /> : (
                  <div>
                    <SectionHeader color="bg-orange-400" label={`Pick do Dia · ${todayDateStr}`} />
                    {today?.alavancagem ? (
                      <AlavancagemCard
                        pick={today.alavancagem}
                        onClick={() => openDetail(today.alavancagem.id, 'alavancagem')}
                        userBankroll={userAlavSerie?.configured ? userAlavSerie.current_bankroll : undefined}
                        onConfigureBanca={() => setTab('alavancagem')}
                      />
                    ) : (
                      <div className="card p-8 text-center border-dashed border-orange-500/20">
                        <p className="text-zinc-500 text-sm font-semibold">Pick de alavancagem não gerado para hoje.</p>
                        <p className="text-zinc-600 text-xs mt-1">Publicado diariamente até às 12h.</p>
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
                        <div className="flex justify-center py-6"><div className="w-6 h-6 border-2 border-zinc-700 border-t-orange-400 rounded-full animate-spin" /></div>
                      ) : !alavancagem.length ? (
                        <div className="card p-8 text-center border-dashed border-orange-500/20">
                          <p className="text-zinc-500 text-sm font-semibold">Série ainda não iniciada.</p>
                          <p className="text-zinc-600 text-xs mt-1">Os stats aparecem assim que os primeiros picks forem gerados.</p>
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
                            { label: 'Resets (RED)', value: String(resets), color: resets > 0 ? 'text-red-400' : 'text-zinc-500', sub: resets === 0 ? 'Nenhum ainda' : `${resets} reinício${resets > 1 ? 's' : ''}` },
                            { label: 'Série Atual', value: currentStreak > 0 ? `${currentStreak} green${currentStreak > 1 ? 's' : ''}` : '', color: currentStreak >= 3 ? 'text-green-400' : currentStreak > 0 ? 'text-green-500' : 'text-zinc-500', sub: currentStreak > 0 ? 'seguidos' : 'Aguardando' },
                            { label: 'Melhor Série', value: bestStreak > 0 ? `${bestStreak} green${bestStreak > 1 ? 's' : ''}` : '', color: 'text-yellow-400', sub: bestStreak > 0 ? 'recorde da série' : 'Ainda sem greens' },
                          ].map(({ label, value, color, sub }) => (
                            <div key={label} className="card p-4 text-center">
                              <div className={`text-xl font-black ${color}`}>{value}</div>
                              <div className="text-xs text-zinc-500 font-semibold mt-0.5">{label}</div>
                              <div className="text-[10px] text-zinc-700 mt-0.5">{sub}</div>
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
                                <div className={`w-0.5 flex-1 my-1 min-h-[16px] ${res === 'GREEN' ? 'bg-green-500/30' : res === 'RED' ? 'bg-red-500/30' : 'bg-zinc-800'}`} />
                              )}
                            </div>
                            <div
                              onClick={() => openDetail(pick.id, 'alavancagem')}
                              className={`flex-1 mb-2 rounded-xl border px-3 py-2.5 cursor-pointer hover:border-orange-500/40 transition-colors ${
                                !res ? 'border-orange-500/40 bg-orange-500/5' : 'border-zinc-800 bg-zinc-900'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1 flex-wrap mb-0.5">
                                    <TeamLogo id={pick.home_team_id_1} name={pick.home_team_1 ?? ''} size={14} />
                                    <span className="text-xs font-bold text-white truncate">{pick.home_team_1}</span>
                                    <span className="text-zinc-600 text-[10px]">vs</span>
                                    <TeamLogo id={pick.away_team_id_1} name={pick.away_team_1 ?? ''} size={14} />
                                    <span className="text-xs font-bold text-white truncate">{pick.away_team_1}</span>
                                  </div>
                                  <div className="text-[10px] text-zinc-500">{date}</div>
                                </div>
                                <div className="text-right shrink-0 space-y-0.5">
                                  {bankBefore != null && (
                                    <div className="text-[10px] text-zinc-600">R${bankBefore.toFixed(2)}</div>
                                  )}
                                  {profit != null && (
                                    <div className={`text-xs font-black ${profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                      {profit >= 0 ? '+' : ''}R${profit.toFixed(2)}
                                    </div>
                                  )}
                                  {bankAfter != null && (
                                    <div className="text-[10px] text-zinc-500">Banca: R${bankAfter.toFixed(2)}</div>
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


            <button onClick={() => navigate('/results')}
              className="w-full text-center text-xs text-orange-400 hover:text-orange-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700 font-semibold">
              Ver todos os resultados
            </button>
          </div>
        )}
        <div className={tab !== 'aovivo' ? 'hidden' : ''}>
          <LivePicks isActive={tab === 'aovivo'} unitValue={bancaSummary?.unit_value} />
        </div>



      </main>
      <Footer />
    </div>
  )
}

