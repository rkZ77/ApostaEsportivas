import { useState } from 'react'
import api from '../services/api'
import { suggestStake } from '../utils/stakeUtils'

const TEAM_LOGO   = (id?: number) => id ? `/api/proxy/team/${id}.png` : null
const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id?: number) =>
  id ? (LOCAL_LEAGUE_LOGOS[id] ?? `/api/proxy/league/${id}.png`) : null

interface Suggestion {
  id: number
  home_team_name: string
  away_team_name: string
  home_team_id?: number
  away_team_id?: number
  league_id?: number
  league_name?: string
  market: string
  line?: string
  odd: number
  bet_house: string
  confidence: number
  stake?: number
  ev?: number
  reasoning?: string
  result?: string
  profit?: number
  rank_position?: number
  pick_type?: string
  is_followed?: boolean
}

const resultMap: Record<string, { cls: string; label: string }> = {
  GREEN:       { cls: 'badge-green', label: 'GREEN' },
  RED:         { cls: 'badge-red',   label: 'RED' },
  PUSH:        { cls: 'bg-zinc-700/50 text-zinc-300 border border-zinc-600 text-xs font-bold px-2.5 py-1 rounded-lg', label: 'PUSH' },
  'HALF-WIN':  { cls: 'bg-teal-500/10 text-teal-400 border border-teal-500/30 text-xs font-bold px-2.5 py-1 rounded-lg', label: '½ WIN' },
  'HALF-LOSS': { cls: 'bg-orange-500/10 text-orange-400 border border-orange-500/30 text-xs font-bold px-2.5 py-1 rounded-lg', label: '½ LOSS' },
}

function TeamLogo({ id, name }: { id?: number; name: string }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={28} height={28}
      className="w-7 h-7 object-contain shrink-0"
      referrerPolicy="no-referrer"
      onError={e => (e.currentTarget.style.display = 'none')} loading="lazy" />
  )
}

function LeagueLogo({ id, name }: { id?: number; name?: string }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={16} height={16}
      className="w-4 h-4 object-contain shrink-0 opacity-70"
      referrerPolicy="no-referrer"
      onError={e => (e.currentTarget.style.display = 'none')} loading="lazy" />
  )
}

interface BancaSummary { bankroll_current: number; unit_value: number }

export default function SuggestionCard({ s, onClick, banca }: { s: Suggestion; onClick?: () => void; banca?: BancaSummary | null }) {
  const pct = Math.round((s.confidence ?? 0) * 100)
  const res = s.result ? resultMap[s.result] : null
  const [followed, setFollowed] = useState(s.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const stakeSuggestion = banca
    ? suggestStake(s.confidence, Number(s.odd), banca.bankroll_current, banca.unit_value)
    : null

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    setFollowing(true)
    try {
      await api.post('/banca/follow', {
        pick_id: s.id,
        pick_type: s.pick_type ?? 'vip',
        stake_units: stakeSuggestion?.units ?? s.stake ?? 1,
      })
      setFollowed(true)
    } catch {
      setFollowed(false)
    } finally {
      setFollowing(false)
    }
  }

  return (
    <div
      className="card p-5 hover:border-zinc-600 hover:bg-zinc-900/80 transition-all duration-200 group cursor-pointer"
      onClick={onClick}
    >
      {/* Times */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex-1 min-w-0">
          {(s.league_id || s.league_name) && (
            <div className="flex items-center gap-1.5 mb-1.5">
              <LeagueLogo id={s.league_id} name={s.league_name} />
              {s.league_name && <span className="text-xs text-zinc-600 truncate">{s.league_name}</span>}
            </div>
          )}
          {s.rank_position && (
            <span className="text-xs text-yellow-400 font-bold mr-2">#{s.rank_position}</span>
          )}
          <div className="flex items-center gap-2">
            <TeamLogo id={s.home_team_id} name={s.home_team_name} />
            <span className="font-bold text-white text-sm truncate">{s.home_team_name}</span>
            <span className="text-zinc-600 text-xs shrink-0">vs</span>
            <span className="font-bold text-white text-sm truncate">{s.away_team_name}</span>
            <TeamLogo id={s.away_team_id} name={s.away_team_name} />
          </div>
        </div>
        {res && <span className={`${res.cls} shrink-0 ml-2`}>{res.label}</span>}
      </div>

      {/* Detalhes da aposta */}
      <div className="grid grid-cols-5 gap-2 mb-4">
        <div className="bg-zinc-800 rounded-lg p-2 col-span-2">
          <div className="text-xs text-zinc-500 mb-0.5">Tipo</div>
          <div className="text-sm font-semibold text-white truncate">{s.market}</div>
        </div>
        <div className="bg-zinc-800 rounded-lg p-2 text-center">
          <div className="text-xs text-zinc-500 mb-0.5">Linha</div>
          <div className="text-sm font-bold text-white truncate">{s.line ?? '—'}</div>
        </div>
        <div className="bg-zinc-800 rounded-lg p-2 text-center">
          <div className="text-xs text-zinc-500 mb-0.5">Odd</div>
          <div className="text-base font-black text-green-500">{Number(s.odd).toFixed(2)}</div>
        </div>
        <div className="bg-zinc-800 rounded-lg p-2 text-center">
          <div className="text-xs text-zinc-500 mb-0.5">Stake</div>
          <div className="text-sm font-bold text-white">{stakeSuggestion?.units ?? s.stake ?? 1}u</div>
          {banca && stakeSuggestion && (
            <div className="text-[10px] text-zinc-500 mt-0.5">
              R${stakeSuggestion.amountR.toFixed(0)}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex-1">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-zinc-500">Confiança</span>
            <span className={pct >= 75 ? 'text-green-500 font-bold' : 'text-zinc-400'}>{pct}%</span>
          </div>
          <div className="bg-zinc-800 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-1.5 rounded-full transition-all ${pct >= 75 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-zinc-500'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        {s.profit != null && (
          <div className={`text-sm font-black ${s.profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
            {s.profit >= 0 ? '+' : ''}{Number(s.profit).toFixed(2)}u
          </div>
        )}
        <span className="text-xs text-zinc-500 border border-zinc-800 px-2 py-1 rounded-md">{s.bet_house}</span>
      </div>

      {s.reasoning && (
        <p className="mt-3 text-xs text-zinc-500 leading-relaxed line-clamp-2">{s.reasoning}</p>
      )}


      <div className="mt-3 flex items-center justify-between">
        {!s.result && !banca && (
          <span className="text-[11px] text-zinc-600 italic">Configure sua banca para registrar aposta</span>
        )}
        {!s.result && banca && (
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
