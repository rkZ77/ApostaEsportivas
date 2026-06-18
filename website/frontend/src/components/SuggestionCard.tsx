import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { suggestStake } from '../utils/stakeUtils'
import ApostaModal from './ApostaModal'

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

function TeamLogo({ id, name, size = 22 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size}
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

function LeagueLogo({ id, name }: { id?: number; name?: string }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={16} height={16}
      className="w-4 h-4 object-contain shrink-0 opacity-70"
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

/** Extrai só o trecho "FATO: ..." ou as primeiras ~120 chars do reasoning */
function shortReasoning(text?: string): string {
  if (!text) return ''
  const fatoMatch = text.match(/FATO:\s*(.+?)(?=\s*ANÁLISE:|$)/i)
  if (fatoMatch) return fatoMatch[1].trim()
  return text.slice(0, 120)
}

interface BancaSummary { bankroll_current: number; unit_value: number }

export default function SuggestionCard({
  s, onClick, banca,
}: { s: Suggestion; onClick?: () => void; banca?: BancaSummary | null }) {
  const navigate = useNavigate()
  const pct = Math.round((s.confidence ?? 0) * 100)
  const [followed, setFollowed]   = useState(s.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [apiError, setApiError]   = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const stakeSuggestion = banca
    ? suggestStake(s.confidence, Number(s.odd), banca.bankroll_current, banca.unit_value)
    : null

  const handleFollow = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    setShowModal(true)
  }

  const handleConfirm = async (actualOdd: number, betHouse: string) => {
    setFollowing(true)
    setApiError(null)
    try {
      await api.post('/banca/follow', {
        pick_id: s.id,
        pick_type: s.pick_type ?? 'vip',
        stake_units: stakeSuggestion?.units ?? s.stake ?? 1,
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

  const resultStyle =
    s.result === 'GREEN' ? { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', label: 'GREEN ✓' }
    : s.result === 'RED' ? { bg: 'bg-red-500/10',   border: 'border-red-500/30',   text: 'text-red-400',   label: 'RED ✗' }
    : s.result === 'PUSH' ? { bg: 'bg-zinc-700/30', border: 'border-zinc-600',     text: 'text-zinc-300',  label: 'PUSH' }
    : s.result === 'HALF-WIN'  ? { bg: 'bg-teal-500/10',   border: 'border-teal-500/30',   text: 'text-teal-400',   label: '½ WIN' }
    : s.result === 'HALF-LOSS' ? { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', label: '½ LOSS' }
    : null

  const fato   = shortReasoning(s.reasoning)
  const isCopa = s.league_id === 1

  return (
  <>
    <div
      className={`relative overflow-hidden bg-zinc-950 border border-zinc-800 rounded-2xl cursor-pointer transition-all duration-200 group ${isCopa ? 'hover:border-yellow-500/30' : 'hover:border-green-500/30'}`}
      onClick={onClick}
    >
      {/* Accent top bar */}
      <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent to-transparent ${isCopa ? 'via-yellow-500' : 'via-green-500'}`} />

      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-zinc-800/60">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[10px] font-black uppercase tracking-widest ${isCopa ? 'text-yellow-500' : 'text-green-400'}`}>Pick VIP</span>
          <span className="badge-vip">VIP</span>
          {(s.league_id || s.league_name) && (
            <div className="flex items-center gap-1">
              <LeagueLogo id={s.league_id} name={s.league_name} />
              {s.league_name && <span className="text-[10px] text-zinc-600 truncate max-w-[90px]">{s.league_name}</span>}
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

      {/* Hero: Odd | Stake | EV */}
      <div className="flex items-stretch divide-x divide-zinc-800/60 border-b border-zinc-800/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-zinc-500 mb-0.5">Odd</div>
          <div className="text-3xl font-black text-green-400">{Number(s.odd).toFixed(2)}</div>
          <div className="text-[10px] text-zinc-600 mt-0.5">{s.bet_house}</div>
        </div>
        {stakeSuggestion && !s.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-green-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-zinc-600">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Retorno pot.</div>
              <div className="text-xl font-black text-white">
                R${(stakeSuggestion.amountR * Number(s.odd)).toFixed(0)}
              </div>
            </div>
          </>
        ) : s.profit != null ? (
          <div className="flex-1 px-5 py-3 text-center">
            <div className="text-[10px] text-zinc-500 mb-0.5">Lucro</div>
            {(() => {
              const u = stakeSuggestion?.units ?? s.stake ?? 1
              const p = Number(s.profit) * u
              return (
                <div className={`text-2xl font-black ${p >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                  {u > 1 && <span className="text-[10px] text-zinc-600 font-normal ml-1">({u}u)</span>}
                </div>
              )
            })()}
          </div>
        ) : (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Stake</div>
              <div className="text-xl font-black text-zinc-200">{s.stake ?? 1}u</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">EV</div>
              <div className={`text-xl font-black ${s.ev != null && s.ev > 0 ? 'text-green-400' : 'text-zinc-500'}`}>
                {s.ev != null ? `${Number(s.ev).toFixed(1)}%` : ''}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Times + mercado */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={s.home_team_id} name={s.home_team_name} />
          <span className="text-sm font-bold text-white truncate">{s.home_team_name}</span>
          <span className="text-zinc-600 text-xs shrink-0">vs</span>
          <span className="text-sm font-bold text-white truncate">{s.away_team_name}</span>
          <TeamLogo id={s.away_team_id} name={s.away_team_name} />
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="font-semibold text-zinc-300">{s.market}</span>
          {s.line && <><span>·</span><span>{s.line}</span></>}
        </div>
      </div>

      {/* Confiança */}
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
        {!s.result ? (
          <button
            onClick={banca ? handleFollow : () => navigate('/banca')}
            disabled={following || followed}
            className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${
              followed
                ? 'border-green-500/30 text-green-400 bg-green-500/10 cursor-default'
                : banca
                ? 'border-zinc-700 text-zinc-400 hover:border-green-500/40 hover:text-green-400 hover:bg-green-500/5'
                : 'border-yellow-500/30 text-yellow-400 hover:border-yellow-500/60 hover:bg-yellow-500/5'
            }`}
          >
            {following ? '...' : followed ? 'Apostei' : banca ? '+ Apostei' : 'Configurar banca →'}
          </button>
        ) : <span />}
        {onClick && (
          <span className="text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors ml-auto">
            Ver detalhes →
          </span>
        )}
      </div>
    </div>

    {showModal && (
      <ApostaModal
        pickOdd={Number(s.odd)}
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

