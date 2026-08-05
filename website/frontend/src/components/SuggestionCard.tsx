import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { toastUp, fadeInUp } from '../lib/motion'
import api from '../services/api'
import { calcVipStake, calcFreeStake, calcMultiplaStake, calcProfitUnits } from '../utils/stakeUtils'
import ApostaModal from './ApostaModal'
import { translateMarket, translateLine, translateTeamName, explainMarket } from '../utils/marketTranslate'
import { PICK_TYPE_BORDER } from '../utils/resultStyle'
import InfoTip from './InfoTip'
import AnalysisModal from './AnalysisModal'
import { Badge, PickTypeBadge, ResultBadge } from './ui'
import FavoriteButton from './FavoriteButton'
import { PickCardFooter, PickExplainButton, PickProbability } from './PickCardParts'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { TeamLogo, LeagueLogo } from './TeamLogo'
import { Clock } from 'lucide-react'

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

/*
 * Teto de unidades por tipo, espelhando STAKE_LIMITS em
 * backend/routers/banca.py. Sem isto o modal deixava escolher mais unidades
 * do que o backend aceita e a aposta so' falhava no POST /banca/follow, com
 * erro genérico depois de o usuário ter confirmado -- faltas e goleiros
 * param em 6 lá, não em 10.
 *
 * VIP fica de fora de propósito: mantém o teto dinâmico que já tinha.
 */
const MAX_UNITS_POR_TIPO: Record<string, number> = {
  free: 6, multipla: 3, faltas: 6, goleiros: 6,
}

export default function SuggestionCard({
  s, onClick, banca, isLive = false,
}: { s: Suggestion; onClick?: () => void; banca?: BancaSummary | null; isLive?: boolean }) {
  const navigate = useNavigate()
  const pct = Math.round((s.confidence ?? 0) * 100)
  const [followed, setFollowed]   = useState(s.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [showAnalysis, setShowAnalysis] = useState(false)
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

  const fato   = shortReasoning(s.reasoning)
  const isCopa = s.league_id === 1
  const pickType = s.pick_type ?? 'vip'

  // Horário do jogo. O card mostrava só a data em outro lugar, e "hoje 16:00"
  // é justamente o que decide se ainda dá tempo de entrar na aposta.
  const kickoff = s.match_date
    ? new Date(s.match_date).toLocaleTimeString('pt-BR', {
        hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo',
      })
    : null

  const probPct = s.probability != null ? Number(s.probability) * 100 : null

  // Sugestão nunca pode nascer acima do teto: em mercado com teto baixo
  // (faltas/goleiros) o Kelly do calcVipStake chegava a pedir mais unidades
  // do que o backend aceita.
  const maxUnits = MAX_UNITS_POR_TIPO[pickType] ?? Math.max(10, stakeSuggestion?.units ?? 10)

  return (
  <>
    <motion.div
      variants={fadeInUp}
      whileHover={{ y: -3, boxShadow: '0 12px 24px -8px rgba(0,0,0,0.5)' }}
      whileTap={{ scale: 0.985 }}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      /* Casca comum dos 6 tipos de card (ver .pick-card em index.css). A cor da
         borda vem de PICK_TYPE_BORDER, que é a mesma convenção do badge. */
      className={`pick-card group cursor-pointer ${isCopa ? 'border-yellow-500/20 hover:border-yellow-500/40' : PICK_TYPE_BORDER[pickType] ?? PICK_TYPE_BORDER.vip}`}
      onClick={onClick}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <PickTypeBadge type={pickType} />
          {(s.league_id || s.league_name) && (
            <div className="flex items-center gap-1 min-w-0">
              <LeagueLogo id={s.league_id} name={s.league_name} />
              {s.league_name && <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{s.league_name}</span>}
            </div>
          )}
          {kickoff && (
            <span className="flex items-center gap-1 text-[10px] text-ink-4 shrink-0">
              <Clock className="w-3 h-3" />
              {kickoff}
            </span>
          )}
        </div>
        {s.home_team_id != null && (
          <FavoriteButton kind="team" refId={s.home_team_id} label={s.home_team_name} size="sm" />
        )}
        {s.result ? (
          <ResultBadge result={s.result} />
        ) : isLive ? (
          <Badge tone="red" className="animate-pulse">Ao vivo</Badge>
        ) : (
          <Badge tone="neutral">Pendente</Badge>
        )}
      </div>

      {/* Hero: Odd | Stake | EV */}
      <div className="font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
          <div className="text-3xl font-black text-green-400">
            {s.is_followed && s.user_actual_odd != null
              ? Number(s.user_actual_odd).toFixed(2)
              : Number(s.odd).toFixed(2)}
          </div>
          {s.is_followed && s.user_actual_odd != null && Math.abs(s.user_actual_odd - Number(s.odd)) > 0.001 && (
            <div className="text-[9px] text-ink-4 mt-0.5">pick: {Number(s.odd).toFixed(2)}</div>
          )}
          <div className="text-[10px] text-ink-4 mt-0.5">
            {s.is_followed && s.user_bet_house ? s.user_bet_house : s.bet_house}
          </div>
        </div>
        {!s.result && s.is_followed && s.user_stake_units != null ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostado</div>
              <div className="text-xl font-black text-green-400">{s.user_stake_units}u</div>
              {banca && <div className="text-[11px] text-ink-4">R${(s.user_stake_units * banca.unit_value).toFixed(0)}</div>}
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              {(() => {
                const effOdd = s.user_actual_odd ?? Number(s.odd)
                const profitU = (effOdd - 1) * s.user_stake_units
                return (
                  <>
                    <div className="text-xl font-black text-ink-1">+{profitU.toFixed(2)}u</div>
                    {banca && <div className="text-[11px] text-green-600 font-semibold">+R${(profitU * banca.unit_value).toFixed(0)}</div>}
                  </>
                )
              })()}
            </div>
          </>
        ) : stakeSuggestion && !s.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-green-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-ink-4">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-ink-1">+{((Number(s.odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
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
            <div className="text-[10px] text-ink-3 mb-0.5">EV</div>
            <div className={`text-xl font-black ${s.ev != null && s.ev > 0 ? 'text-green-400' : 'text-ink-3'}`}>
              {/* ev vem como fração do endpoint de lista · ver AnalysisModal */}
              {s.ev != null ? `${(Number(s.ev) * 100).toFixed(1)}%` : 's/d'}
            </div>
          </div>
        )}
      </div>

      {/* Times + mercado */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={s.home_team_id} name={s.home_team_name} />
          <span className="text-sm font-bold text-ink-1 truncate">{s.home_team_name}</span>
          <span className="text-ink-4 text-xs shrink-0">vs</span>
          <span className="text-sm font-bold text-ink-1 truncate">{s.away_team_name}</span>
          <TeamLogo id={s.away_team_id} name={s.away_team_name} />
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3">
          <span className="font-semibold text-ink-2">{translateMarket(s.market)}</span>
          {s.line && <><span>·</span><span>{translateLine(s.line)}</span></>}
          <InfoTip text={explainMarket(s.market, s.line)} />
        </div>
      </div>

      <PickProbability confidence={s.confidence} probability={s.probability} />

      {/* Reasoning snippet */}
      {fato && (
        <div className="mx-5 mb-3 px-3 py-2 bg-surface-1 border border-line rounded-md">
          <span className="label-micro">Fato · </span>
          <span className="text-[11px] text-ink-2 leading-relaxed line-clamp-3">{fato}</span>
        </div>
      )}


      {/* Footer */}
      {(s.reasoning || s.ev != null || probPct != null) && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!s.result ? (banca ? handleFollow : () => navigate('/banca')) : undefined}
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
          market: translateMarket(s.market),
          line: translateLine(s.line),
          odd: Number(s.odd),
          confidence: s.confidence,
          probability: s.probability,
          ev: s.ev,
          reasoning: s.reasoning,
        }}
      />
    )}
    </AnimatePresence>

    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={modalOdd}
        suggestedUnits={Math.min(stakeSuggestion?.units ?? 1, maxUnits)}
        suggestedHouse={s.bet_house}
        maxUnits={maxUnits}
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
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-ink-1 text-sm font-semibold px-5 py-3 rounded-lg shadow-lg whitespace-nowrap"
      >
        Pick registrado com sucesso!
      </motion.div>
    )}
    </AnimatePresence>
  </>
  )
}

