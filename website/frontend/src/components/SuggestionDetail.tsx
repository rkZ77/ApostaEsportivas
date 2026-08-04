import { useEffect, useState } from 'react'
import { Spinner } from './ui'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { X, TrendingUp, BarChart2, Activity, List, MessageCircle, Route, Lock } from 'lucide-react'
import { getResultStyle, PICK_TYPE_LABEL } from '../utils/resultStyle'
import api from '../services/api'
import PickSocial from './PickSocial'
import { calcVipStake, calcFreeStake, calcMultiplaStake } from '../utils/stakeUtils'
import { translateMarket, translateLine } from '../utils/marketTranslate'
import { backdropFade, drawerRight } from '../lib/motion'

interface StatBlock {
  context_type: string
  avg_goals_for: number; avg_goals_against: number; avg_total_goals: number
  avg_corners_for: number; avg_corners_against: number; avg_total_corners: number
  avg_yellow_for: number; avg_yellow_against: number
  avg_shots_on_for: number; avg_shots_on_against: number
  avg_possession_for: number; avg_passes_accuracy_for: number
  games_count: number
}
interface RecentMatch {
  match_date: string; is_home: boolean; gf: number; ga: number
  corners_f: number; corners_a: number; resultado: string
  total_goals: number; home_team_id: number; away_team_id: number
}
interface OddRow {
  market_name: string; value_name: string; odd_value: number
  bookmaker_name: string; market_type: string; side_team: string
}

const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null

const resultColor: Record<string, string> = {
  W: 'bg-green-500 text-black',
  D: 'bg-surface-3 text-ink-1',
  L: 'bg-red-500 text-ink-1',
}

function FormBadge({ r }: { r: string }) {
  return (
    <span className={`w-7 h-7 flex items-center justify-center rounded-full text-xs font-black shrink-0 ${resultColor[r] ?? 'bg-surface-3 text-ink-1'}`}>
      {r}
    </span>
  )
}

function StatBar({ label, home, away, higherIsBetter = true }: {
  label: string; home: number; away: number; higherIsBetter?: boolean
}) {
  const h = Number(home || 0)
  const a = Number(away || 0)
  const total = h + a || 1
  const homePct = Math.round((h / total) * 100)
  const homeWins = higherIsBetter ? h >= a : h <= a
  return (
    <div className="mb-3">
      <div className="flex justify-between text-xs mb-1">
        <span className={`font-bold ${homeWins ? 'text-green-400' : 'text-ink-2'}`}>{h.toFixed(2)}</span>
        <span className="text-ink-4 text-[11px]">{label}</span>
        <span className={`font-bold ${!homeWins ? 'text-blue-400' : 'text-ink-2'}`}>{a.toFixed(2)}</span>
      </div>
      <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-2">
        <div className="bg-green-500/70 transition-all duration-500" style={{ width: `${homePct}%` }} />
        <div className="bg-blue-500/70 flex-1" />
      </div>
    </div>
  )
}

export default function SuggestionDetail({ id, onClose, pickType = 'vip', banca }: {
  id: number; onClose: () => void; pickType?: string
  banca?: { bankroll_current: number; unit_value: number } | null
}) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<string>('ia')
  const [standings, setStandings] = useState<any>(null)
  const [standingsLoading, setStandingsLoading] = useState(false)
  const [caminho, setCaminho] = useState<any[]>([])
  const [caminhoLoading, setCaminhoLoading] = useState(false)
  const [locked, setLocked] = useState(false)

  useEffect(() => {
    setLoading(true); setData(null); setLocked(false); setTab('ia'); setStandings(null); setCaminho([])
    api.get(`/suggestions/${id}/detail`, { params: { pick_type: pickType } })
      .then(r => setData(r.data))
      .catch(err => { if (err?.response?.status === 403) setLocked(true) })
      .finally(() => setLoading(false))
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [id])

  useEffect(() => {
    if (tab !== 'standings' || standings || standingsLoading) return
    const fixtureId = data?.suggestion?.fixture_id
    if (!fixtureId) return
    setStandingsLoading(true)
    api.get(`/suggestions/${fixtureId}/standings`)
      .then(r => setStandings(r.data))
      .catch(() => setStandings({ groups: [] }))
      .finally(() => setStandingsLoading(false))
  }, [tab, data])

  useEffect(() => {
    if (tab !== 'caminho' || caminho.length > 0 || caminhoLoading) return
    setCaminhoLoading(true)
    api.get('/suggestions/alavancagem', { params: { limit: 50 } })
      .then(r => setCaminho(Array.isArray(r.data?.items) ? r.data.items : []))
      .catch(() => setCaminho([]))
      .finally(() => setCaminhoLoading(false))
  }, [tab])

  const isAlav = pickType === 'alavancagem'
  const hasStats = pickType === 'vip' || pickType === 'free' || isAlav
  const tabs = [
    { key: 'ia',         label: 'Pick',          Icon: TrendingUp    },
    ...(hasStats ? [
      { key: 'stats',    label: 'Médias',        Icon: BarChart2     },
      { key: 'form',     label: 'Forma',         Icon: Activity      },
      ...(isAlav
        ? [{ key: 'caminho', label: 'Caminho', Icon: Route }]
        : [{ key: 'standings', label: 'Classificação', Icon: List }]
      ),
    ] : []),
    { key: 'social',     label: 'Chat',          Icon: MessageCircle },
  ]

  const s = data?.suggestion
  const homeLogo = TEAM_LOGO(s?.home_team_id)
  const awayLogo = TEAM_LOGO(s?.away_team_id)
  const resultStyle = getResultStyle(s?.result)
  const confidence = Math.round((s?.confidence ?? 0) * 100)
  const ev = s?.ev != null ? (Number(s.ev) * 100).toFixed(1) : null

  const stakeUnits = (() => {
    if (pickType === 'alavancagem') return null
    if (!s) return 1

    // 1. Stake real apostada pelo usuário (user_followed_picks)
    if (s.user_stake_units != null && s.user_stake_units > 0) {
      return s.user_stake_units
    }

    // 2. Sugestão calculada pelo backend com banca real
    if (s.suggested_stake_units != null && s.suggested_stake_units > 0) {
      return s.suggested_stake_units
    }

    // 3. Fallback com mesmas funções dos cards (por tipo de pick)
    const isMultipla = pickType === 'multipla'
    const isFree     = pickType === 'free'
    const odd  = Number(s.total_odd ?? s.odd ?? 0)
    const prob = Number(s.probability ?? s.confidence ?? s.prob_real ?? 0)
    const ev   = Number(s.ev ?? 0)

    if (prob > 0 && odd > 1 && banca?.bankroll_current && banca.unit_value > 0) {
      if (isMultipla) {
        const sug = calcMultiplaStake(prob, odd, banca.bankroll_current, banca.unit_value)
        if (sug) return sug.units
      } else if (isFree) {
        const sug = calcFreeStake(prob, odd, ev, banca.bankroll_current, banca.unit_value)
        if (sug) return sug.units
      } else {
        const sug = calcVipStake(prob, odd, ev, banca.bankroll_current, banca.unit_value, s.stake_pct)
        if (sug) return sug.units
      }
    }

    // 4. Sem banca: escala de referência (1% banca ref. R$1000 = 1u)
    if (s.stake_pct) return Math.max(1, Math.round(s.stake_pct / 0.01))

    return 1
  })()

  return (
    <motion.div
      variants={backdropFade}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="fixed inset-0 z-[60] flex"
      onClick={onClose}
    >
      {/* overlay */}
      <div className="flex-1 bg-black/70 backdrop-blur-sm hidden sm:block" />

      {/* panel · full screen mobile, side panel desktop */}
      <motion.div
        variants={drawerRight}
        className="w-full sm:max-w-lg bg-surface-0 sm:border-l border-line flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="shrink-0 border-b border-line">
          {/* Times */}
          <div className="px-5 pt-4 pb-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-ink-3 font-semibold">
                {/* PICK_TYPE_LABEL cobre os seis pipelines. A cadeia de
                    ternarios que estava aqui terminava em 'VIP', entao um
                    pick de faltas abria rotulado como VIP. */}
                {pickType === 'free' ? 'Dica do Dia' : PICK_TYPE_LABEL[pickType] ?? 'VIP'}
              </span>
              <button
                onClick={onClose}
                className="flex items-center gap-1.5 text-xs font-bold text-ink-2 hover:text-ink-1 bg-surface-2 hover:bg-surface-3 border border-line-strong hover:border-ink-4 px-3 py-1.5 rounded-lg transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                Fechar
              </button>
            </div>

            {s ? (
              <div className="flex items-center gap-3">
                {/* Casa */}
                <div className="flex-1 flex items-center gap-2 min-w-0">
                  {homeLogo && (
                    <img src={homeLogo} alt="" width={32} height={32} className="w-8 h-8 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')} />
                  )}
                  <span className="font-black text-ink-1 text-sm leading-tight truncate">{s.home_team_name}</span>
                </div>

                {/* VS */}
                <div className="text-center shrink-0">
                  {resultStyle ? (
                    <span className={`text-xs font-black px-2 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.text} ${resultStyle.border}`}>
                      {resultStyle.label}
                    </span>
                  ) : (
                    <span className="text-ink-4 text-xs font-bold">VS</span>
                  )}
                  {s.match_datetime && (
                    <div className="text-[10px] text-ink-4 mt-1">
                      {new Date(s.match_datetime).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>

                {/* Visitante */}
                <div className="flex-1 flex items-center gap-2 justify-end min-w-0">
                  <span className="font-black text-ink-1 text-sm leading-tight truncate text-right">{s.away_team_name}</span>
                  {awayLogo && (
                    <img src={awayLogo} alt="" width={32} height={32} className="w-8 h-8 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')} />
                  )}
                </div>
              </div>
            ) : (
              <div className="h-10 flex items-center">
                <Spinner size="lg" className="mx-auto" />
              </div>
            )}
          </div>

          {/* Bet summary bar */}
          {s && pickType !== 'multipla' && pickType !== 'alavancagem' && (
            <div className="flex items-center gap-0 border-t border-line/60 text-center divide-x divide-line/60">
              <div className="flex-1 py-2.5 px-3">
                <div className="text-[10px] text-ink-3 mb-0.5">Mercado</div>
                <div className="text-xs font-bold text-ink-1 truncate">{translateMarket(s.market) ?? ''}</div>
              </div>
              {s.line && (
                <div className="flex-1 py-2.5 px-3">
                  <div className="text-[10px] text-ink-3 mb-0.5">Linha</div>
                  <div className="text-xs font-bold text-ink-1">{translateLine(s.line)}</div>
                </div>
              )}
              <div className="flex-1 py-2.5 px-3">
                <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
                <div className="font-mono text-sm font-black text-green-400">{Number(s.odd).toFixed(2)}</div>
              </div>
              <div className="flex-1 py-2.5 px-3">
                <div className="text-[10px] text-ink-3 mb-0.5">Casa</div>
                <div className="text-xs font-bold text-ink-1 truncate">{s.bet_house}</div>
              </div>
            </div>
          )}
        </div>

        <div className="flex border-b border-line shrink-0">
          {tabs.map(({ key, label, Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`tab flex-1 flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-bold uppercase ${
                tab === key ? 'tab-active' : ''
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <Spinner size="lg" />
            </div>
          ) : locked ? (
            <div className="flex flex-col items-center text-center py-10 gap-3">
              <Lock className="w-6 h-6 text-yellow-400" />
              <p className="text-ink-2 text-sm max-w-xs">
                A análise completa da IA fica disponível só para assinantes VIP.
              </p>
              <Link
                to="/planos"
                className="mt-1 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-ink-1 text-sm font-bold transition-colors"
              >
                Assinar VIP
              </Link>
            </div>
          ) : !data ? (
            <p className="text-ink-3 text-center py-10">Erro ao carregar dados.</p>
          ) : (
            <>
              {tab === 'ia' && (
                <div className="space-y-4">
                  {/* Métricas principais */}
                  <div className="font-mono grid grid-cols-3 gap-2">
                    <div className="bg-surface-1 border border-line rounded-lg p-3 text-center">
                      <div className="text-[10px] text-ink-3 uppercase mb-1">Confiança</div>
                      <div className={`text-2xl font-black ${confidence >= 75 ? 'text-green-400' : confidence >= 60 ? 'text-yellow-400' : 'text-ink-2'}`}>
                        {confidence}%
                      </div>
                    </div>
                    <div className="bg-surface-1 border border-line rounded-lg p-3 text-center">
                      {isAlav ? (
                        <>
                          <div className="text-[10px] text-ink-3 uppercase mb-1">Tipo</div>
                          <div className="text-2xl font-black text-ink-1 capitalize">{s?.tipo ?? 'N/D'}</div>
                        </>
                      ) : (
                        <>
                          <div className="text-[10px] text-ink-3 uppercase mb-1">Stake</div>
                          {stakeUnits != null
                            ? <div className="text-2xl font-black text-ink-1">{stakeUnits}u</div>
                            : <div className="text-xs text-ink-3 mt-1">s/d</div>
                          }
                        </>
                      )}
                    </div>
                    <div className="bg-surface-1 border border-line rounded-lg p-3 text-center">
                      <div className="text-[10px] text-ink-3 uppercase mb-1">EV</div>
                      <div className={`text-2xl font-black ${ev && Number(ev) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {ev ? `${Number(ev) > 0 ? '+' : ''}${ev}%` : ''}
                      </div>
                    </div>
                  </div>

                  {/* Barra de confiança */}
                  <div>
                    <div className="flex justify-between text-xs text-ink-3 mb-1.5">
                      <span>Nível de confiança</span>
                      <span className={confidence >= 75 ? 'text-green-400' : confidence >= 60 ? 'text-yellow-400' : 'text-ink-2'}>{confidence}%</span>
                    </div>
                    <div className="bg-surface-2 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all duration-700 ${confidence >= 75 ? 'bg-green-500' : confidence >= 60 ? 'bg-yellow-500' : 'bg-ink-4'}`}
                        style={{ width: `${confidence}%` }}
                      />
                    </div>
                  </div>

                  {/* Resultado se tiver */}
                  {resultStyle && s.profit != null && (
                    <div className={`rounded-lg p-4 border flex items-center justify-between ${resultStyle.bg} ${resultStyle.border}`}>
                      <div>
                        <div className="text-xs text-ink-3 mb-0.5">Resultado</div>
                        <div className={`text-xl font-black ${resultStyle.text}`}>{resultStyle.label}</div>
                      </div>
                      <div className={`text-2xl font-black ${s.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {s.profit >= 0 ? '+' : ''}{Number(s.profit).toFixed(2)}u
                      </div>
                    </div>
                  )}

                  {/* Raciocínio da IA */}
                  <div>
                    <p className="text-[10px] text-ink-3 uppercase mb-2">Análise da IA</p>
                    <div className="bg-surface-1 rounded-lg p-4 border border-line">
                      <p className="text-sm text-ink-2 leading-relaxed whitespace-pre-wrap">
                        {s.reasoning || 'Sem análise registrada.'}
                      </p>
                    </div>
                  </div>

                  {/* Múltipla / Alavancagem · legs */}
                  {(pickType === 'multipla' || pickType === 'alavancagem') && s.legs?.length > 0 && (
                    <div>
                      <p className="text-[10px] text-ink-3 uppercase mb-2">Jogos</p>
                      <div className="space-y-2">
                        {s.legs.map((g: any, i: number) => {
                          const homeTeam = g.home_team || g.home || ''
                          const awayTeam = g.away_team || g.away || ''
                          const homeLogo = g.home_team_id ? `/api/proxy/team/${g.home_team_id}.png` : null
                          const awayLogo = g.away_team_id ? `/api/proxy/team/${g.away_team_id}.png` : null
                          return (
                            <div key={i} className="bg-surface-1 border border-line rounded-lg px-4 py-3">
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5 flex-1 min-w-0 flex-wrap">
                                  {homeLogo && (
                                    <img src={homeLogo} alt="" width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                                      onError={e => (e.currentTarget.style.display = 'none')} />
                                  )}
                                  <span className="text-sm font-semibold text-ink-1 truncate">{homeTeam}</span>
                                  <span className="text-ink-4 text-xs shrink-0">vs</span>
                                  {awayLogo && (
                                    <img src={awayLogo} alt="" width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                                      onError={e => (e.currentTarget.style.display = 'none')} />
                                  )}
                                  <span className="text-sm font-semibold text-ink-1 truncate">{awayTeam}</span>
                                </div>
                                <span className="text-green-400 font-black shrink-0">{g.odd ? Number(g.odd).toFixed(2) : ''}</span>
                              </div>
                              <div className="text-xs text-ink-3 mt-0.5">{translateMarket(g.market)}{g.line ? ` · ${translateLine(g.line)}` : ''}</div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                </div>
              )}

              {tab === 'stats' && (
                <div className="space-y-6">
                  {(['HOME', 'AWAY'] as const).map(ctx => {
                    const hStats: StatBlock = data.home_stats?.[ctx]
                    const aStats: StatBlock = data.away_stats?.[ctx === 'HOME' ? 'AWAY' : 'HOME'] ?? data.away_stats?.[ctx]
                    return (
                      <div key={ctx}>
                        <div className="flex items-center justify-between mb-3">
                          <p className="text-[10px] text-ink-3 uppercase font-semibold">
                            {ctx === 'HOME' ? 'Contexto Casa' : 'Contexto Fora'}
                          </p>
                          <span className="text-[10px] text-ink-4">{hStats?.games_count ?? 0}j / {aStats?.games_count ?? 0}j</span>
                        </div>

                        {/* Legenda */}
                        <div className="flex justify-between text-[10px] mb-2">
                          <span className="text-green-400 font-bold truncate max-w-[120px]">{s.home_team_name}</span>
                          <span className="text-blue-400 font-bold truncate max-w-[120px] text-right">{s.away_team_name}</span>
                        </div>

                        <div className="bg-surface-1 rounded-lg border border-line p-4">
                          {hStats || aStats ? (
                            <>
                              <StatBar label="Gols feitos"      home={hStats?.avg_goals_for ?? 0}       away={aStats?.avg_goals_for ?? 0} />
                              <StatBar label="Gols cedidos"     home={hStats?.avg_goals_against ?? 0}   away={aStats?.avg_goals_against ?? 0} higherIsBetter={false} />
                              <StatBar label="Total de gols"    home={hStats?.avg_total_goals ?? 0}     away={aStats?.avg_total_goals ?? 0} />
                              <StatBar label="Escanteios feitos"  home={hStats?.avg_corners_for ?? 0}   away={aStats?.avg_corners_for ?? 0} />
                              <StatBar label="Escanteios cedidos" home={hStats?.avg_corners_against ?? 0} away={aStats?.avg_corners_against ?? 0} higherIsBetter={false} />
                              <StatBar label="Escanteios tot"   home={hStats?.avg_total_corners ?? 0}   away={aStats?.avg_total_corners ?? 0} />
                              <StatBar label="Amarelos feitos"  home={hStats?.avg_yellow_for ?? 0}      away={aStats?.avg_yellow_for ?? 0} higherIsBetter={false} />
                              <StatBar label="Amarelos cedidos" home={hStats?.avg_yellow_against ?? 0}  away={aStats?.avg_yellow_against ?? 0} higherIsBetter={false} />
                              <StatBar label="Chutes a gol"     home={hStats?.avg_shots_on_for ?? 0}    away={aStats?.avg_shots_on_for ?? 0} />
                              <StatBar label="Posse de bola"    home={hStats?.avg_possession_for ?? 0}  away={aStats?.avg_possession_for ?? 0} />
                            </>
                          ) : (
                            <p className="text-xs text-ink-4 text-center py-4">Sem médias para este contexto</p>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {tab === 'form' && (
                <div className="space-y-5">
                  {[
                    { name: s.home_team_name, teamId: s.home_team_id, recent: data.home_recent },
                    { name: s.away_team_name, teamId: s.away_team_id, recent: data.away_recent },
                  ].map(({ name, teamId, recent }) => {
                    const logo = TEAM_LOGO(teamId)
                    return (
                      <div key={name}>
                        {/* Time + forma */}
                        <div className="flex items-center gap-2 mb-2">
                          {logo && (
                            <img src={logo} alt="" width={20} height={20} className="w-5 h-5 object-contain"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                          <span className="text-xs font-bold text-ink-1 truncate">{name}</span>
                          <div className="flex gap-1 ml-auto">
                            {recent.length > 0
                              ? recent.map((m: RecentMatch, i: number) => <FormBadge key={i} r={m.resultado} />)
                              : <span className="text-xs text-ink-4">Sem dados</span>
                            }
                          </div>
                        </div>

                        {/* Jogos recentes */}
                        <div className="space-y-1.5">
                          {recent.length === 0 ? (
                            <p className="text-xs text-ink-4 py-2">Sem jogos recentes</p>
                          ) : recent.map((m: RecentMatch, i: number) => {
                            const date = new Date(m.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                            const isHome = m.is_home
                            return (
                              <div key={i} className="flex items-center gap-2 bg-surface-1 rounded-lg px-3 py-2 border border-line/50">
                                <FormBadge r={m.resultado} />
                                <span className="text-[10px] text-ink-3 w-9 shrink-0">{date}</span>
                                <span className="text-[10px] text-ink-4 shrink-0">{isHome ? 'C' : 'F'}</span>
                                <span className="flex-1 text-xs text-ink-1 font-bold">{m.gf} – {m.ga}</span>
                                <span className="text-[10px] text-ink-4">{m.corners_f}c</span>
                                <span className="text-[10px] text-ink-4">{Number(m.total_goals).toFixed(0)}g</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {tab === 'standings' && (
                <div>
                  {standingsLoading ? (
                    <div className="flex items-center justify-center h-40">
                      <Spinner size="lg" />
                    </div>
                  ) : !standings || standings.groups.length === 0 ? (
                    <p className="text-ink-3 text-center py-10 text-sm">Classificação não disponível.</p>
                  ) : standings.groups.map((g: any, gi: number) => (
                    <div key={gi} className={gi > 0 ? 'mt-6' : ''}>
                      {standings.groups.length > 1 && (
                        <p className="text-[10px] text-ink-3 uppercase mb-2 font-semibold">{g.group}</p>
                      )}
                      <div className="bg-surface-1 rounded-lg border border-line overflow-hidden">
                        {/* Header */}
                        <div className="grid grid-cols-[28px_1fr_32px_28px_28px_28px_28px] gap-1 px-3 py-2 border-b border-line text-[10px] text-ink-4 font-semibold uppercase">
                          <span>#</span>
                          <span>Time</span>
                          <span className="text-center">Pts</span>
                          <span className="text-center">J</span>
                          <span className="text-center">V</span>
                          <span className="text-center">E</span>
                          <span className="text-center">SG</span>
                        </div>
                        {g.teams.map((t: any, i: number) => {
                          const isHome = t.team_id === standings.home_team_id
                          const isAway = t.team_id === standings.away_team_id
                          const logo = t.team_id ? `/api/proxy/team/${t.team_id}.png` : null
                          return (
                            <div
                              key={i}
                              className={`grid grid-cols-[28px_1fr_32px_28px_28px_28px_28px] gap-1 px-3 py-2 border-b border-line/40 last:border-0 items-center ${
                                isHome ? 'bg-green-500/8 border-l-2 border-l-green-500' :
                                isAway ? 'bg-blue-500/8 border-l-2 border-l-blue-500' : ''
                              }`}
                            >
                              <span className={`text-xs font-black ${isHome || isAway ? 'text-ink-1' : 'text-ink-3'}`}>{t.pos}</span>
                              <div className="flex items-center gap-1.5 min-w-0">
                                {logo && (
                                  <img src={logo} alt="" width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                                    onError={e => (e.currentTarget.style.display = 'none')} />
                                )}
                                <span className={`text-xs truncate ${isHome ? 'text-green-400 font-bold' : isAway ? 'text-blue-400 font-bold' : 'text-ink-2'}`}>
                                  {t.team}
                                </span>
                              </div>
                              <span className={`text-xs font-black text-center ${isHome || isAway ? 'text-ink-1' : 'text-ink-2'}`}>{t.pts}</span>
                              <span className="text-[11px] text-ink-3 text-center">{t.played}</span>
                              <span className="text-[11px] text-green-500 text-center">{t.won}</span>
                              <span className="text-[11px] text-ink-3 text-center">{t.draw}</span>
                              <span className={`text-[11px] text-center font-semibold ${(t.gd ?? 0) > 0 ? 'text-green-400' : (t.gd ?? 0) < 0 ? 'text-red-400' : 'text-ink-3'}`}>
                                {(t.gd ?? 0) > 0 ? '+' : ''}{t.gd}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                      <div className="flex gap-3 mt-2 px-1">
                        <span className="flex items-center gap-1 text-[10px] text-green-400"><span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />{s?.home_team_name}</span>
                        <span className="flex items-center gap-1 text-[10px] text-blue-400"><span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />{s?.away_team_name}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {tab === 'caminho' && (
                <div>
                  {caminhoLoading ? (
                    <div className="flex items-center justify-center h-40">
                      <Spinner size="lg" tone="orange" />
                    </div>
                  ) : caminho.length === 0 ? (
                    <p className="text-ink-3 text-center py-10 text-sm">Nenhum histórico disponível.</p>
                  ) : (
                    <div className="space-y-0">
                      {/* Banca inicial */}
                      {(() => {
                        const first = caminho[caminho.length - 1]
                        const startBankroll = first?.bankroll_before
                        const lastDone = [...caminho].reverse().find(p => p.result)
                        const currentBankroll = lastDone?.bankroll_after ?? startBankroll
                        return (
                          <div className="flex items-center gap-3 bg-orange-500/10 border border-orange-500/20 rounded-lg px-4 py-3 mb-4">
                            <div className="w-8 h-8 rounded-full bg-orange-500/20 flex items-center justify-center shrink-0">
                              <span className="text-orange-400 text-xs font-black">R$</span>
                            </div>
                            <div className="flex-1">
                              <div className="text-[10px] text-ink-3 uppercase">Banca atual da série</div>
                              <div className="text-lg font-black text-orange-400">
                                R${Number(currentBankroll ?? 0).toFixed(0)}
                              </div>
                            </div>
                            {startBankroll && currentBankroll && (
                              <div className={`text-sm font-black ${currentBankroll >= startBankroll ? 'text-green-400' : 'text-red-400'}`}>
                                {currentBankroll >= startBankroll ? '+' : ''}
                                {((currentBankroll / startBankroll - 1) * 100).toFixed(1)}%
                              </div>
                            )}
                          </div>
                        )
                      })()}

                      {/* Timeline de picks */}
                      {[...caminho].reverse().map((pick: any, idx: number) => {
                        const isThisPick = pick.id === id
                        const res = pick.result
                        const resColor = res === 'GREEN' ? 'text-green-400 bg-green-500/10 border-green-500/30'
                          : res === 'RED' ? 'text-red-400 bg-red-500/10 border-red-500/30'
                          : 'text-ink-2 bg-surface-2 border-line-strong'
                        const resLabel = res === 'GREEN' ? '✓' : res === 'RED' ? '✗' : '·'
                        const date = pick.match_date
                          ? new Date(pick.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                          : ''
                        const bankBefore = pick.bankroll_before
                        const bankAfter = pick.bankroll_after
                        return (
                          <div key={pick.id} className="flex gap-3">
                            {/* Linha vertical + círculo */}
                            <div className="flex flex-col items-center w-8 shrink-0">
                              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-black border ${
                                isThisPick
                                  ? 'bg-orange-500 border-orange-400 text-black'
                                  : res
                                    ? (res === 'GREEN' ? 'bg-green-500/20 border-green-500/40 text-green-400' : 'bg-red-500/20 border-red-500/40 text-red-400')
                                    : 'bg-surface-2 border-line-strong text-ink-2'
                              }`}>
                                {resLabel}
                              </div>
                              {idx < caminho.length - 1 && (
                                <div className={`w-0.5 flex-1 my-1 ${res === 'GREEN' ? 'bg-green-500/30' : res === 'RED' ? 'bg-red-500/30' : 'bg-surface-2'}`} />
                              )}
                            </div>

                            {/* Card do pick */}
                            <div className={`flex-1 mb-2 rounded-lg border px-3 py-2.5 ${
                              isThisPick ? 'border-orange-500/40 bg-orange-500/5' : 'border-line bg-surface-1'
                            }`}>
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1 flex-wrap mb-0.5">
                                    {pick.home_team_id_1 && (
                                      <img src={`/api/proxy/team/${pick.home_team_id_1}.png`}
                                        alt="" width={14} height={14} className="w-3.5 h-3.5 object-contain shrink-0"
                                        onError={e => (e.currentTarget.style.display = 'none')} />
                                    )}
                                    <span className="text-xs font-bold text-ink-1 truncate">{pick.home_team_1}</span>
                                    <span className="text-ink-4 text-[10px]">vs</span>
                                    {pick.away_team_id_1 && (
                                      <img src={`/api/proxy/team/${pick.away_team_id_1}.png`}
                                        alt="" width={14} height={14} className="w-3.5 h-3.5 object-contain shrink-0"
                                        onError={e => (e.currentTarget.style.display = 'none')} />
                                    )}
                                    <span className="text-xs font-bold text-ink-1 truncate">{pick.away_team_1}</span>
                                  </div>
                                  <div className="text-[10px] text-ink-3 mt-0.5">
                                    {date} · {pick.market_1}{pick.odd_combined ? ` @ ${Number(pick.odd_combined).toFixed(2)}` : ''}
                                  </div>
                                </div>
                                {res && (
                                  <span className={`text-[10px] font-black px-2 py-0.5 rounded border shrink-0 ${resColor}`}>
                                    {res === 'GREEN' ? 'GREEN' : res === 'RED' ? 'RED' : res}
                                  </span>
                                )}
                              </div>
                              {/* Progressão de banca */}
                              {(bankBefore || bankAfter) && (
                                <div className="flex items-center gap-1.5 mt-1.5">
                                  {bankBefore && <span className="text-[10px] text-ink-3">R${Number(bankBefore).toFixed(0)}</span>}
                                  {bankBefore && bankAfter && <span className="text-[10px] text-ink-4">·</span>}
                                  {bankAfter && (
                                    <span className={`text-[10px] font-bold ${bankAfter > bankBefore ? 'text-green-400' : bankAfter < bankBefore ? 'text-red-400' : 'text-ink-2'}`}>
                                      R${Number(bankAfter).toFixed(0)}
                                    </span>
                                  )}
                                  {bankBefore && bankAfter && (
                                    <span className={`text-[10px] ml-auto ${bankAfter >= bankBefore ? 'text-green-400' : 'text-red-400'}`}>
                                      {bankAfter >= bankBefore ? '+' : ''}{Number(pick.profit ?? 0).toFixed(2)}u
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {tab === 'social' && (
                <PickSocial pickId={id} pickType={pickType} />
              )}
            </>
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
