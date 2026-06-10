import { useEffect, useState } from 'react'
import api from '../services/api'
import PickSocial from './PickSocial'

// ─── tipos ──────────────────────────────────────────────────────────────────
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
  home_goals: number; away_goals: number; total_goals: number
  home_team_id: number; away_team_id: number
}
interface OddRow {
  market_name: string; value_name: string; odd_value: number
  bookmaker_name: string; market_type: string; side_team: string
}

const resultColor: Record<string, string> = {
  W: 'bg-green-500 text-black', D: 'bg-zinc-600 text-white', L: 'bg-red-500 text-white',
}

// ─── mini componentes ────────────────────────────────────────────────────────
function StatRow({ label, home, away, higherIsBetter = true }: {
  label: string; home: number; away: number; higherIsBetter?: boolean
}) {
  const h = Number(home || 0).toFixed(2)
  const a = Number(away || 0).toFixed(2)
  const homeWins = higherIsBetter ? home >= away : home <= away
  return (
    <div className="flex items-center gap-3 py-2 border-b border-zinc-800/60 last:border-0">
      <span className={`text-sm font-bold w-14 text-right ${homeWins ? 'text-green-400' : 'text-zinc-300'}`}>{h}</span>
      <span className="flex-1 text-xs text-zinc-500 text-center">{label}</span>
      <span className={`text-sm font-bold w-14 ${!homeWins ? 'text-green-400' : 'text-zinc-300'}`}>{a}</span>
    </div>
  )
}

function FormBadge({ r }: { r: string }) {
  return (
    <span className={`w-7 h-7 flex items-center justify-center rounded-full text-xs font-black ${resultColor[r] ?? 'bg-zinc-700 text-white'}`}>
      {r}
    </span>
  )
}

function RecentList({ matches, label }: { matches: RecentMatch[]; label: string }) {
  return (
    <div>
      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">{label}</p>
      {matches.length === 0 ? (
        <p className="text-xs text-zinc-600">Sem dados recentes</p>
      ) : (
        <div className="space-y-1.5">
          {matches.map((m, i) => {
            const date = new Date(m.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
            return (
              <div key={i} className="flex items-center gap-2 bg-zinc-800/40 rounded-lg px-3 py-2">
                <FormBadge r={m.resultado} />
                <span className="text-xs text-zinc-400 w-10 shrink-0">{date}</span>
                <span className="flex-1 text-xs text-white font-medium">{m.gf} – {m.ga}</span>
                <span className="text-xs text-zinc-600">{m.corners_f}c/{m.corners_a}</span>
                <span className="text-xs text-zinc-600">{Number(m.total_goals).toFixed(0)}g</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── modal principal ─────────────────────────────────────────────────────────
export default function SuggestionDetail({ id, onClose, pickType = 'vip' }: { id: number; onClose: () => void; pickType?: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<string>('ia')

  useEffect(() => {
    setLoading(true)
    setData(null)
    setTab('ia')
    api.get(`/suggestions/${id}/detail`, { params: { pick_type: pickType } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))

    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [id])

  const hasFullDetail = pickType === 'vip' || pickType === 'free'
  const tabs = [
    { key: 'ia',     label: 'IA'     },
    ...(hasFullDetail ? [
      { key: 'stats', label: 'Médias' },
      { key: 'form',  label: 'Forma'  },
      { key: 'odds',  label: 'Odds'   },
    ] : []),
    { key: 'social', label: 'Chat'   },
  ]

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="flex-1 bg-black/70 backdrop-blur-sm" />

      <div
        className="w-full max-w-xl bg-zinc-950 border-l border-zinc-800 flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800 shrink-0">
          {data?.suggestion ? (
            <div className="min-w-0 flex-1">
              <p className="text-white font-black text-base leading-tight truncate">
                {data.suggestion.home_team_name}
                {data.suggestion.away_team_name && (
                  <>
                    <span className="text-zinc-500 font-normal mx-2 text-sm">vs</span>
                    {data.suggestion.away_team_name}
                  </>
                )}
              </p>
              <p className="text-xs text-zinc-500 mt-0.5">
                {pickType === 'multipla' || pickType === 'alavancagem'
                  ? `Odd ${Number(data.suggestion.odd ?? 0).toFixed(2)} · Confiança ${Math.round((data.suggestion.confidence ?? 0) * 100)}%`
                  : <>{data.suggestion.market}{data.suggestion.line ? <> · <span className="text-zinc-400">{data.suggestion.line}</span></> : ''} · Odd {Number(data.suggestion.odd).toFixed(2)} · {data.suggestion.bet_house}</>
                }
              </p>
            </div>
          ) : (
            <span className="text-zinc-400 text-sm">Carregando...</span>
          )}
          <button onClick={onClose}
            className="text-zinc-500 hover:text-white text-2xl leading-none ml-4 shrink-0 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-zinc-800 transition-colors">
            ×
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-zinc-800 shrink-0">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 py-2.5 text-xs font-bold uppercase tracking-wider transition-colors ${
                tab === t.key
                  ? 'text-green-500 border-b-2 border-green-500'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
            </div>
          ) : !data ? (
            <p className="text-zinc-500 text-center py-10">Erro ao carregar dados.</p>
          ) : (
            <>
              {/* ── ABA IA ─────────────────────────────────────────────── */}
              {tab === 'ia' && (
                <div className="space-y-5">
                  {data.suggestion.result && (
                    <div className={`rounded-xl p-4 border ${
                      data.suggestion.result === 'GREEN' ? 'bg-green-500/10 border-green-500/30'
                      : data.suggestion.result === 'RED'  ? 'bg-red-500/10 border-red-500/30'
                      : 'bg-zinc-800 border-zinc-700'
                    }`}>
                      <p className="text-xs text-zinc-400 mb-1">Resultado</p>
                      <p className={`text-2xl font-black ${
                        data.suggestion.result === 'GREEN' ? 'text-green-400'
                        : data.suggestion.result === 'RED' ? 'text-red-400' : 'text-zinc-300'
                      }`}>
                        {data.suggestion.result}
                        {data.suggestion.profit != null && (
                          <span className="text-base ml-3 font-bold">
                            {data.suggestion.profit >= 0 ? '+' : ''}{Number(data.suggestion.profit).toFixed(2)}u
                          </span>
                        )}
                      </p>
                    </div>
                  )}

                  {(data.suggestion.market || data.suggestion.line) && pickType !== 'multipla' && pickType !== 'alavancagem' && (
                    <div className="grid grid-cols-5 gap-2">
                      <div className="bg-zinc-800 rounded-xl p-3 col-span-3">
                        <div className="text-xs text-zinc-500 mb-1">Tipo</div>
                        <div className="text-sm font-bold text-white truncate">{data.suggestion.market ?? '—'}</div>
                      </div>
                      <div className="bg-zinc-800 rounded-xl p-3 col-span-2 text-center">
                        <div className="text-xs text-zinc-500 mb-1">Linha</div>
                        <div className="text-sm font-bold text-white truncate">{data.suggestion.line ?? '—'}</div>
                      </div>
                    </div>
                  )}

                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'Confiança', value: `${Math.round((data.suggestion.confidence ?? 0) * 100)}%` },
                      { label: 'Stake',     value: `${data.suggestion.stake ?? 1}u` },
                      { label: 'EV',        value: data.suggestion.ev != null ? Number(data.suggestion.ev).toFixed(3) : '—' },
                    ].map(({ label, value }) => (
                      <div key={label} className="bg-zinc-800 rounded-xl p-3 text-center">
                        <div className="text-xs text-zinc-500 mb-1">{label}</div>
                        <div className="text-lg font-black text-white">{value}</div>
                      </div>
                    ))}
                  </div>

                  <div>
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3">Raciocínio da IA</p>
                    <div className="bg-zinc-900 rounded-xl p-4 border border-zinc-800">
                      <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap">
                        {data.suggestion.reasoning || 'Sem raciocínio registrado.'}
                      </p>
                    </div>
                  </div>

                  {data.suggestion.match_datetime && (
                    <div className="text-xs text-zinc-600 text-center">
                      Jogo: {new Date(data.suggestion.match_datetime).toLocaleString('pt-BR')}
                    </div>
                  )}
                </div>
              )}

              {/* ── ABA STATS ──────────────────────────────────────────── */}
              {tab === 'stats' && (
                <div className="space-y-6">
                  {(['HOME', 'AWAY'] as const).map(ctx => {
                    const hStats: StatBlock = data.home_stats?.[ctx]
                    const aStats: StatBlock = data.away_stats?.[ctx === 'HOME' ? 'AWAY' : 'HOME']
                      ?? data.away_stats?.[ctx]

                    return (
                      <div key={ctx}>
                        <div className="flex items-center justify-between mb-3">
                          <p className="text-xs text-zinc-500 uppercase tracking-wider">
                            {ctx === 'HOME' ? 'Casa' : 'Visitante'} — contexto {ctx}
                          </p>
                          <span className="text-xs text-zinc-600">
                            {hStats?.games_count ?? 0}j / {aStats?.games_count ?? 0}j
                          </span>
                        </div>

                        <div className="bg-zinc-900 rounded-xl border border-zinc-800 overflow-hidden">
                          <div className="flex items-center gap-3 px-4 py-2 bg-zinc-800/60 text-xs font-bold">
                            <span className="w-14 text-right text-green-400 truncate">{data.suggestion.home_team_name}</span>
                            <span className="flex-1 text-center text-zinc-500">Estatística</span>
                            <span className="w-14 text-blue-400 truncate">{data.suggestion.away_team_name}</span>
                          </div>

                          {hStats || aStats ? (
                            <div className="px-4">
                              <StatRow label="Gols pró"       home={hStats?.avg_goals_for ?? 0}     away={aStats?.avg_goals_for ?? 0} />
                              <StatRow label="Gols sofridos"  home={hStats?.avg_goals_against ?? 0} away={aStats?.avg_goals_against ?? 0} higherIsBetter={false} />
                              <StatRow label="Total gols"     home={hStats?.avg_total_goals ?? 0}   away={aStats?.avg_total_goals ?? 0} />
                              <StatRow label="Escanteios pró" home={hStats?.avg_corners_for ?? 0}   away={aStats?.avg_corners_for ?? 0} />
                              <StatRow label="Escanteios tot" home={hStats?.avg_total_corners ?? 0} away={aStats?.avg_total_corners ?? 0} />
                              <StatRow label="Cartões pró"    home={hStats?.avg_yellow_for ?? 0}    away={aStats?.avg_yellow_for ?? 0} higherIsBetter={false} />
                              <StatRow label="Chutes a gol"   home={hStats?.avg_shots_on_for ?? 0}  away={aStats?.avg_shots_on_for ?? 0} />
                              <StatRow label="Posse de bola"  home={hStats?.avg_possession_for ?? 0} away={aStats?.avg_possession_for ?? 0} />
                            </div>
                          ) : (
                            <p className="text-xs text-zinc-600 text-center py-6">Sem médias para este contexto</p>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* ── ABA FORMA ──────────────────────────────────────────── */}
              {tab === 'form' && (
                <div className="space-y-6">
                  <div className="grid grid-cols-2 gap-4">
                    {[
                      { name: data.suggestion.home_team_name, recent: data.home_recent },
                      { name: data.suggestion.away_team_name, recent: data.away_recent },
                    ].map(({ name, recent }) => (
                      <div key={name}>
                        <p className="text-xs text-zinc-500 mb-2 truncate">{name}</p>
                        <div className="flex gap-1 flex-wrap">
                          {recent.length > 0
                            ? recent.map((m: RecentMatch, i: number) => <FormBadge key={i} r={m.resultado} />)
                            : <span className="text-xs text-zinc-600">Sem dados</span>
                          }
                        </div>
                      </div>
                    ))}
                  </div>

                  <RecentList matches={data.home_recent} label={`Últimos jogos — ${data.suggestion.home_team_name}`} />
                  <RecentList matches={data.away_recent} label={`Últimos jogos — ${data.suggestion.away_team_name}`} />
                </div>
              )}

              {/* ── ABA SOCIAL ─────────────────────────────────────────── */}
              {tab === 'social' && (
                <PickSocial pickId={id} pickType={pickType} />
              )}

              {/* ── ABA ODDS ───────────────────────────────────────────── */}
              {tab === 'odds' && (
                <div className="space-y-4">
                  {data.odds.length === 0 ? (
                    <p className="text-zinc-500 text-center py-10 text-sm">Sem odds disponíveis para este jogo.</p>
                  ) : (
                    (() => {
                      const groups: Record<string, OddRow[]> = {}
                      for (const o of data.odds) {
                        const key = o.market_type || 'other'
                        if (!groups[key]) groups[key] = []
                        groups[key].push(o)
                      }
                      return Object.entries(groups).map(([type, rows]) => (
                        <div key={type}>
                          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">{type}</p>
                          <div className="bg-zinc-900 rounded-xl border border-zinc-800 overflow-hidden">
                            {rows.map((o, i) => (
                              <div key={i} className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/30">
                                <div className="flex-1 min-w-0">
                                  <span className="text-sm text-white">{o.market_name}</span>
                                  <span className="text-xs text-zinc-500 ml-2">{o.value_name}</span>
                                </div>
                                <div className="text-right shrink-0 ml-3">
                                  <span className="text-green-400 font-black">{Number(o.odd_value).toFixed(2)}</span>
                                  <span className="text-xs text-zinc-600 ml-2">{o.bookmaker_name}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))
                    })()
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
