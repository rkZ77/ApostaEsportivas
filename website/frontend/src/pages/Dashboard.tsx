import { useEffect, useState, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import SuggestionCard from '../components/SuggestionCard'
import SuggestionDetail from '../components/SuggestionDetail'
import Navbar from '../components/Navbar'
import Avatar from '../components/Avatar'
import CommunityChat from '../components/CommunityChat'
import Footer from '../components/Footer'
import { UserCircle, Crown, Rocket } from 'lucide-react'
import { suggestStake } from '../utils/stakeUtils'

// ─── Helpers de logo ──────────────────────────────────────────────────────────
const TEAM_LOGO   = (id?: number) => id ? `/api/proxy/team/${id}.png` : null
const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id?: number) =>
  id ? (LOCAL_LEAGUE_LOGOS[id] ?? `/api/proxy/league/${id}.png`) : null

function TeamLogo({ id, name, size = 24 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size}
      className="object-contain shrink-0" style={{ width: size, height: size }}
      referrerPolicy="no-referrer"
      onError={e => (e.currentTarget.style.display = 'none')} loading="lazy" />
  )
}

function LeagueLogo({ id, name, size = 18 }: { id?: number; name?: string; size?: number }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={size} height={size}
      className="object-contain shrink-0 opacity-80" style={{ width: size, height: size }}
      referrerPolicy="no-referrer"
      onError={e => (e.currentTarget.style.display = 'none')} loading="lazy" />
  )
}

// ─── Tradução de mercados ─────────────────────────────────────────────────────
const MARKET_PT: Record<string, string> = {
  'Goals Over/Under': 'Gols ±',
  'Over/Under': 'Gols ±',
  'Both Teams Score': 'Ambas Marcam',
  'Both Teams To Score': 'Ambas Marcam',
  'Asian Handicap': 'Handicap Asiático',
  'Double Chance': 'Dupla Chance',
  'Corners Over/Under': 'Escanteios ±',
  'Total Corners': 'Escanteios',
  'Cards Over/Under': 'Cartões ±',
  'Total Cards': 'Cartões',
  'Match Winner': 'Resultado',
  'Result': 'Resultado',
  'Home/Away': '1X2',
  'HT/FT': 'Inter./Final',
  'Exact Score': 'Placar Exato',
  'First Goal': 'Primeiro Gol',
  'Anytime Score': 'Marcar a Qualquer Tempo',
}
const translateMarket = (m?: string) => (m ? (MARKET_PT[m] ?? m) : '')

// ─── Tipos ────────────────────────────────────────────────────────────────────
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

// ─── Tab bar ──────────────────────────────────────────────────────────────────
function TabBar({ tab, setTab, canSeeVip, counts }: {
  tab: Tab; setTab: (t: Tab) => void; canSeeVip: boolean
  counts?: Partial<Record<Tab, number>>
}) {
  const tabs: { key: Tab; label: string; badge?: string; badgeCls?: string; premiumOnly?: boolean }[] = [
    { key: 'hoje',         label: 'Hoje'            },
    { key: 'pick_seguro',  label: 'Picks Free',      badge: 'FREE', badgeCls: 'bg-green-500/10 text-green-400 border-green-500/20' },
    { key: 'vip',          label: 'Picks VIP',       premiumOnly: true },
    { key: 'multiplas',    label: 'Múltiplas',       premiumOnly: true },
    { key: 'alavancagem',  label: 'Alavancagem',      premiumOnly: true },
    { key: 'aovivo',       label: 'Ao Vivo',          badge: 'LIVE', badgeCls: 'bg-red-500/10 text-red-400 border-red-500/20' },
    { key: 'chat',         label: 'Comunidade'       },
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

// ─── User greeting ────────────────────────────────────────────────────────────
function UserGreeting({ user, isVip, isAdmin, daysUntilExpiry }: {
  user: any; isVip: boolean; isAdmin: boolean; daysUntilExpiry: number | null
}) {
  if (!user) return null
  const firstName = user.name.split(' ')[0]

  const isTrial = user.plan === 'trial'
  const planColor = isAdmin ? 'text-purple-400 bg-purple-400/10 border-purple-400/20'
    : isTrial ? 'text-green-400 bg-green-500/10 border-green-500/20'
    : isVip ? 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
    : 'text-zinc-400 bg-zinc-800 border-zinc-700'
  const planLabel = isAdmin ? 'ADMIN' : isTrial ? 'TESTE' : isVip ? 'VIP' : 'FREE'

  return (
    <div className="card p-4 mb-5 flex items-center gap-4">
      <Avatar name={user.name} imageUrl={user.avatar_url} size="lg" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-white font-black text-lg leading-tight">Olá, {firstName}!</h2>
          <span className={`text-xs font-black px-2.5 py-0.5 rounded-full border ${planColor}`}>{planLabel}</span>
        </div>
        <p className="text-zinc-500 text-xs mt-0.5 truncate">{user.email}</p>
        {isVip && daysUntilExpiry !== null && (
          <p className={`text-xs mt-1 font-semibold ${daysUntilExpiry <= 3 ? 'text-red-400' : daysUntilExpiry <= 7 ? 'text-yellow-400' : 'text-zinc-500'}`}>
            {daysUntilExpiry <= 0
              ? 'Plano expirado'
              : isTrial
                ? `Teste VIP · ${daysUntilExpiry} dia${daysUntilExpiry === 1 ? '' : 's'} restante${daysUntilExpiry === 1 ? '' : 's'}`
                : `Plano VIP · ${daysUntilExpiry} dia${daysUntilExpiry === 1 ? '' : 's'} restante${daysUntilExpiry === 1 ? '' : 's'}`}
          </p>
        )}
        {!isVip && !isAdmin && (
          <Link to="/checkout" className="text-xs text-yellow-400 hover:text-yellow-300 transition-colors mt-1 inline-block font-semibold">
            Fazer upgrade para VIP →
          </Link>
        )}
      </div>
      <div className="shrink-0 hidden sm:flex flex-col gap-1.5">
        <Link to="/profile" className="flex items-center justify-center gap-1.5 text-blue-400 hover:text-blue-300 transition-colors text-xs border border-blue-400/20 hover:border-blue-400/40 bg-blue-400/5 px-3 py-2 rounded-lg font-semibold">
          <UserCircle className="w-3.5 h-3.5" />
          Editar perfil
        </Link>
        {!isAdmin && (isVip || user?.plan === 'trial') && (
          <Link to="/planos" className="flex items-center justify-center gap-1.5 text-yellow-400 hover:text-yellow-300 transition-colors text-xs border border-yellow-400/20 hover:border-yellow-400/40 bg-yellow-400/5 px-3 py-2 rounded-lg font-semibold">
            <Crown className="w-3.5 h-3.5" />
            Meu Plano
          </Link>
        )}
        {!isAdmin && !isVip && user?.plan !== 'trial' && (
          <Link to="/checkout" className="flex items-center justify-center gap-1.5 text-yellow-400 hover:text-yellow-300 transition-colors text-xs border border-yellow-400/20 hover:border-yellow-400/40 bg-yellow-400/5 px-3 py-2 rounded-lg font-semibold">
            <Rocket className="w-3.5 h-3.5" />
            Upgrade VIP
          </Link>
        )}
      </div>
    </div>
  )
}

// ─── Quick stats ──────────────────────────────────────────────────────────────
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
      value: streak > 0 ? (streakType === 'green' ? `+${streak}` : `-${streak}`) : '—',
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

// ─── Pick do Dia card ─────────────────────────────────────────────────────────
function shortReasoning(text?: string): string {
  if (!text) return ''
  const fatoMatch = text.match(/FATO:\s*(.+?)(?=\s*ANÁLISE:|$)/i)
  if (fatoMatch) return fatoMatch[1].trim()
  return text.slice(0, 130)
}

function PickSeguroCard({ dica, compact = false, onClick, banca }: { dica: any; compact?: boolean; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null }) {
  const pct = Math.round((dica.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState(dica.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const stakeSuggestion = banca
    ? suggestStake(dica.confidence, Number(dica.odd), banca.bankroll_current, banca.unit_value)
    : null
  const fato = shortReasoning(dica.reasoning)

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    setFollowing(true)
    try {
      await api.post('/banca/follow', { pick_id: dica.id, pick_type: 'free', stake_units: stakeSuggestion?.units ?? 1 })
      setFollowed(true)
    } catch { /* ignora */ } finally {
      setFollowing(false)
    }
  }

  const isCopa = dica.league_id === 1
  const resultStyle =
    dica.result === 'GREEN' ? { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', label: 'GREEN ✓' }
    : dica.result === 'RED' ? { bg: 'bg-red-500/10',   border: 'border-red-500/30',   text: 'text-red-400',   label: 'RED ✗' }
    : null

  return (
    <div
      className={`relative overflow-hidden bg-zinc-950 border rounded-2xl transition-all duration-200 group ${isCopa ? 'border-yellow-500/20' : 'border-green-500/20'} ${onClick ? (isCopa ? 'hover:border-yellow-500/40 cursor-pointer' : 'hover:border-green-500/40 cursor-pointer') : ''}`}
      onClick={onClick}
    >
      <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent to-transparent ${isCopa ? 'via-yellow-500' : 'via-green-500'}`} />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[10px] font-black uppercase tracking-widest ${isCopa ? 'text-yellow-500' : 'text-green-400'}`}>Pick do Dia</span>
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
            {resultStyle.label}
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
              <div className="text-[10px] text-zinc-500 mb-0.5">Retorno pot.</div>
              <div className="text-xl font-black text-white">
                R${(stakeSuggestion.amountR * Number(dica.odd)).toFixed(0)}
              </div>
            </div>
          </>
        ) : dica.profit != null ? (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-zinc-500 mb-0.5">Lucro</div>
            <div className={`text-2xl font-black ${dica.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {dica.profit >= 0 ? '+' : ''}{Number(dica.profit).toFixed(2)}u
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Stake</div>
              <div className="text-xl font-black text-zinc-200">1u</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Confiança</div>
              <div className={`text-xl font-black ${pct >= 75 ? 'text-green-400' : 'text-zinc-300'}`}>{pct}%</div>
            </div>
          </>
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
        {!dica.result && !banca ? (
          <a href="/banca" className="text-[11px] text-green-500/70 hover:text-green-400 underline">Configurar banca</a>
        ) : !dica.result && banca ? (
          <button
            onClick={handleFollow}
            disabled={following || followed}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : 'border-zinc-700 text-zinc-400 hover:border-green-500/50 hover:text-green-400 hover:bg-green-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Apostei' : '+ Apostei'}
          </button>
        ) : <span />}
        {onClick && (
          <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors ml-auto">
            Ver detalhes →
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Vazio do Pick Seguro ─────────────────────────────────────────────────────
function PickSeguroEmpty() {
  const hour = new Date().getHours()
  const msg = hour < 8
    ? 'O Pick do Dia será publicado após as 08:00.'
    : hour < 12
    ? 'O Pick do Dia está sendo preparado pela IA.'
    : 'Nenhum Pick do Dia disponível para hoje.'

  return (
    <div className="card p-10 text-center border-dashed">
      <p className="text-zinc-500 text-sm font-semibold mb-1">Pick do Dia indisponível</p>
      <p className="text-zinc-600 text-xs">{msg}</p>
    </div>
  )
}

// ─── Múltipla card ────────────────────────────────────────────────────────────
function MultiplaCard({ m, onClick, banca }: { m: any; onClick?: () => void; banca?: { bankroll_current: number; unit_value: number } | null }) {
  let legs: any[] = []
  try { legs = typeof m.legs === 'string' ? JSON.parse(m.legs) : (m.legs ?? []) } catch { legs = [] }

  const pct = Math.round((m.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState<boolean>(!!m.is_followed)
  const [following, setFollowing] = useState(false)
  const stakeSuggestion = banca
    ? suggestStake(m.confidence, Number(m.total_odd), banca.bankroll_current, banca.unit_value)
    : null
  const potReturn = stakeSuggestion
    ? (stakeSuggestion.amountR * Number(m.total_odd)).toFixed(2)
    : null

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following) return
    setFollowing(true)
    try {
      await api.post('/banca/follow', {
        pick_id: m.id,
        pick_type: 'multipla',
        stake_units: stakeSuggestion?.units ?? 1,
      })
      setFollowed(true)
    } catch {
      setFollowed(false)
    } finally {
      setFollowing(false)
    }
  }

  const resultStyle = m.result === 'GREEN'
    ? { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', label: 'GREEN ✓' }
    : m.result === 'RED'
    ? { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', label: 'RED ✗' }
    : null

  return (
    <div
      className="relative overflow-hidden bg-zinc-950 border border-zinc-800 hover:border-blue-500/30 rounded-2xl cursor-pointer transition-all duration-200 group"
      onClick={onClick}
    >
      {/* Accent bar */}
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-blue-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-black text-blue-400 uppercase tracking-widest">Múltipla</span>
          <span className="badge-vip">VIP</span>
          <span className="text-[10px] text-zinc-600">
            {new Date(m.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}
            {' · '}{legs.length} seleções
          </span>
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label}
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
              <div className="text-[10px] text-zinc-500 mb-0.5">Retorno pot.</div>
              <div className="text-xl font-black text-white">R${potReturn}</div>
            </div>
          </>
        ) : m.profit != null ? (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-zinc-500 mb-0.5">Lucro</div>
            <div className={`text-2xl font-black ${m.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {m.profit >= 0 ? '+' : ''}{Number(m.profit).toFixed(2)}u
            </div>
          </div>
        ) : (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-zinc-500 mb-0.5">Confiança</div>
            <div className={`text-2xl font-black ${pct >= 70 ? 'text-green-400' : 'text-zinc-300'}`}>{pct}%</div>
          </div>
        )}
      </div>

      {/* Legs */}
      <div className="px-5 py-3 space-y-2">
        {legs.map((leg: any, i: number) => (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-blue-500/10 text-blue-400 text-[10px] font-black shrink-0">
                {i + 1}
              </span>
              <div className="flex items-center gap-1.5 flex-1 min-w-0">
                <TeamLogo id={leg.home_team_id} name={leg.home ?? leg.home_team ?? ''} size={20} />
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.home ?? leg.home_team}</span>
                <span className="text-zinc-600 text-[10px] shrink-0">vs</span>
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.away ?? leg.away_team}</span>
                <TeamLogo id={leg.away_team_id} name={leg.away ?? leg.away_team ?? ''} size={20} />
              </div>
              <span className="text-green-400 font-black text-sm shrink-0">{Number(leg.odd).toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-1.5 ml-7 text-xs">
              <span className="font-semibold text-zinc-300">{translateMarket(leg.market)}</span>
              {leg.line && <><span className="text-zinc-600">·</span><span className="text-zinc-400">{leg.line}</span></>}
            </div>
          </div>
        ))}
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
        {!m.result && !banca ? (
          <a href="/banca" className="text-[11px] text-green-500/70 hover:text-green-400 underline">Configurar banca</a>
        ) : !m.result && banca ? (
          <button
            onClick={handleFollow}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : 'border-zinc-700 text-zinc-400 hover:border-blue-500/40 hover:text-blue-400 hover:bg-blue-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Apostei' : '+ Apostei'}
          </button>
        ) : <span />}
        <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">Ver detalhes →</span>
      </div>
    </div>
  )
}

// ─── Alavancagem card ─────────────────────────────────────────────────────────
function AlavancagemCard({ pick, onClick, userBankroll, onConfigureBanca }: { pick: any; onClick?: () => void; userBankroll?: number; onConfigureBanca?: () => void }) {
  const isCombo     = pick.tipo === 'combinacao'
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

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following) return
    setFollowing(true)
    try {
      await api.post('/banca/follow', { pick_id: pick.id, pick_type: 'alavancagem' })
      setFollowed(true)
    } catch {
      setFollowed(false)
    } finally {
      setFollowing(false)
    }
  }

  const legs: any[] = []
  if (pick.home_team_1) legs.push({ home: pick.home_team_1, away: pick.away_team_1, homeId: pick.home_team_id_1, awayId: pick.away_team_id_1, market: pick.market_1, line: pick.line_1, odd: pick.odd_1, house: pick.bet_house_1 })
  if (isCombo && pick.home_team_2) legs.push({ home: pick.home_team_2, away: pick.away_team_2, homeId: pick.home_team_id_2, awayId: pick.away_team_id_2, market: pick.market_2, line: pick.line_2, odd: pick.odd_2, house: pick.bet_house_2 })

  const resultStyle = pick.result === 'GREEN'
    ? { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', label: 'GREEN ✓' }
    : pick.result === 'RED'
    ? { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', label: 'RED ✗' }
    : null

  return (
    <div
      className="relative overflow-hidden bg-zinc-950 border border-orange-500/20 hover:border-orange-500/40 rounded-2xl cursor-pointer transition-all duration-200 group"
      onClick={onClick}
    >
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-orange-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-black text-orange-400 uppercase tracking-widest">Alavancagem</span>
          <span className="badge-vip">VIP</span>
          {isCombo && <span className="text-[10px] text-blue-400 border border-blue-400/20 bg-blue-400/10 px-2 py-0.5 rounded-md font-bold">Combinada</span>}
        </div>
        {resultStyle ? (
          <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.border} ${resultStyle.text}`}>
            {resultStyle.label}
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
                    <span className="text-zinc-600 text-sm">→</span>
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
              {leg.line && <><span className="text-zinc-600">·</span><span className="text-zinc-400">{leg.line}</span></>}
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
        {!pick.result && userBankroll == null ? (
          <button onClick={e => { e.stopPropagation(); onConfigureBanca?.() }} className="text-[11px] text-orange-500/70 hover:text-orange-400 underline">Configurar banca alavancagem</button>
        ) : !pick.result ? (
          <button
            onClick={handleFollow}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : 'border-zinc-700 text-zinc-400 hover:border-orange-500/40 hover:text-orange-400 hover:bg-orange-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Apostei' : '+ Apostei'}
          </button>
        ) : <span />}
        <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">Ver detalhes →</span>
      </div>
    </div>
  )
}

// ─── Seção header ─────────────────────────────────────────────────────────────
function SectionHeader({ color, label, badge }: { color: string; label: string; badge?: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className={`w-0.5 h-5 ${color} rounded-full block`} />
      <h2 className="text-xs font-black text-zinc-300 uppercase tracking-widest">{label}</h2>
      {badge && <span className="badge-vip">{badge}</span>}
    </div>
  )
}

// ─── Spinner ──────────────────────────────────────────────────────────────────
function Spinner() {
  return (
    <div className="card p-16 flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div>
  )
}

// ─── Constantes resultado / fonte ─────────────────────────────────────────────
const RESULT_CLS: Record<string, string> = {
  GREEN:       'bg-green-500/10 text-green-400 border border-green-500/30',
  RED:         'bg-red-500/10 text-red-400 border border-red-500/30',
  PUSH:        'bg-zinc-700/50 text-zinc-400 border border-zinc-700',
  'HALF-WIN':  'bg-teal-500/10 text-teal-400 border border-teal-500/30',
  'HALF-LOSS': 'bg-orange-500/10 text-orange-400 border border-orange-500/30',
}
const RESULT_LBL: Record<string, string> = {
  GREEN: 'GREEN', RED: 'RED', PUSH: 'PUSH', 'HALF-WIN': '½ WIN', 'HALF-LOSS': '½ LOSS',
}
const SOURCE_CLS: Record<string, string> = {
  vip:         'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  free:        'text-green-400 bg-green-500/10 border-green-500/20',
  multipla:    'text-blue-400 bg-blue-400/10 border-blue-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
}
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

// ─── Tabela padronizada de picks ──────────────────────────────────────────────
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
          const homeSrc = p.homeId ? `/api/proxy/team/${p.homeId}.png` : null
          const awaySrc = p.awayId ? `/api/proxy/team/${p.awayId}.png` : null
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
                    <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${SOURCE_CLS[pt] ?? ''}`}>
                      {SOURCE_LBL[pt] ?? pt}
                    </span>
                  )}
                  {homeSrc && <img src={homeSrc} alt="" className="w-4 h-4 object-contain shrink-0" onError={e => (e.currentTarget.style.display = 'none')} />}
                  <span className="text-sm font-semibold text-white truncate">{p.homeName}</span>
                  {p.awayName && (
                    <>
                      <span className="text-zinc-600 text-xs shrink-0">vs</span>
                      <span className="text-sm font-semibold text-white truncate">{p.awayName}</span>
                      {awaySrc && <img src={awaySrc} alt="" className="w-4 h-4 object-contain shrink-0" onError={e => (e.currentTarget.style.display = 'none')} />}
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
                {p.result ? (
                  <span className={`text-xs font-black px-2 py-0.5 rounded-lg ${RESULT_CLS[p.result] ?? 'text-zinc-500'}`}>
                    {RESULT_LBL[p.result] ?? p.result}
                  </span>
                ) : (
                  <span className="text-xs font-black px-2 py-0.5 rounded-lg text-yellow-400 bg-yellow-400/10 border border-yellow-400/20">
                    Pendente
                  </span>
                )}
                {p.profit != null ? (
                  <span className={`text-sm font-black w-14 text-right ${p.profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                    {p.profit >= 0 ? '+' : ''}{p.isMonetary ? 'R$' : ''}{Math.abs(p.profit).toFixed(2)}{!p.isMonetary ? 'u' : ''}
                  </span>
                ) : (
                  <span className="text-sm font-black w-14 text-right text-zinc-700">—</span>
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

// ─── VIP Lock Overlay ─────────────────────────────────────────────────────────
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

// ─── Ao Vivo ─────────────────────────────────────────────────────────────────
const LIVE_SET = new Set(['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'])
const STATUS_LABEL: Record<string, string> = {
  NS: 'Não iniciado', '1H': '1º Tempo', HT: 'Intervalo',
  '2H': '2º Tempo', ET: 'Prorrogação', FT: 'Encerrado',
  AET: 'Encerrado', CANC: 'Cancelado', PST: 'Adiado', SUSP: 'Suspenso',
}

function StatBar({ currentVal, lineVal, direction }: {
  currentVal: number; lineVal: number; direction: 'over' | 'under'
}) {
  const maxVal    = Math.max(lineVal * 1.7, currentVal * 1.1 + 1)
  const linePos   = Math.min((lineVal / maxVal) * 100, 98)
  const fillPos   = Math.min((currentVal / maxVal) * 100, 100)
  const winning   = direction === 'over' ? currentVal > lineVal : currentVal < lineVal
  const fillColor = winning ? '#22c55e' : '#ef4444'

  return (
    <div className="relative h-2 bg-zinc-700/60 rounded-full mt-3 mb-4">
      <div className="absolute left-0 top-0 h-full rounded-full transition-all duration-700"
        style={{ width: `${fillPos}%`, backgroundColor: fillColor }} />
      <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-white/50 rounded"
        style={{ left: `${linePos}%` }} />
      <div className="absolute -top-5 text-[10px] font-black text-white/70"
        style={{ left: `${linePos}%`, transform: 'translateX(-50%)' }}>
        {lineVal}
      </div>
      <div className="absolute -bottom-5 text-[10px] font-black"
        style={{ left: `${Math.min(fillPos, 95)}%`, transform: 'translateX(-50%)', color: fillColor }}>
        {currentVal}
      </div>
    </div>
  )
}

function LiveLeg({ leg }: { leg: any }) {
  const isLive  = LIVE_SET.has(leg.status)
  const legLineLc = leg.line?.toLowerCase() ?? ''
  const hasBar  = leg.current_val != null && leg.line_val != null &&
    (legLineLc.startsWith('over') || legLineLc.startsWith('mais') ||
     legLineLc.startsWith('under') || legLineLc.startsWith('menos'))
  const direction: 'over' | 'under' = (leg.line || '').toLowerCase().startsWith('under') ||
    (leg.line || '').toLowerCase().startsWith('menos') ? 'under' : 'over'
  const stColor = leg.pick_status === 'winning' ? 'text-green-400'
    : leg.pick_status === 'losing' ? 'text-red-400' : 'text-zinc-400'

  return (
    <div className="bg-zinc-800/60 rounded-lg p-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <TeamLogo id={leg.home_team_id} name={leg.home_team || ''} size={14} />
          <span className="text-xs text-zinc-300 truncate">{leg.home_team}</span>
          <span className="text-zinc-600 text-xs shrink-0">vs</span>
          <span className="text-xs text-zinc-300 truncate">{leg.away_team}</span>
          <TeamLogo id={leg.away_team_id} name={leg.away_team || ''} size={14} />
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-2">
          {isLive && leg.elapsed && (
            <span className="text-[9px] font-black text-green-400 animate-pulse">{leg.elapsed}'</span>
          )}
          {leg.status !== 'NS' && (
            <span className="text-sm font-black text-white tabular-nums">
              {leg.home_goals} – {leg.away_goals}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-500 truncate">{leg.market} · {leg.line}</span>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {leg.current_val != null && (
            <span className={`font-black ${stColor}`}>
              {leg.stat_label}: {leg.current_val}
            </span>
          )}
          {leg.is_locked && leg.pick_status === 'winning' && (
            <span className="text-[9px] font-black text-green-400 bg-green-400/15 border border-green-500/30 px-1.5 py-0.5 rounded">
              GARANTIDO
            </span>
          )}
          {leg.is_locked && leg.pick_status === 'losing' && (
            <span className="text-[9px] font-black text-red-400 bg-red-400/15 border border-red-500/30 px-1.5 py-0.5 rounded">
              PERDIDO
            </span>
          )}
        </div>
      </div>
      {hasBar && !leg.is_locked && (
        <StatBar currentVal={leg.current_val} lineVal={leg.line_val} direction={direction} />
      )}
    </div>
  )
}

function LivePickCard({ pick }: { pick: any }) {
  const isLive  = pick.is_live
  const isMulti = pick.pick_type === 'multipla' || pick.pick_type === 'alavancagem'
  const lineLc  = pick.line?.toLowerCase() ?? ''
  const hasBar  = !isMulti && pick.current_val != null && pick.line_val != null &&
    (lineLc.startsWith('over') || lineLc.startsWith('mais') ||
     lineLc.startsWith('under') || lineLc.startsWith('menos'))
  const direction: 'over' | 'under' = (pick.line || '').toLowerCase().startsWith('under') ||
    (pick.line || '').toLowerCase().startsWith('menos') ? 'under' : 'over'
  const stColor = pick.pick_status === 'winning' ? 'text-green-400'
    : pick.pick_status === 'losing' ? 'text-red-400' : 'text-zinc-400'
  const typeCls: Record<string, string> = {
    vip:        'text-yellow-400 bg-yellow-400/10',
    free:       'text-green-400 bg-green-400/10',
    multipla:   'text-blue-400 bg-blue-400/10',
    alavancagem:'text-orange-400 bg-orange-400/10',
  }
  const typeLabel: Record<string, string> = {
    vip: 'VIP', free: 'FREE', multipla: 'MÚLT.', alavancagem: 'ALAV.',
  }

  return (
    <div className={`rounded-xl border p-4 transition-colors ${isLive ? 'border-green-500/25 bg-zinc-900' : 'border-zinc-800 bg-zinc-900/60'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded ${typeCls[pick.pick_type] ?? 'text-zinc-400 bg-zinc-700/50'}`}>
            {typeLabel[pick.pick_type] ?? pick.pick_type}
          </span>
          <span className="text-xs text-zinc-500">Odd {Number(pick.odd).toFixed(2)}</span>
          <span className="text-xs text-zinc-600">· {pick.stake_units}u</span>
        </div>
        {isLive ? (
          <span className="flex items-center gap-1 text-[9px] font-black text-red-400 bg-red-400/10 border border-red-500/20 px-2 py-0.5 rounded-full tracking-wide">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse shrink-0" />
            AO VIVO
          </span>
        ) : (
          <span className="text-[10px] text-zinc-600 uppercase tracking-wide">
            {STATUS_LABEL[pick.status] ?? pick.status ?? 'Aguardando'}
          </span>
        )}
      </div>

      {isMulti ? (
        <div className="space-y-2">
          {(pick.legs ?? []).map((leg: any, i: number) => (
            <LiveLeg key={i} leg={leg} />
          ))}
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <TeamLogo id={pick.home_team_id} name={pick.home_team || ''} size={20} />
            <span className="text-sm font-semibold text-white">{pick.home_team}</span>
            {pick.status !== 'NS' && (
              <span className="text-sm font-black text-white tabular-nums mx-1">
                {pick.home_goals} – {pick.away_goals}
              </span>
            )}
            <span className="text-sm font-semibold text-white">{pick.away_team}</span>
            <TeamLogo id={pick.away_team_id} name={pick.away_team || ''} size={20} />
            {isLive && pick.elapsed && (
              <span className="text-[10px] font-black text-green-400 ml-auto animate-pulse">{pick.elapsed}'</span>
            )}
          </div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-zinc-500">{pick.market} · {pick.line}</span>
            <div className="flex items-center gap-1.5 shrink-0 ml-2">
              {pick.current_val != null && (
                <span className={`font-black ${stColor}`}>
                  {pick.stat_label}: {pick.current_val}
                </span>
              )}
              {pick.is_locked && pick.pick_status === 'winning' && (
                <span className="text-[9px] font-black text-green-400 bg-green-400/15 border border-green-500/30 px-1.5 py-0.5 rounded">
                  GARANTIDO
                </span>
              )}
              {pick.is_locked && pick.pick_status === 'losing' && (
                <span className="text-[9px] font-black text-red-400 bg-red-400/15 border border-red-500/30 px-1.5 py-0.5 rounded">
                  PERDIDO
                </span>
              )}
            </div>
          </div>
          {hasBar && !pick.is_locked && (
            <StatBar currentVal={pick.current_val} lineVal={pick.line_val} direction={direction} />
          )}
        </>
      )}
    </div>
  )
}

function LivePicks() {
  const [picks, setPicks]         = useState<any[]>([])
  const [loading, setLoading]     = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  const load = useCallback(() => {
    api.get('/live/my-picks')
      .then(r => { setPicks(r.data); setLastUpdate(new Date()) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [load])

  if (loading && picks.length === 0) {
    return <div className="text-center py-16"><Spinner /></div>
  }

  const live    = picks.filter(p => p.is_live)
  const pending = picks.filter(p => !p.is_live)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-xs text-zinc-500 leading-relaxed max-w-sm">
          Picks que você apostou — acompanhe ao vivo. Atualiza automaticamente a cada 60s.
        </p>
        {lastUpdate && (
          <button onClick={load}
            className="text-xs text-green-500 hover:underline shrink-0 ml-4">
            Atualizar
          </button>
        )}
      </div>

      {picks.length === 0 ? (
        <div className="card p-10 text-center border-dashed">
          <div className="flex justify-center mb-3">
              <svg className="w-10 h-10 text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12 20.25h.008v.008H12v-.008z" />
              </svg>
            </div>
          <p className="font-semibold text-zinc-400">Nenhum pick ativo</p>
          <p className="text-sm text-zinc-600 mt-1">Clique em "Apostei" em qualquer pick para acompanhar aqui.</p>
        </div>
      ) : (
        <>
          {live.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                <span className="text-xs font-black text-red-400 uppercase tracking-widest">Ao Vivo</span>
              </div>
              <div className="space-y-3">
                {live.map(p => <LivePickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} />)}
              </div>
            </div>
          )}
          {pending.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-zinc-600 rounded-full" />
                <span className="text-xs font-black text-zinc-500 uppercase tracking-widest">Aguardando / Hoje</span>
              </div>
              <div className="space-y-3">
                {pending.map(p => <LivePickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} />)}
              </div>
            </div>
          )}
        </>
      )}

      {lastUpdate && (
        <p className="text-center text-[10px] text-zinc-700">
          Última atualização: {lastUpdate.toLocaleTimeString('pt-BR')}
        </p>
      )}
    </div>
  )
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const navigate = useNavigate()
  const { user, isVip, isAdmin, daysUntilExpiry } = useAuth()
  const canSeeVip = isVip || isAdmin
  const { hasNew, markSeen } = useNotifications()

  const [tab, setTab]               = useState<Tab>('hoje')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedPickType, setSelectedPickType] = useState<string>('vip')

  const openDetail = (id: number, pickType = 'vip') => {
    setSelectedId(id)
    setSelectedPickType(pickType)
  }

  // Dados de hoje (free + VIP rápido)
  const [today, setToday]         = useState<any>(null)
  const [todayLoading, setTodayLoading] = useState(true)

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
  const [bancaSummary, setBancaSummary] = useState<{ has_banca: boolean; bankroll_current: number; unit_value: number } | null>(null)

  const [quickStats, setQuickStats] = useState<any>(null)
  const [recentResults, setRecentResults] = useState<any[]>([])
  const todayLabel   = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', timeZone: 'America/Sao_Paulo' })
  const todayDateStr = new Date().toLocaleDateString('pt-BR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'America/Sao_Paulo' })

  useEffect(() => {
    api.get('/suggestions/today')
      .then(r => setToday(r.data))
      .catch(() => {})
      .finally(() => setTodayLoading(false))
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
    api.get('/banca/summary').then(r => setBancaSummary(r.data)).catch(() => {})
  }, [canSeeVip])

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
    try {
      await api.put('/banca/alavancagem-init', { bankroll_init: val })
      const r = await api.get('/banca/alavancagem-serie')
      setUserAlavSerie(r.data)
      setAlavInitInput('')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Erro ao salvar')
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
      {selectedId && <SuggestionDetail id={selectedId} pickType={selectedPickType} onClose={() => setSelectedId(null)} />}
      <Navbar />

      {/* Cabeçalho */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-base font-black text-white tracking-tight">Picks</h1>
            <p className="text-zinc-500 text-xs capitalize mt-0.5">{todayLabel}</p>
          </div>
          <div className="flex items-center gap-4">
            {quickStats && (
              <div className="hidden sm:flex items-center gap-3 text-xs">
                <span className="text-zinc-600">Win rate mensal</span>
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
        {/* Greeting do usuário */}
        <UserGreeting user={user} isVip={isVip} isAdmin={isAdmin} daysUntilExpiry={daysUntilExpiry} />

        <TabBar
          tab={tab}
          setTab={setTab}
          canSeeVip={canSeeVip}
          counts={{
            vip:         (today?.vip ?? []).filter((s: any) => !s.result).length || undefined,
            multiplas:   (today?.multiplas ?? []).filter((m: any) => !m.result).length || undefined,
            alavancagem: today?.alavancagem && !today.alavancagem.result ? 1 : undefined,
          }}
        />

        {/* ── HOJE ─────────────────────────────────────────────────────────── */}
        {tab === 'hoje' && (
          todayLoading ? <Spinner /> : (
            <div className="space-y-8">

              {/* Resumo das bancas — visível para VIPs */}
              {canSeeVip && (bancaSummary || userAlavSerie) && (
                <div className="grid grid-cols-2 gap-3">
                  {/* Banca Geral */}
                  <div className={`rounded-xl border p-3.5 ${bancaSummary?.has_banca ? 'bg-zinc-900 border-zinc-800' : 'bg-zinc-900/50 border-dashed border-zinc-800'}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold">Banca Geral</span>
                      {!bancaSummary?.has_banca && (
                        <span className="text-[10px] text-yellow-500 font-bold">Não configurada</span>
                      )}
                    </div>
                    {bancaSummary?.has_banca ? (
                      <>
                        <div className="text-xl font-black text-white">R${Number(bancaSummary.bankroll_current).toFixed(2)}</div>
                        <div className="text-[11px] text-zinc-600 mt-0.5">{bancaSummary.unit_value ? `1u = R$${Number(bancaSummary.unit_value).toFixed(2)}` : '—'}</div>
                      </>
                    ) : (
                      <p className="text-xs text-zinc-600 mt-1"><a href="/banca" className="text-green-400 underline font-semibold">Configurar banca</a></p>
                    )}
                  </div>
                  {/* Banca Alavancagem */}
                  <div className={`rounded-xl border p-3.5 ${userAlavSerie?.configured ? 'bg-zinc-900 border-orange-500/20' : 'bg-zinc-900/50 border-dashed border-zinc-800'}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold">Alavancagem</span>
                      {!userAlavSerie?.configured && (
                        <span className="text-[10px] text-yellow-500 font-bold">Não configurada</span>
                      )}
                    </div>
                    {userAlavSerie?.configured ? (
                      <>
                        <div className="text-xl font-black text-orange-400">R${Number(userAlavSerie.current_bankroll).toFixed(2)}</div>
                        <div className="text-[11px] text-zinc-600 mt-0.5">
                          início R${Number(userAlavSerie.initial_bankroll).toFixed(2)}
                          {userAlavSerie.current_bankroll > userAlavSerie.initial_bankroll && (
                            <span className="text-green-400 ml-1">+R${(userAlavSerie.current_bankroll - userAlavSerie.initial_bankroll).toFixed(2)}</span>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-xs text-zinc-600 mt-1">Configure na aba <button onClick={() => setTab('alavancagem')} className="text-orange-400 underline">Alavancagem</button></p>
                    )}
                  </div>
                </div>
              )}

              {/* Stats rápidas do mês — para todos */}
              <QuickStats stats={quickStats} />

              {/* Pick do Dia — visível para todos */}
              <section>
                <SectionHeader color="bg-green-500" label="Pick do Dia" />
                {today?.dica_do_dia
                  ? <PickSeguroCard dica={today.dica_do_dia} compact onClick={() => openDetail(today.dica_do_dia.id, 'free')} banca={bancaSummary?.has_banca ? bancaSummary : null} />
                  : <PickSeguroEmpty />
                }
              </section>


              {/* PICKS VIP DO DIA — apenas pendentes */}
              {canSeeVip && (() => {
                const pending = (today?.vip ?? []).filter((s: any) => !s.result)
                return (
                  <section>
                    <SectionHeader
                      color="bg-yellow-400"
                      label="Picks VIP do Dia"
                      badge={pending.length ? `${pending.length} pendente${pending.length > 1 ? 's' : ''}` : undefined}
                    />
                    {pending.length > 0 ? (
                      <>
                        <div className="grid gap-4 md:grid-cols-2">
                          {pending.slice(0, 4).map((s: any) => (
                            <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} banca={bancaSummary?.has_banca ? bancaSummary : null} />
                          ))}
                        </div>
                        {pending.length > 4 && (
                          <button
                            onClick={() => setTab('vip')}
                            className="mt-4 w-full text-center text-xs text-green-500 hover:text-green-400 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700"
                          >
                            Ver todos os {pending.length} picks pendentes →
                          </button>
                        )}
                      </>
                    ) : today?.vip?.length > 0 ? (
                      <div className="card p-6 text-center border-dashed">
                        <p className="text-zinc-500 text-sm font-semibold">Todos os picks de hoje já foram resolvidos.</p>
                        <p className="text-zinc-600 text-xs mt-1">Confira os resultados abaixo.</p>
                      </div>
                    ) : (
                      <div className="card p-8 text-center border-dashed">
                        <p className="text-zinc-600 text-sm">Nenhum pick VIP gerado para hoje ainda.</p>
                      </div>
                    )}
                  </section>
                )
              })()}

              {/* Múltiplas de hoje */}
              {canSeeVip && today?.multiplas?.length > 0 && (
                <section>
                  <SectionHeader color="bg-blue-400" label="Múltipla do Dia" />
                  <div className="grid gap-4 md:grid-cols-2">
                    {today.multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} banca={bancaSummary?.has_banca ? bancaSummary : null} />)}
                  </div>
                </section>
              )}

              {/* Alavancagem de hoje */}
              {canSeeVip && today?.alavancagem && (
                <section>
                  <SectionHeader color="bg-orange-400" label="Alavancagem" badge="VIP" />
                  <div className="card p-4 border-orange-500/10 bg-orange-500/5 mb-3">
                    <p className="text-xs text-zinc-400 leading-relaxed">
                      Banca composta: começa em{' '}
                      <span className="text-orange-400 font-bold">
                        {userAlavSerie?.configured ? `R$${userAlavSerie.initial_bankroll.toFixed(2)}` : 'sua banca cadastrada'}
                      </span>{' '}
                      e reinveste o lucro a cada GREEN. Reset automático no RED. Odds alvo ~1.50.
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
                    Ver histórico da série →
                  </button>
                </section>
              )}


            </div>
          )
        )}

        {/* ── PICKS FREE ───────────────────────────────────────────────────── */}
        {tab === 'pick_seguro' && (
          <div className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-green-500/20 bg-green-500/5">
              <p className="text-xs font-black text-green-400 uppercase tracking-widest mb-3">O que é o Pick do Dia Free?</p>
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
              Ver todos os resultados →
            </button>
          </div>
        )}

        {/* ── PICKS VIP ────────────────────────────────────────────────────── */}
        {tab === 'vip' && (
          <div className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-yellow-400/20 bg-yellow-400/5">
              <p className="text-xs font-black text-yellow-400 uppercase tracking-widest mb-3">O que são os Picks VIP?</p>
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
                const pending = (today?.vip ?? []).filter((s: any) => !s.result)
                return (
                  <>
                    {pending.length > 0 ? (
                      <>
                        <div className="grid gap-4 md:grid-cols-2">
                          {pending.slice(0, 4).map((s: any) => (
                            <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} banca={bancaSummary?.has_banca ? bancaSummary : null} />
                          ))}
                        </div>
                        {pending.length > 4 && (
                          <p className="text-xs text-zinc-600 text-center mt-2">+{pending.length - 4} picks disponíveis</p>
                        )}
                      </>
                    ) : today?.vip?.length > 0 ? (
                      <div className="card p-6 text-center border-dashed">
                        <p className="text-zinc-500 text-sm font-semibold">Todos os picks de hoje já foram resolvidos.</p>
                        <p className="text-zinc-600 text-xs mt-1">Confira os resultados abaixo.</p>
                      </div>
                    ) : (
                      <div className="card p-8 text-center border-dashed">
                        <p className="text-zinc-500 text-sm font-semibold">Picks VIP do dia ainda não gerados.</p>
                        <p className="text-zinc-600 text-xs mt-1">Os picks saem pela manhã. Volte mais tarde.</p>
                      </div>
                    )}
                  </>
                )
              })()}
            </div>


            <button onClick={() => navigate('/results')}
              className="w-full text-center text-xs text-yellow-400 hover:text-yellow-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700 font-semibold">
              Ver todos os resultados →
            </button>
          </div>
        )}

        {/* ── MÚLTIPLAS ────────────────────────────────────────────────────── */}
        {tab === 'multiplas' && (
          <div className="space-y-6">
            {/* O que é */}
            <div className="card p-5 border-blue-400/20 bg-blue-400/5">
              <p className="text-xs font-black text-blue-400 uppercase tracking-widest mb-3">O que são as Múltiplas VIP?</p>
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
              Ver todos os resultados →
            </button>
          </div>
        )}

        {/* ── PICKS COPA (ALAVANCAGEM) ─────────────────────────────────────── */}
        {tab === 'alavancagem' && (
          <div className="space-y-6">
            {/* Como funciona */}
            <div className="card p-5 border-orange-500/20 bg-orange-500/5">
              <p className="text-xs font-black text-orange-400 uppercase tracking-widest mb-3">Como funciona a Alavancagem?</p>
              <div className="space-y-2 text-sm text-zinc-400 leading-relaxed">
                <p>
                  A banca começa em <span className="text-white font-bold">R$50</span> e o lucro de cada GREEN é
                  reinvestido integralmente na próxima aposta — sem retirar nada.
                </p>
                <p>
                  A cada <span className="text-red-400 font-bold">RED</span>, a banca reseta para R$50 e uma nova
                  série começa do zero. A IA seleciona 1 pick (ou combinada de 2 com alta correlação)
                  com <span className="text-white font-bold">odd alvo ~1.50</span> para maximizar a consistência.
                </p>
                <p>
                  O objetivo é <span className="text-green-400 font-bold">encadear greens consecutivos</span> e multiplicar
                  a banca progressivamente durante o torneio. Uma sequência de 5 greens transforma R$50 em mais de R$300.
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                  {[
                    { label: 'Banca inicial', value: 'R$50',   color: 'text-orange-400' },
                    { label: 'Odd alvo',      value: '~1.50',  color: 'text-green-400'  },
                    { label: 'Reset no RED',  value: 'R$50',   color: 'text-red-400'    },
                    { label: '5 greens',      value: '~R$300', color: 'text-white'      },
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
                {/* Config banca Copa alavancagem */}
                <div className="card p-5 border-orange-500/20">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="text-xs font-black text-orange-400 uppercase tracking-widest">Banca Copa Alavancagem</p>
                      <p className="text-xs text-zinc-500 mt-0.5">Separada da sua banca principal — reinveste a cada GREEN, reseta no RED</p>
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
                        <p className="text-zinc-600 text-xs mt-1">Nenhum pick de alavancagem disponível para hoje.</p>
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
                              value: userBankroll != null ? `R$${userBankroll.toFixed(2)}` : '—',
                              color: userBankroll != null && userBankroll > initialBankroll ? 'text-green-400' : 'text-orange-400',
                              sub: userBankroll != null && userBankroll > initialBankroll ? `+R$${(userBankroll - initialBankroll).toFixed(2)}` : userAlavSerie?.configured ? 'Início da série' : 'Cadastre sua banca',
                            },
                            { label: 'Resets (RED)', value: String(resets), color: resets > 0 ? 'text-red-400' : 'text-zinc-500', sub: resets === 0 ? 'Nenhum ainda' : `${resets} reinício${resets > 1 ? 's' : ''}` },
                            { label: 'Série Atual', value: currentStreak > 0 ? `${currentStreak} green${currentStreak > 1 ? 's' : ''}` : '—', color: currentStreak >= 3 ? 'text-green-400' : currentStreak > 0 ? 'text-green-500' : 'text-zinc-500', sub: currentStreak > 0 ? 'seguidos' : 'Aguardando' },
                            { label: 'Melhor Série', value: bestStreak > 0 ? `${bestStreak} green${bestStreak > 1 ? 's' : ''}` : '—', color: 'text-yellow-400', sub: bestStreak > 0 ? 'recorde da série' : 'Ainda sem greens' },
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
                          ? new Date(pick.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                          : '—'
                        const bankBefore = pick.bankroll_before
                        const bankAfter  = pick.bankroll_after
                        return (
                          <div key={pick.id} className="flex gap-3">
                            <div className="flex flex-col items-center w-8 shrink-0">
                              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-black border ${
                                !res
                                  ? 'bg-orange-500 border-orange-400 text-black'
                                  : res === 'GREEN' ? 'bg-green-500/20 border-green-500/40 text-green-400'
                                  : 'bg-red-500/20 border-red-500/40 text-red-400'
                              }`}>
                                {res === 'GREEN' ? '✓' : res === 'RED' ? '✗' : '⏳'}
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
                                    {pick.home_team_id_1 && (
                                      <img src={`/api/proxy/team/${pick.home_team_id_1}.png`}
                                        alt="" className="w-3.5 h-3.5 object-contain shrink-0"
                                        onError={e => (e.currentTarget.style.display = 'none')} />
                                    )}
                                    <span className="text-xs font-bold text-white truncate">{pick.home_team_1}</span>
                                    <span className="text-zinc-600 text-[10px]">vs</span>
                                    {pick.away_team_id_1 && (
                                      <img src={`/api/proxy/team/${pick.away_team_id_1}.png`}
                                        alt="" className="w-3.5 h-3.5 object-contain shrink-0"
                                        onError={e => (e.currentTarget.style.display = 'none')} />
                                    )}
                                    <span className="text-xs font-bold text-white truncate">{pick.away_team_1}</span>
                                  </div>
                                  <div className="text-[10px] text-zinc-500">{date}</div>
                                </div>
                                <div className="text-right shrink-0">
                                  {bankBefore != null && (
                                    <div className="text-[10px] text-zinc-600">R${Number(bankBefore).toFixed(0)}</div>
                                  )}
                                  {bankAfter != null && (
                                    <div className={`text-xs font-black ${res === 'GREEN' ? 'text-green-400' : 'text-red-400'}`}>
                                      → R${Number(bankAfter).toFixed(0)}
                                    </div>
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
              Ver todos os resultados →
            </button>
          </div>
        )}
        {/* ── AO VIVO ──────────────────────────────────────────────────────── */}
        {tab === 'aovivo' && <LivePicks />}

        {/* ── CHAT COMUNIDADE ──────────────────────────────────────────────── */}
        {tab === 'chat' && (
          <div className="max-w-2xl mx-auto">
            <div className="mb-4">
              <p className="text-xs text-zinc-500 leading-relaxed">
                Chat em tempo real da comunidade Pick<span className="text-green-500">IA</span>.
                Discuta picks, compartilhe análises e conecte-se com outros apostadores.
              </p>
            </div>
            <CommunityChat />
          </div>
        )}

      </main>
      <Footer />
    </div>
  )
}
