import { useEffect, useState, useMemo } from 'react'
import {
  Target, Flag, AlertTriangle, AlertCircle,
  Shield, Crosshair, Repeat, TrendingUp, TrendingDown, Minus,
  Home, Globe, Plane, X, Lock,
} from 'lucide-react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id: number) => LOCAL_LEAGUE_LOGOS[id] ?? `/api/proxy/league/${id}.png`

interface League { league_id: number; name: string; season: number; logo_url: string }
interface Game {
  fixture_id: number; match_date: string
  home_team: string; away_team: string
  home_goals: number; away_goals: number; total_goals: number
  total_corners: number; total_yellow_cards: number; total_red_cards: number
  home_shots_on: number; away_shots_on: number; total_shots_on: number
  home_fouls: number; away_fouls: number; total_fouls: number
  home_team_id?: number; away_team_id?: number
}
interface Summary {
  total_games: number
  avg_goals: number; avg_corners: number
  avg_yellow_cards: number; avg_red_cards: number
  avg_fouls: number; avg_shots_on: number
  btts_pct: number; over25_pct: number
}
interface TeamRank {
  team_id: number; team_name: string; games: number
  avg_goals: number; avg_corners: number
  avg_yellows: number; avg_reds: number
  avg_fouls: number; avg_shots_on: number
}

type StatKey = 'goals' | 'corners' | 'yellows' | 'reds' | 'fouls' | 'shots_on' | 'btts' | 'over25'
type RankField = keyof Omit<TeamRank, 'team_id' | 'team_name' | 'games'>
type Context = 'all' | 'home' | 'away'

interface StatDef {
  label: string
  Icon: React.ComponentType<{ className?: string }>
  iconCls: string; high: number; low: number
  rankField: RankField | null; rankLabel: string
}

const STAT_DEFS: Record<StatKey, StatDef> = {
  goals:    { label: 'Gols/jogo',          Icon: Target,        iconCls: 'text-green-400',   high: 2.5, low: 1.5, rankField: 'avg_goals',    rankLabel: 'Gols Marcados' },
  corners:  { label: 'Escanteios/jogo',    Icon: Flag,          iconCls: 'text-blue-400',    high: 10,  low: 7,   rankField: 'avg_corners',  rankLabel: 'Escanteios' },
  yellows:  { label: 'Amarelos/jogo',      Icon: AlertTriangle, iconCls: 'text-yellow-400',  high: 3.5, low: 2,   rankField: 'avg_yellows',  rankLabel: 'Cartões Amarelos' },
  reds:     { label: 'Vermelhos/jogo',     Icon: AlertCircle,   iconCls: 'text-red-400',     high: 0.3, low: 0,   rankField: 'avg_reds',     rankLabel: 'Cartões Vermelhos' },
  fouls:    { label: 'Faltas/jogo',        Icon: Shield,        iconCls: 'text-orange-400',  high: 25,  low: 18,  rankField: 'avg_fouls',    rankLabel: 'Faltas' },
  shots_on: { label: 'Finalizações/jogo',  Icon: Crosshair,     iconCls: 'text-purple-400',  high: 10,  low: 6,   rankField: 'avg_shots_on', rankLabel: 'Finalizações no Gol' },
  btts:     { label: 'BTTS',               Icon: Repeat,        iconCls: 'text-cyan-400',    high: 55,  low: 35,  rankField: null,           rankLabel: '' },
  over25:   { label: 'Over 2.5',           Icon: TrendingUp,    iconCls: 'text-emerald-400', high: 55,  low: 35,  rankField: null,           rankLabel: '' },
}
const STAT_ORDER: StatKey[] = ['goals', 'corners', 'yellows', 'reds', 'fouls', 'shots_on', 'btts', 'over25']

const LIMIT_OPTIONS = [
  { label: '15',   value: 15 },
  { label: '20',   value: 20 },
  { label: '30',   value: 30 },
  { label: '50',   value: 50 },
  { label: 'Todos', value: 0 },
]

function trendCls(v: number, h: number, l: number) {
  return v >= h ? 'text-green-400' : v <= l ? 'text-red-400' : 'text-zinc-400'
}
function trendLbl(v: number, h: number, l: number) {
  return v >= h ? 'Alto' : v <= l ? 'Baixo' : 'Médio'
}
function TrendIcon({ value, high, low }: { value: number; high: number; low: number }) {
  if (value >= high) return <TrendingUp className="w-3 h-3" />
  if (value <= low)  return <TrendingDown className="w-3 h-3" />
  return <Minus className="w-3 h-3" />
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div>
  )
}

function statValue(key: StatKey, s: Summary): number {
  const map: Record<StatKey, number> = {
    goals:    s.avg_goals,
    corners:  s.avg_corners,
    yellows:  s.avg_yellow_cards,
    reds:     s.avg_red_cards,
    fouls:    s.avg_fouls ?? 0,
    shots_on: s.avg_shots_on ?? 0,
    btts:     s.btts_pct,
    over25:   s.over25_pct,
  }
  return map[key]
}

export function EstatisticasContent() {
  const { user } = useAuth()
  const isVip = user?.plan === 'vip' || user?.plan === 'admin' || user?.plan === 'trial'

  const [leagues, setLeagues]       = useState<League[]>([])
  const [leagueId, setLeagueId]     = useState<number | null>(null)
  const [limit, setLimit]           = useState(0)
  const [games, setGames]           = useState<Game[]>([])
  const [summary, setSummary]       = useState<Summary | null>(null)
  const [loading, setLoading]       = useState(false)
  const [leaguesLoading, setLeaguesLoading] = useState(true)
  const [ranking, setRanking]       = useState<TeamRank[]>([])
  const [context, setContext]       = useState<Context>('all')
  const [activeCard, setActiveCard] = useState<StatKey | null>(null)

  useEffect(() => {
    if (!isVip) return
    api.get('/public/leagues')
      .then(r => {
        const ls: League[] = r.data
        setLeagues(ls)
        if (ls.length > 0) setLeagueId(ls[0].league_id)
      })
      .catch(() => {})
      .finally(() => setLeaguesLoading(false))
  }, [isVip])

  useEffect(() => {
    if (!leagueId || !isVip) return
    setLoading(true)
    const apiLimit = limit === 0 ? 500 : limit
    api.get('/suggestions/liga/tendencias', { params: { league_id: leagueId, limit: apiLimit } })
      .then(r => { setGames(r.data.games ?? []); setSummary(r.data.summary ?? null) })
      .catch(() => { setGames([]); setSummary(null) })
      .finally(() => setLoading(false))
  }, [leagueId, limit, isVip])

  useEffect(() => {
    if (!leagueId || !isVip) return
    api.get('/suggestions/liga/ranking', { params: { league_id: leagueId, context } })
      .then(r => setRanking(r.data ?? []))
      .catch(() => setRanking([]))
  }, [leagueId, context, isVip])

  const sortedRanking = useMemo(() => {
    if (!activeCard) return []
    const field = STAT_DEFS[activeCard].rankField
    if (!field) return []
    return [...ranking].sort((a, b) => (b[field] ?? 0) - (a[field] ?? 0))
  }, [ranking, activeCard])

  const selectedLeague = leagues.find(l => l.league_id === leagueId)

  const toggleCard = (key: StatKey) => {
    if (!STAT_DEFS[key].rankField) return
    setActiveCard(prev => prev === key ? null : key)
  }

  // VIP gate
  if (!isVip) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <div className="w-14 h-14 rounded-full bg-zinc-900 flex items-center justify-center">
          <Lock className="w-6 h-6 text-zinc-500" />
        </div>
        <h2 className="text-white font-black text-lg">Recurso VIP</h2>
        <p className="text-zinc-500 text-sm text-center max-w-xs">
          As estatísticas detalhadas são exclusivas para membros VIP.
        </p>
        <a href="/planos" className="btn-primary px-6 py-2 text-sm">Ver planos</a>
      </div>
    )
  }

  return (
    <div className="space-y-6">

        {/* Filtros */}
        <div className="card p-4 flex flex-col sm:flex-row gap-3 items-start sm:items-center">
          <div className="flex-1">
            <label className="text-[10px] text-zinc-600 font-semibold uppercase tracking-widest block mb-1.5">Liga</label>
            {leaguesLoading ? (
              <div className="h-9 bg-zinc-800 rounded-lg animate-pulse w-48" />
            ) : (
              <div className="flex flex-wrap gap-2">
                {leagues.map(l => (
                  <button
                    key={l.league_id}
                    onClick={() => { setLeagueId(l.league_id); setActiveCard(null) }}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors ${
                      leagueId === l.league_id
                        ? 'bg-green-500/10 border-green-500/40 text-green-400'
                        : 'border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-300'
                    }`}
                  >
                    <img src={LEAGUE_LOGO(l.league_id)} alt={l.name} className="w-4 h-4 object-contain"
                      onError={e => (e.currentTarget.style.display = 'none')} />
                    {l.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="shrink-0">
            <label className="text-[10px] text-zinc-600 font-semibold uppercase tracking-widest block mb-1.5">Jogos</label>
            <div className="flex gap-1 flex-wrap">
              {LIMIT_OPTIONS.map(({ label, value }) => (
                <button
                  key={value}
                  onClick={() => setLimit(value)}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors ${
                    limit === value
                      ? 'bg-zinc-700 border-zinc-600 text-white'
                      : 'border-zinc-800 text-zinc-500 hover:border-zinc-700 hover:text-zinc-400'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {loading ? <Spinner /> : !summary ? (
          <div className="card p-12 text-center">
            <p className="text-zinc-500 text-sm">Sem dados para esta liga ainda.</p>
          </div>
        ) : (
          <>
            {/* Liga header */}
            {selectedLeague && (
              <div className="flex items-center gap-3">
                <img src={LEAGUE_LOGO(selectedLeague.league_id)} alt={selectedLeague.name}
                  className="w-8 h-8 object-contain"
                  onError={e => (e.currentTarget.style.display = 'none')} />
                <div>
                  <h2 className="text-white font-black text-base">{selectedLeague.name}</h2>
                  <p className="text-zinc-500 text-xs">
                    Temporada {selectedLeague.season} · <span className="text-green-400 font-bold">{summary.total_games}</span> jogos analisados
                  </p>
                </div>
              </div>
            )}

            {/* Stat cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {STAT_ORDER.map(key => {
                const def = STAT_DEFS[key]
                const val = statValue(key, summary)
                const display = (key === 'btts' || key === 'over25') ? `${val}%` : String(val)
                const cls = trendCls(val, def.high, def.low)
                const isActive = activeCard === key
                const hasRank = !!def.rankField
                const Icon = def.Icon
                return (
                  <button
                    key={key}
                    onClick={() => toggleCard(key)}
                    disabled={!hasRank}
                    className={`card p-3 text-center transition-all select-none ${
                      hasRank ? 'cursor-pointer hover:bg-zinc-800/60 active:scale-95' : 'cursor-default'
                    } ${isActive ? 'ring-1 ring-green-500/40 bg-green-500/5' : ''}`}
                  >
                    <div className={`flex justify-center mb-1 ${def.iconCls}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className={`text-xl font-black ${cls}`}>{display}</div>
                    <div className="text-[9px] text-zinc-600 font-semibold mt-0.5 leading-tight">{def.label}</div>
                    <div className={`flex items-center justify-center gap-0.5 mt-1 text-[9px] font-bold ${cls}`}>
                      <TrendIcon value={val} high={def.high} low={def.low} />
                      {trendLbl(val, def.high, def.low)}
                    </div>
                    {hasRank && (
                      <div className="mt-1.5 text-[9px] text-zinc-600 font-semibold">Ranking →</div>
                    )}
                  </button>
                )
              })}
            </div>

            {/* Ranking modal */}
            {activeCard && STAT_DEFS[activeCard].rankField && (
              <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center" onClick={() => setActiveCard(null)}>
                <div className="absolute inset-0 bg-black/70" />
                <div
                  className="relative z-10 w-full sm:max-w-md bg-zinc-900 rounded-t-2xl sm:rounded-2xl overflow-hidden max-h-[80vh] flex flex-col"
                  onClick={e => e.stopPropagation()}
                >
                  {/* Header */}
                  <div className="px-4 py-4 border-b border-zinc-800 flex items-center justify-between gap-3 shrink-0 bg-zinc-800">
                    <div className="flex items-center gap-2">
                      {(() => {
                        const def = STAT_DEFS[activeCard!]
                        const Icon = def.Icon
                        return <>
                          <Icon className={`w-5 h-5 ${def.iconCls}`} />
                          <h3 className="text-base font-black text-white">Ranking — {def.rankLabel}</h3>
                        </>
                      })()}
                    </div>
                    <button onClick={() => setActiveCard(null)} className="text-zinc-500 hover:text-white p-1 transition-colors">
                      <X className="w-5 h-5" />
                    </button>
                  </div>

                  {/* Context filter */}
                  <div className="flex gap-1.5 px-4 py-3 border-b border-zinc-800 shrink-0">
                    {([
                      { key: 'all',  label: 'Todos', Icon: Globe  },
                      { key: 'home', label: 'Casa',  Icon: Home   },
                      { key: 'away', label: 'Fora',  Icon: Plane  },
                    ] as const).map(({ key, label, Icon }) => (
                      <button
                        key={key}
                        onClick={() => setContext(key)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                          context === key
                            ? 'bg-zinc-700 text-white'
                            : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        {label}
                      </button>
                    ))}
                  </div>

                  {/* List */}
                  <div className="flex-1 overflow-y-auto">
                    {sortedRanking.length === 0 ? (
                      <div className="p-8 text-center text-zinc-500 text-sm">Sem dados de ranking ainda.</div>
                    ) : (
                      <div className="divide-y divide-zinc-800/60">
                        {sortedRanking.map((team, idx) => {
                          const field = STAT_DEFS[activeCard!].rankField!
                          const val = team[field] as number
                          const isFirst = idx === 0
                          const rankCls = idx === 0 ? 'text-yellow-400' : idx === 1 ? 'text-zinc-400' : idx === 2 ? 'text-zinc-500' : 'text-zinc-700'
                          return (
                            <div key={team.team_id}
                              className={`flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/50 transition-colors ${isFirst ? 'bg-green-500/5' : ''}`}>
                              <span className={`text-sm font-black w-6 shrink-0 text-right ${rankCls}`}>{idx + 1}</span>
                              <img src={`/api/proxy/team/${team.team_id}.png`} alt=""
                                className="w-6 h-6 object-contain shrink-0"
                                onError={e => (e.currentTarget.style.display = 'none')} />
                              <span className="text-sm text-zinc-200 font-semibold flex-1 truncate">{team.team_name}</span>
                              <span className="text-[11px] text-zinc-600 shrink-0">{team.games}j</span>
                              <span className={`text-base font-black shrink-0 tabular-nums w-14 text-right ${isFirst ? 'text-green-400' : 'text-zinc-200'}`}>
                                {val.toFixed(2)}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Game table */}
            <div className="card overflow-hidden p-0">
              <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
                <h3 className="text-sm font-black text-white">
                  {limit === 0 ? 'Todos os' : `Últimos ${games.length}`} Jogos
                </h3>
                <div className="hidden sm:flex items-center gap-3 text-[10px] text-zinc-600 font-semibold">
                  <span className="flex items-center gap-1"><Flag className="w-3 h-3" />Escan.</span>
                  <span className="flex items-center gap-1"><AlertTriangle className="w-3 h-3" />Amar.</span>
                  <span className="flex items-center gap-1"><AlertCircle className="w-3 h-3" />Verm.</span>
                  <span className="flex items-center gap-1"><Shield className="w-3 h-3" />Faltas</span>
                </div>
              </div>

              <div className="divide-y divide-zinc-800/60">
                {games.map(g => {
                  const date = new Date(g.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                  const goalsColor = (g.total_goals || 0) >= 3
                    ? 'text-green-400' : (g.total_goals || 0) === 0 ? 'text-red-400' : 'text-zinc-300'
                  return (
                    <div key={g.fixture_id}
                      className="flex items-center gap-2 px-4 py-2.5 hover:bg-zinc-900/50 transition-colors">
                      <span className="text-xs text-zinc-600 w-10 shrink-0 font-semibold">{date}</span>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          {g.home_team_id && (
                            <img src={`/api/proxy/team/${g.home_team_id}.png`} alt=""
                              className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                          <span className="text-sm text-zinc-300 font-semibold truncate">{g.home_team}</span>
                          <span className={`text-sm font-black shrink-0 mx-0.5 ${goalsColor}`}>
                            {g.home_goals ?? '?'} – {g.away_goals ?? '?'}
                          </span>
                          <span className="text-sm text-zinc-300 font-semibold truncate">{g.away_team}</span>
                          {g.away_team_id && (
                            <img src={`/api/proxy/team/${g.away_team_id}.png`} alt=""
                              className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        <span className="text-xs bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-400 font-semibold min-w-[1.75rem] text-center">
                          {g.total_corners ?? '–'}
                        </span>
                        <span className={`text-xs px-1.5 py-0.5 rounded font-semibold min-w-[1.75rem] text-center ${
                          (g.total_yellow_cards || 0) >= 4
                            ? 'bg-yellow-500/10 text-yellow-400' : 'bg-zinc-800 text-zinc-400'
                        }`}>
                          {g.total_yellow_cards ?? '–'}
                        </span>
                        {(g.total_red_cards || 0) > 0 ? (
                          <span className="text-xs bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded font-semibold min-w-[1.75rem] text-center">
                            {g.total_red_cards}
                          </span>
                        ) : (
                          <span className="text-xs text-zinc-800 px-1.5 py-0.5 min-w-[1.75rem] text-center">–</span>
                        )}
                        <span className="hidden sm:block text-xs text-zinc-600 px-1.5 py-0.5 min-w-[2rem] text-center">
                          {g.total_fouls != null ? `${g.total_fouls}f` : '–'}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}
    </div>
  )
}

export default function Estatisticas() {
  return (
    <div className="min-h-screen bg-black">
      <Navbar />
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4">
          <h1 className="text-base font-black text-white tracking-tight">Estatísticas</h1>
          <p className="text-zinc-500 text-xs mt-0.5">Tendências por liga · clique em um card para ver o ranking por time</p>
        </div>
      </div>
      <main className="max-w-5xl mx-auto px-4 py-6">
        <EstatisticasContent />
      </main>
      <Footer />
    </div>
  )
}
