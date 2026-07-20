import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { calcVipStake, calcFreeStake, calcMultiplaStake, calcProfitUnits } from '../utils/stakeUtils'
import ApostaModal from './ApostaModal'
import { translateMarket, translateLine, translateTeamName } from '../utils/marketTranslate'
import { getResultStyle } from '../utils/resultStyle'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { TeamLogo, LeagueLogo } from './TeamLogo'
import { Share2, Check as CheckIcon, Loader2 } from 'lucide-react'

function wcPhase(dateStr?: string): string | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const phases: [string, string, string][] = [
    ['2026-06-11', '2026-07-02', 'Grupos'],
    ['2026-07-04', '2026-07-10', 'Oitavas'],
    ['2026-07-13', '2026-07-17', 'Quartas'],
    ['2026-07-19', '2026-07-22', 'Semi'],
    ['2026-07-25', '2026-07-26', 'Semifinal'],
    ['2026-07-29', '2026-08-01', 'Final'],
  ]
  for (const [start, end, label] of phases) {
    if (d >= new Date(start) && d <= new Date(end)) return label
  }
  return null
}

interface Suggestion {
  id: number
  fixture_id?: number
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
  probability?: number | null
  market_type?: string | null
  ev?: number
  match_date?: string
  reasoning?: string
  result?: string
  profit?: number
  rank_position?: number
  pick_type?: string
  is_followed?: boolean
  user_stake_units?: number | null
  user_actual_odd?: number | null
  user_bet_house?: string | null
  stake_pct?: number | null
  suggested_stake_units?: number | null
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
  const [modalOdd, setModalOdd]   = useState(Number(s.odd))
  const [apiError, setApiError]   = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()
  // Prioridade: 1) suggested_stake_units do backend (já usa banca real)
  //             2) função específica por tipo como fallback
  const stakeSuggestion = (() => {
    if (!banca) return null
    if (s.suggested_stake_units != null && s.suggested_stake_units > 0) {
      const units = s.suggested_stake_units
      return {
        units,
        amountR: units * banca.unit_value,
        kellyPct: Math.round(units * banca.unit_value / banca.bankroll_current * 1000) / 10,
      }
    }
    const prob = Number(s.probability ?? s.confidence ?? 0)
    const odd  = Number(s.odd)
    const ev   = Number(s.ev ?? 0)
    const pickType = s.pick_type ?? 'vip'
    if (pickType === 'multipla') {
      return calcMultiplaStake(prob, odd, banca.bankroll_current, banca.unit_value)
    }
    if (pickType === 'free') {
      return calcFreeStake(prob, odd, ev, banca.bankroll_current, banca.unit_value)
    }
    return calcVipStake(prob, odd, ev, banca.bankroll_current, banca.unit_value, s.stake_pct)
  })()

  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation()
    const pickTypeRoute = (s.pick_type ?? 'vip').replace('multiplas', 'multipla')
    shareStory({
      pickId: s.id,
      pickTypeRoute,
      homeTeamName: translateTeamName(s.home_team_name),
      awayTeamName: translateTeamName(s.away_team_name),
      homeTeamId: s.home_team_id,
      awayTeamId: s.away_team_id,
      leagueName: s.league_name,
      pickType: pickTypeRoute,
      market: s.market ? translateMarket(s.market) : undefined,
      line: translateLine(s.line),
      odd: Number(s.odd),
      result: s.result,
      profit: s.result ? calcProfitUnits(s.result, Number(s.odd), s.user_stake_units ?? stakeSuggestion?.units ?? 1, s.user_actual_odd) : null,
    })
  }

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    let odd = Number(s.odd)
    if (s.fixture_id && s.pick_type !== 'multipla') {
      setFollowing(true)
      try {
        const { data } = await api.get('/live/pick-odd', {
          params: { fixture_id: s.fixture_id, market_type: s.market_type ?? '', line: s.line ?? '' },
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
      await api.post('/banca/follow', {
        pick_id: s.id,
        pick_type: s.pick_type ?? 'vip',
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

  const rs = getResultStyle(s.result)
  const resultStyle = rs ? { bg: rs.bg, border: rs.border, text: rs.text, label: `${rs.label} ${rs.emoji}` } : null

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
          <span className={`text-xs font-black ${isCopa ? 'text-yellow-500' : 'text-green-400'}`}>Pick VIP</span>
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
          <div className="text-3xl font-black text-green-400">
            {s.is_followed && s.user_actual_odd != null
              ? Number(s.user_actual_odd).toFixed(2)
              : Number(s.odd).toFixed(2)}
          </div>
          {s.is_followed && s.user_actual_odd != null && Math.abs(s.user_actual_odd - Number(s.odd)) > 0.001 && (
            <div className="text-[9px] text-zinc-600 mt-0.5">pick: {Number(s.odd).toFixed(2)}</div>
          )}
          <div className="text-[10px] text-zinc-600 mt-0.5">
            {s.is_followed && s.user_bet_house ? s.user_bet_house : s.bet_house}
          </div>
        </div>
        {!s.result && s.is_followed && s.user_stake_units != null ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Apostado</div>
              <div className="text-xl font-black text-green-400">{s.user_stake_units}u</div>
              {banca && <div className="text-[11px] text-zinc-600">R${(s.user_stake_units * banca.unit_value).toFixed(0)}</div>}
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Lucro pot.</div>
              {(() => {
                const effOdd = s.user_actual_odd ?? Number(s.odd)
                const profitU = (effOdd - 1) * s.user_stake_units
                return (
                  <>
                    <div className="text-xl font-black text-white">+{profitU.toFixed(2)}u</div>
                    {banca && <div className="text-[11px] text-green-600 font-semibold">+R${(profitU * banca.unit_value).toFixed(0)}</div>}
                  </>
                )
              })()}
            </div>
          </>
        ) : stakeSuggestion && !s.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-green-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-zinc-600">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-zinc-500 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-white">+{((Number(s.odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
              <div className="text-[11px] text-green-600 font-semibold">+R${((Number(s.odd) - 1) * stakeSuggestion.amountR).toFixed(0)}</div>
            </div>
          </>
        ) : s.result ? (
          (() => {
            const u = s.user_stake_units ?? stakeSuggestion?.units ?? 1
            const p = calcProfitUnits(s.result, Number(s.odd), u, s.user_actual_odd)
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
            <div className="text-[10px] text-zinc-500 mb-0.5">EV</div>
            <div className={`text-xl font-black ${s.ev != null && s.ev > 0 ? 'text-green-400' : 'text-zinc-500'}`}>
              {s.ev != null ? `${Number(s.ev).toFixed(1)}%` : 's/d'}
            </div>
          </div>
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
          <span className="font-semibold text-zinc-300">{translateMarket(s.market)}</span>
          {s.line && <><span>·</span><span>{translateLine(s.line)}</span></>}
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
          <span className="text-[10px] text-zinc-600 font-black uppercase">Fato · </span>
          <span className="text-[11px] text-zinc-400 leading-relaxed line-clamp-3">{fato}</span>
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
        suggestedHouse={s.bet_house}
        maxUnits={s.pick_type === 'multipla' ? 3 : Math.max(10, stakeSuggestion?.units ?? 10)}
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

