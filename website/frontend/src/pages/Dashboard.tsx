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

// ─── Helpers de logo ──────────────────────────────────────────────────────────
const TEAM_LOGO   = (id?: number) => id ? `https://media.api-sports.io/football/teams/${id}.png` : null
const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id?: number) =>
  id ? (LOCAL_LEAGUE_LOGOS[id] ?? `https://media.api-sports.io/football/leagues/${id}.png`) : null

function TeamLogo({ id, name, size = 24 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size}
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} loading="lazy" />
  )
}

function LeagueLogo({ id, name, size = 18 }: { id?: number; name?: string; size?: number }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={size} height={size}
      className="object-contain shrink-0 opacity-80" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} loading="lazy" />
  )
}

// ─── Tipos ────────────────────────────────────────────────────────────────────
type Tab = 'hoje' | 'pick_seguro' | 'vip' | 'multiplas' | 'alavancagem' | 'chat'

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
    { key: 'chat',         label: 'Comunidade'       },
  ]

  return (
    <div className="flex border-b border-zinc-800 mb-6 -mx-4 px-4 overflow-x-auto">
      {tabs.map(t => {
        const count = counts?.[t.key]
        return (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-3 text-sm font-semibold border-b-2 transition-colors mr-1 whitespace-nowrap ${
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
      <Link to="/profile" className="shrink-0 text-zinc-600 hover:text-zinc-400 transition-colors text-xs border border-zinc-800 hover:border-zinc-700 px-3 py-2 rounded-lg hidden sm:block">
        Editar perfil
      </Link>
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
function PickSeguroCard({ dica, compact = false, onClick }: { dica: any; compact?: boolean; onClick?: () => void }) {
  const pct = Math.round((dica.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState(dica.is_followed ?? false)
  const [following, setFollowing] = useState(false)

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    setFollowing(true)
    try {
      await api.post('/banca/follow', {
        pick_id: dica.id,
        pick_type: 'free',
        stake_units: 1,
      })
      setFollowed(true)
    } catch { /* ignora */ } finally {
      setFollowing(false)
    }
  }

  return (
    <div
      className={`relative overflow-hidden card p-5 border-green-500/20 transition-all duration-200 ${onClick ? 'hover:border-zinc-600 hover:bg-zinc-900/80 cursor-pointer group' : ''}`}
      onClick={onClick}
    >
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-green-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <LeagueLogo id={dica.league_id} name={dica.league_name} />
          <span className="text-xs text-zinc-500">{dica.league_name}</span>
        </div>
        {dica.result
          ? <span className={dica.result === 'GREEN' ? 'badge-green' : 'badge-red'}>{dica.result}</span>
          : <span className="badge-free">FREE</span>
        }
      </div>

      {/* Times com logos */}
      <div className="flex items-center gap-2 mb-4">
        <TeamLogo id={dica.home_team_id} name={dica.home_team ?? ''} size={28} />
        <span className="font-bold text-white text-sm truncate">{dica.home_team}</span>
        <span className="text-zinc-600 text-xs shrink-0">vs</span>
        <span className="font-bold text-white text-sm truncate">{dica.away_team}</span>
        <TeamLogo id={dica.away_team_id} name={dica.away_team ?? ''} size={28} />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-5 gap-2 mb-4">
        <div className="bg-zinc-800 rounded-lg p-2 col-span-2">
          <div className="text-xs text-zinc-500 mb-0.5">Tipo</div>
          <div className="text-sm font-semibold text-white truncate">{dica.market}</div>
        </div>
        <div className="bg-zinc-800 rounded-lg p-2 text-center">
          <div className="text-xs text-zinc-500 mb-0.5">Linha</div>
          <div className="text-sm font-bold text-white truncate">{dica.line ?? '—'}</div>
        </div>
        <div className="bg-zinc-800 rounded-lg p-2 text-center">
          <div className="text-xs text-zinc-500 mb-0.5">Odd</div>
          <div className="text-base font-black text-green-500">{Number(dica.odd).toFixed(2)}</div>
        </div>
        <div className="bg-zinc-800 rounded-lg p-2 text-center">
          <div className="text-xs text-zinc-500 mb-0.5">Stake</div>
          <div className="text-sm font-bold text-white">1u</div>
        </div>
      </div>

      {/* Confiança */}
      <div className="flex justify-between text-xs mb-1">
        <span className="text-zinc-500">Confiança</span>
        <span className={pct >= 75 ? 'text-green-500 font-bold' : 'text-zinc-400'}>{pct}%</span>
      </div>
      <div className="bg-zinc-800 rounded-full h-1.5 overflow-hidden mb-3">
        <div
          className={`h-1.5 rounded-full transition-all ${pct >= 75 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-zinc-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {!compact && dica.reasoning && (
        <p className="text-xs text-zinc-500 leading-relaxed line-clamp-2 mb-3">{dica.reasoning}</p>
      )}

      {/* Footer: Apostei + Ver detalhes */}
      <div className="flex items-center justify-between">
        {!dica.result && (
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
        )}
        {onClick && (
          <p className="text-xs text-zinc-700 group-hover:text-zinc-500 transition-colors ml-auto">
            Ver detalhes →
          </p>
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
function MultiplaCard({ m, onClick }: { m: any; onClick?: () => void }) {
  let legs: any[] = []
  try { legs = typeof m.legs === 'string' ? JSON.parse(m.legs) : (m.legs ?? []) } catch { legs = [] }

  const pct = Math.round((m.confidence ?? 0) * 100)
  const [followed, setFollowed] = useState<boolean>(!!m.is_followed)
  const [following, setFollowing] = useState(false)

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (following) return
    setFollowing(true)
    try {
      await api.post('/banca/follow', { pick_id: m.id, pick_type: 'multipla' })
      setFollowed(true)
    } catch {
      setFollowed(false)
    } finally {
      setFollowing(false)
    }
  }

  return (
    <div className="card p-5 cursor-pointer" onClick={onClick}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-xs font-black text-zinc-300 uppercase tracking-wider">Múltipla</p>
            <span className="badge-vip">VIP</span>
          </div>
          <p className="text-xs text-zinc-600">
            {new Date(m.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long' })}
            {' · '}{legs.length} seleções
          </p>
        </div>
        <div className="flex items-center gap-3">
          {m.result && (
            <span className={m.result === 'GREEN' ? 'badge-green' : 'badge-red'}>{m.result}</span>
          )}
          <div className="text-right">
            <div className="text-green-400 font-black text-2xl">{Number(m.total_odd).toFixed(2)}</div>
            <div className="text-xs text-zinc-600">odd total</div>
          </div>
        </div>
      </div>

      {/* Legs */}
      {legs.length > 0 && (
        <div className="space-y-1.5 mb-4">
          {legs.map((leg: any, i: number) => (
            <div key={i} className="flex items-center gap-2 bg-zinc-800/50 rounded-lg px-3 py-2 text-xs">
              <span className="w-5 h-5 flex items-center justify-center bg-zinc-700 rounded-full text-zinc-400 font-bold shrink-0">
                {i + 1}
              </span>
              <TeamLogo id={leg.home_team_id} name={leg.home ?? leg.home_team ?? ''} size={18} />
              <div className="flex-1 min-w-0">
                <span className="text-zinc-300 font-medium truncate block">
                  {leg.home ?? leg.home_team} vs {leg.away ?? leg.away_team}
                </span>
                <span className="text-zinc-500">{leg.market}{leg.line ? <> · <span className="text-zinc-400">{leg.line}</span></> : ''}</span>
              </div>
              <TeamLogo id={leg.away_team_id} name={leg.away ?? leg.away_team ?? ''} size={18} />
              <span className="text-green-400 font-black shrink-0 ml-1">{Number(leg.odd).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Confidence + profit */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-zinc-500 mr-2">Confiança</span>
            <span className={pct >= 70 ? 'text-green-500 font-bold' : 'text-zinc-400'}>{pct}%</span>
          </div>
          <div className="bg-zinc-800 rounded-full h-1.5 w-24">
            <div
              className={`h-1.5 rounded-full ${pct >= 70 ? 'bg-green-500' : 'bg-zinc-500'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        {m.profit != null && (
          <span className={`text-lg font-black ${m.profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
            {m.profit >= 0 ? '+' : ''}{Number(m.profit).toFixed(2)}u
          </span>
        )}
      </div>

      {m.reasoning && (
        <p className="mb-3 text-xs text-zinc-500 leading-relaxed line-clamp-2">{m.reasoning}</p>
      )}

      {/* Footer actions */}
      <div className="flex items-center justify-between pt-3 border-t border-zinc-800">
        <button
          onClick={handleFollow}
          className={`text-xs font-bold px-3 py-1.5 rounded-lg transition-colors ${
            followed
              ? 'bg-green-500/20 text-green-400 border border-green-500/30'
              : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
          }`}
        >
          {followed ? 'Apostei' : '+ Apostei'}
        </button>
        <span className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
          Ver detalhes →
        </span>
      </div>
    </div>
  )
}

// ─── Alavancagem card ─────────────────────────────────────────────────────────
function AlavancagemCard({ pick, onClick }: { pick: any; onClick?: () => void }) {
  const isCombo        = pick.tipo === 'combinacao'
  const stake          = Number(pick.stake ?? pick.bankroll_before ?? 50)
  const potReturn      = Number(pick.potential_return ?? 0)
  const oddCombined    = Number(pick.odd_combined ?? 0)
  const confPct        = Math.round((pick.confidence_media ?? 0) * 100)
  const profit         = pick.profit != null ? Number(pick.profit) : null
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

  const legs = []
  if (pick.home_team_1) legs.push({ home: pick.home_team_1, away: pick.away_team_1, homeId: pick.home_team_id_1, awayId: pick.away_team_id_1, market: pick.market_1, line: pick.line_1, odd: pick.odd_1, house: pick.bet_house_1, reasoning: pick.reasoning_1 })
  if (isCombo && pick.home_team_2) legs.push({ home: pick.home_team_2, away: pick.away_team_2, homeId: pick.home_team_id_2, awayId: pick.away_team_id_2, market: pick.market_2, line: pick.line_2, odd: pick.odd_2, house: pick.bet_house_2, reasoning: pick.reasoning_2 })

  return (
    <div className="relative overflow-hidden card p-5 border-orange-500/20 cursor-pointer" onClick={onClick}>
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-orange-500 to-transparent" />

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-black text-orange-400 uppercase tracking-widest">Alavancagem</span>
          <span className="badge-vip">VIP</span>
          {isCombo && <span className="text-xs text-blue-400 border border-blue-400/20 bg-blue-400/10 px-2 py-0.5 rounded-md">Combinada</span>}
        </div>
        {pick.result
          ? <span className={pick.result === 'GREEN' ? 'badge-green' : 'badge-red'}>{pick.result}</span>
          : <span className="text-xs text-yellow-400 border border-yellow-400/20 bg-yellow-400/10 px-2 py-1 rounded-lg font-bold">Pendente</span>
        }
      </div>

      {/* Banca */}
      <div className="bg-zinc-900 rounded-xl p-3 mb-4 grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-xs text-zinc-500 mb-0.5">Stake</div>
          <div className="text-lg font-black text-orange-400">R${stake.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-xs text-zinc-500 mb-0.5">Odd</div>
          <div className="text-lg font-black text-green-400">{oddCombined.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-xs text-zinc-500 mb-0.5">Retorno</div>
          <div className="text-lg font-black text-white">R${potReturn.toFixed(2)}</div>
        </div>
      </div>

      {/* Legs */}
      <div className="space-y-2 mb-4">
        {legs.map((leg, i) => (
          <div key={i} className="bg-zinc-800/50 rounded-xl p-3">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <TeamLogo id={leg.homeId} name={leg.home ?? ''} size={20} />
                <span className="text-xs text-zinc-300 font-semibold truncate">{leg.home} vs {leg.away}</span>
                <TeamLogo id={leg.awayId} name={leg.away ?? ''} size={20} />
              </div>
              <span className="text-green-400 font-black shrink-0 ml-2">{Number(leg.odd).toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-white">{leg.market}{leg.line ? <> · <span className="text-zinc-400">{leg.line}</span></> : ''}</span>
              {leg.house && <span className="text-xs text-zinc-600">· {leg.house}</span>}
            </div>
            {leg.reasoning && <p className="text-xs text-zinc-500 mt-1 line-clamp-2">{leg.reasoning}</p>}
          </div>
        ))}
      </div>

      {/* Confiança + profit */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-zinc-500 mr-2">Confiança</span>
            <span className={confPct >= 75 ? 'text-green-500 font-bold' : 'text-zinc-400'}>{confPct}%</span>
          </div>
          <div className="bg-zinc-800 rounded-full h-1.5 w-24">
            <div className={`h-1.5 rounded-full ${confPct >= 75 ? 'bg-green-500' : 'bg-zinc-500'}`} style={{ width: `${confPct}%` }} />
          </div>
        </div>
        {profit != null && (
          <span className={`text-lg font-black ${profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
            {profit >= 0 ? '+' : ''}R${profit.toFixed(2)}
          </span>
        )}
      </div>

      {/* Footer actions */}
      <div className="flex items-center justify-between pt-3 border-t border-zinc-800">
        <button
          onClick={handleFollow}
          className={`text-xs font-bold px-3 py-1.5 rounded-lg transition-colors ${
            followed
              ? 'bg-green-500/20 text-green-400 border border-green-500/30'
              : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
          }`}
        >
          {followed ? 'Apostei' : '+ Apostei'}
        </button>
        <span className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
          Ver detalhes →
        </span>
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
    const f = legs[0]
    const label = f ? `${f.home ?? f.home_team}${legs.length > 1 ? ` +${legs.length - 1}` : ''}` : 'Múltipla'
    return { ...base,
      homeName: label, homeId: f?.home_team_id,
      odd: row.total_odd ? Number(row.total_odd) : undefined,
      profit: row.profit != null ? Number(row.profit) : undefined,
    }
  }
  if (pickType === 'alavancagem') return { ...base,
    homeName: row.home_team_1 ?? '',
    awayName: row.away_team_1 ?? '',
    homeId: row.home_team_id_1, awayId: row.away_team_id_1,
    market: row.market_1, line: row.line_1,
    odd: row.odd_combined ? Number(row.odd_combined) : row.odd_1 ? Number(row.odd_1) : undefined,
    isMonetary: true, profit: row.profit != null ? Number(row.profit) : undefined,
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
          const homeSrc = p.homeId ? `https://media.api-sports.io/football/teams/${p.homeId}.png` : null
          const awaySrc = p.awayId ? `https://media.api-sports.io/football/teams/${p.awayId}.png` : null
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
                  {p.awayName && pt !== 'multipla' && (
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

  const [quickStats, setQuickStats] = useState<any>(null)
  const [recentResults, setRecentResults] = useState<any[]>([])
  const todayLabel   = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', timeZone: 'America/Sao_Paulo' })
  const todayDateStr = new Date().toLocaleDateString('pt-BR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'America/Sao_Paulo' })

  useEffect(() => {
    api.get('/suggestions/today')
      .then(r => setToday(r.data))
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

              {/* Barra de status do plano */}
              {!isAdmin && daysUntilExpiry !== null && (isVip || user?.plan === 'trial') && (() => {
                const isTrial = user?.plan === 'trial'
                const totalDays = isTrial ? 2 : 30
                const pct = Math.max(0, Math.min(100, (daysUntilExpiry / totalDays) * 100))
                const isExpiring = isTrial ? daysUntilExpiry <= 1 : daysUntilExpiry <= 5
                const expiryDate = new Date(Date.now() + daysUntilExpiry * 24 * 3600000)
                const expiryStr = expiryDate.toLocaleDateString('pt-BR', { day: 'numeric', month: 'long' })
                return (
                  <div className={`card p-4 ${isExpiring ? 'border-red-500/30 bg-red-500/5' : ''}`}>
                    <div className="flex items-center gap-3">
                      <span className={`shrink-0 text-xs font-black px-2.5 py-1 rounded-full border ${isTrial ? 'text-green-400 bg-green-500/10 border-green-500/20' : 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'}`}>
                        {isTrial ? 'TESTE' : 'VIP'}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-xs text-zinc-500">
                            <span className={`font-black text-base ${isExpiring ? 'text-red-400' : 'text-white'}`}>{daysUntilExpiry}</span>
                            {' '}dia{daysUntilExpiry !== 1 ? 's' : ''} restante{daysUntilExpiry !== 1 ? 's' : ''}
                            <span className="text-zinc-700 ml-1.5">· expira {expiryStr}</span>
                          </span>
                          <Link to="/planos" className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors shrink-0 ml-3">
                            Ver plano →
                          </Link>
                        </div>
                        <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${isExpiring ? 'bg-red-500' : isTrial ? 'bg-green-500' : 'bg-yellow-400'}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                      {isExpiring && (
                        <Link to="/checkout" className="shrink-0 text-xs bg-yellow-400 text-black font-black py-1.5 px-3 rounded-lg hover:bg-yellow-300 transition-colors whitespace-nowrap">
                          Renovar →
                        </Link>
                      )}
                    </div>
                  </div>
                )
              })()}

              {/* Stats rápidas do mês — para todos */}
              <QuickStats stats={quickStats} />

              {/* Pick do Dia — visível para todos */}
              <section>
                <SectionHeader color="bg-green-500" label="Pick do Dia" />
                {today?.dica_do_dia
                  ? <PickSeguroCard dica={today.dica_do_dia} compact onClick={() => openDetail(today.dica_do_dia.id, 'free')} />
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
                            <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} />
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
                    {today.multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} />)}
                  </div>
                </section>
              )}

              {/* Alavancagem de hoje */}
              {canSeeVip && today?.alavancagem && (
                <section>
                  <SectionHeader color="bg-orange-400" label="Alavancagem" badge="VIP" />
                  <div className="card p-4 border-orange-500/10 bg-orange-500/5 mb-3">
                    <p className="text-xs text-zinc-400 leading-relaxed">
                      Banca composta: começa em <span className="text-orange-400 font-bold">R$50</span> e reinveste o lucro a cada GREEN.
                      Reset automático no RED. Odds alvo ~1.50 (faixa 1.40–1.60).
                    </p>
                  </div>
                  <AlavancagemCard pick={today.alavancagem} onClick={() => openDetail(today.alavancagem.id, 'alavancagem')} />
                  <button onClick={() => setTab('alavancagem')}
                    className="mt-3 w-full text-center text-xs text-orange-400 hover:text-orange-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700">
                    Ver histórico da série →
                  </button>
                </section>
              )}

              {/* ÚLTIMOS RESULTADOS — sempre no final */}
              {(canSeeVip || recentResults.length > 0) && (
                <section>
                  <SectionHeader color="bg-zinc-400" label="Últimos Resultados" />
                  {recentResults.length > 0 ? (
                    <PicksTable
                      rows={recentResults.slice(0, 6)}
                      pickType="mixed"
                      showSource
                      onOpen={openDetail}
                      footerAction={{ label: 'Ver histórico completo →', onClick: () => navigate('/results') }}
                    />
                  ) : (
                    <div className="card p-8 text-center border-dashed">
                      <p className="text-zinc-600 text-sm">Nenhum resultado disponível ainda.</p>
                    </div>
                  )}
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
                {today?.dica_do_dia ? <PickSeguroCard dica={today.dica_do_dia} onClick={() => openDetail(today.dica_do_dia.id, 'free')} /> : <PickSeguroEmpty />}
              </div>
            )}

            {/* Últimos 5 resultados */}
            {(() => {
              const last5 = recentResults.filter(r => r.pick_type === 'free').slice(0, 5)
              return (
                <div>
                  <SectionHeader color="bg-zinc-400" label="Últimos 5 Resultados" />
                  {last5.length > 0
                    ? <PicksTable rows={last5} pickType="free" onOpen={openDetail} />
                    : <div className="card p-8 text-center border-dashed"><p className="text-zinc-600 text-sm">Nenhum resultado disponível ainda.</p></div>
                  }
                </div>
              )
            })()}

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
                            <SuggestionCard key={s.id} s={s} onClick={() => openDetail(s.id, 'vip')} />
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

            {/* Últimos 5 resultados VIP */}
            {(() => {
              const last5 = recentResults.filter(r => r.pick_type === 'vip').slice(0, 5)
              return (
                <div>
                  <SectionHeader color="bg-zinc-400" label="Últimos 5 Resultados" />
                  {last5.length > 0
                    ? <PicksTable rows={last5} pickType="vip" onOpen={openDetail} />
                    : <div className="card p-8 text-center border-dashed"><p className="text-zinc-600 text-sm">Nenhum resultado disponível ainda.</p></div>
                  }
                </div>
              )
            })()}

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
                    {today.multiplas.map((m: any) => <MultiplaCard key={m.id} m={m} onClick={() => openDetail(m.id, 'multipla')} />)}
                  </div>
                ) : (
                  <div className="card p-8 text-center border-dashed">
                    <p className="text-zinc-500 text-sm font-semibold">Múltipla do dia ainda não gerada.</p>
                    <p className="text-zinc-600 text-xs mt-1">Publicada diariamente pela manhã.</p>
                  </div>
                )
              )}
            </div>

            {/* Últimos 5 resultados */}
            {(() => {
              const last5 = recentResults.filter(r => r.pick_type === 'multipla').slice(0, 5)
              return (
                <div>
                  <SectionHeader color="bg-zinc-400" label="Últimos 5 Resultados" />
                  {last5.length > 0
                    ? <PicksTable rows={last5} pickType="multipla" onOpen={openDetail} />
                    : <div className="card p-8 text-center border-dashed"><p className="text-zinc-600 text-sm">Nenhum resultado disponível ainda.</p></div>
                  }
                </div>
              )
            })()}

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
                  const last = alavancagem[0]
                  const bankroll = last?.bankroll_after != null
                    ? Number(last.bankroll_after)
                    : last?.bankroll_before != null
                    ? Number(last.bankroll_before)
                    : 50

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
                            { label: 'Banca Atual',  value: `R$${bankroll.toFixed(2)}`, color: bankroll > 50 ? 'text-green-400' : 'text-orange-400', sub: bankroll > 50 ? `+R$${(bankroll - 50).toFixed(2)}` : 'Início da série' },
                            { label: 'Resets (RED)', value: String(resets),             color: resets > 0 ? 'text-red-400' : 'text-zinc-500',        sub: resets === 0 ? 'Nenhum ainda' : `${resets} reinício${resets > 1 ? 's' : ''}` },
                            { label: 'Série Atual',  value: currentStreak > 0 ? `${currentStreak} green${currentStreak > 1 ? 's' : ''}` : '—', color: currentStreak >= 3 ? 'text-green-400' : currentStreak > 0 ? 'text-green-500' : 'text-zinc-500', sub: currentStreak > 0 ? 'seguidos' : 'Aguardando' },
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

                {/* Pick de hoje */}
                {todayLoading ? <Spinner /> : (
                  <div>
                    <SectionHeader color="bg-orange-400" label={`Pick do Dia · ${todayDateStr}`} />
                    {today?.alavancagem ? (
                      <AlavancagemCard pick={today.alavancagem} />
                    ) : (
                      <div className="card p-8 text-center border-dashed border-orange-500/20">
                        <p className="text-zinc-500 text-sm font-semibold">Pick de alavancagem não gerado para hoje.</p>
                        <p className="text-zinc-600 text-xs mt-1">Nenhum pick de alavancagem disponível para hoje.</p>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}

            {/* Últimos 5 resultados */}
            {(() => {
              const last5 = recentResults.filter(r => r.pick_type === 'alavancagem').slice(0, 5)
              return (
                <div>
                  <SectionHeader color="bg-zinc-400" label="Últimos 5 Resultados" />
                  {last5.length > 0
                    ? <PicksTable rows={last5} pickType="alavancagem" onOpen={openDetail} />
                    : <div className="card p-8 text-center border-dashed"><p className="text-zinc-600 text-sm">Nenhum resultado disponível ainda.</p></div>
                  }
                </div>
              )
            })()}

            <button onClick={() => navigate('/results')}
              className="w-full text-center text-xs text-orange-400 hover:text-orange-300 transition-colors py-3 border border-zinc-800 rounded-xl hover:border-zinc-700 font-semibold">
              Ver todos os resultados →
            </button>
          </div>
        )}
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
    </div>
  )
}
