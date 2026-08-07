import { useEffect, useState, useMemo } from 'react'
import {
  Target, Flag, AlertTriangle, AlertCircle,
  Shield, Crosshair, Repeat, TrendingUp, TrendingDown, Minus,
  Home, Globe, Plane, X, Lock,
} from 'lucide-react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import PageShell from '../components/PageShell'
import { SpinnerBlock } from '../components/ui'
import FilterPanel from '../components/FilterPanel'

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
  return v >= h ? 'text-green-400' : v <= l ? 'text-red-400' : 'text-ink-2'
}
function trendLbl(v: number, h: number, l: number) {
  return v >= h ? 'Alto' : v <= l ? 'Baixo' : 'Médio'
}
function TrendIcon({ value, high, low }: { value: number; high: number; low: number }) {
  if (value >= high) return <TrendingUp className="w-3 h-3" />
  if (value <= low)  return <TrendingDown className="w-3 h-3" />
  return <Minus className="w-3 h-3" />
}

/* Carregamento desta tela. O spinner em si vem de ui/Spinner: aqui só a altura. */
function StatsLoading() {
  return <SpinnerBlock className="py-20" />
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
        <div className="w-14 h-14 rounded-full bg-surface-1 flex items-center justify-center">
          <Lock className="w-6 h-6 text-ink-3" />
        </div>
        <h2 className="text-ink-1 font-bold text-lg">Recurso VIP</h2>
        <p className="text-ink-3 text-sm text-center max-w-xs">
          As estatísticas detalhadas são exclusivas para membros VIP.
        </p>
        <a href="/planos" className="btn-primary px-6 py-2 text-sm">Ver planos</a>
      </div>
    )
  }

  return (
    <div className="space-y-6">

        {/* Filtros */}
        {leaguesLoading ? (
          <div className="h-9 bg-surface-2 rounded-lg animate-pulse w-48" />
        ) : (
          <FilterPanel
            accent="green"
            groups={[
              {
                key: 'league', label: 'Liga',
                options: leagues.map(l => ({
                  value: String(l.league_id), label: l.name,
                  icon: <img src={LEAGUE_LOGO(l.league_id)} alt={l.name} width={16} height={16} className="w-4 h-4 object-contain"
                          onError={e => (e.currentTarget.style.display = 'none')} />,
                })),
                value: String(leagueId ?? leagues[0]?.league_id ?? ''),
                onChange: v => { setLeagueId(Number(v)); setActiveCard(null) },
              },
              {
                key: 'limit', label: 'Jogos',
                options: LIMIT_OPTIONS.map(o => ({ value: String(o.value), label: o.label })),
                value: String(limit), defaultValue: '0',
                onChange: v => setLimit(Number(v)),
              },
            ]}
          />
        )}

        {loading ? <StatsLoading /> : !summary ? (
          <div className="card p-12 text-center">
            <p className="text-ink-3 text-sm">Sem dados para esta liga ainda.</p>
          </div>
        ) : (
          <>
            {/* Liga header */}
            {selectedLeague && (
              <div className="flex items-center gap-3">
                <img src={LEAGUE_LOGO(selectedLeague.league_id)} alt={selectedLeague.name}
                  width={32} height={32} className="w-8 h-8 object-contain"
                  onError={e => (e.currentTarget.style.display = 'none')} />
                <div>
                  <h2 className="text-ink-1 font-bold text-base">{selectedLeague.name}</h2>
                  <p className="text-ink-3 text-xs">
                    Temporada {selectedLeague.season} · <span className="font-mono text-green-400 font-bold">{summary.total_games}</span> jogos analisados
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
                      hasRank ? 'cursor-pointer hover:bg-surface-2/60 active:scale-95' : 'cursor-default'
                    } ${isActive ? 'ring-1 ring-green-500/40 bg-green-500/5' : ''}`}
                  >
                    <div className={`flex justify-center mb-1 ${def.iconCls}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className={`font-mono text-xl font-black ${cls}`}>{display}</div>
                    <div className="text-[9px] text-ink-4 font-semibold mt-0.5 leading-tight">{def.label}</div>
                    <div className={`flex items-center justify-center gap-0.5 mt-1 text-[9px] font-bold ${cls}`}>
                      <TrendIcon value={val} high={def.high} low={def.low} />
                      {trendLbl(val, def.high, def.low)}
                    </div>
                    {hasRank && (
                      <div className="mt-1.5 text-[9px] text-ink-4 font-semibold">Ranking</div>
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
                  className="relative z-10 w-full sm:max-w-md bg-surface-1 rounded-t-lg sm:rounded-lg overflow-hidden max-h-[80vh] flex flex-col"
                  onClick={e => e.stopPropagation()}
                >
                  {/* Header */}
                  <div className="px-4 py-4 border-b border-line flex items-center justify-between gap-3 shrink-0 bg-surface-2">
                    <div className="flex items-center gap-2">
                      {(() => {
                        const def = STAT_DEFS[activeCard!]
                        const Icon = def.Icon
                        return <>
                          <Icon className={`w-5 h-5 ${def.iconCls}`} />
                          <h3 className="text-base font-bold text-ink-1">Ranking: {def.rankLabel}</h3>
                        </>
                      })()}
                    </div>
                    <button onClick={() => setActiveCard(null)} className="text-ink-3 hover:text-ink-1 p-1 transition-colors">
                      <X className="w-5 h-5" />
                    </button>
                  </div>

                  {/* Context filter */}
                  <div className="flex gap-1.5 px-4 py-3 border-b border-line shrink-0">
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
                            ? 'bg-surface-3 text-ink-1'
                            : 'bg-surface-2 text-ink-3 hover:text-ink-2'
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
                      <div className="p-8 text-center text-ink-3 text-sm">Sem dados de ranking ainda.</div>
                    ) : (
                      <div className="divide-y divide-line/60">
                        {sortedRanking.map((team, idx) => {
                          const field = STAT_DEFS[activeCard!].rankField!
                          const val = team[field] as number
                          const isFirst = idx === 0
                          const rankCls = idx === 0 ? 'text-yellow-400' : idx === 1 ? 'text-ink-2' : idx === 2 ? 'text-ink-3' : 'text-ink-4'
                          return (
                            <div key={team.team_id}
                              className={`flex items-center gap-3 px-4 py-3 hover:bg-surface-2/50 transition-colors ${isFirst ? 'bg-green-500/5' : ''}`}>
                              <span className={`font-mono text-sm font-black w-6 shrink-0 text-right ${rankCls}`}>{idx + 1}</span>
                              <img src={`/api/proxy/team/${team.team_id}.png`} alt=""
                                width={24} height={24} className="w-6 h-6 object-contain shrink-0"
                                onError={e => (e.currentTarget.style.display = 'none')} />
                              <span className="text-sm text-ink-2 font-semibold flex-1 truncate">{team.team_name}</span>
                              <span className="font-mono text-[11px] text-ink-4 shrink-0">{team.games}j</span>
                              <span className={`font-mono text-base font-black shrink-0 tabular-nums w-14 text-right ${isFirst ? 'text-green-400' : 'text-ink-2'}`}>
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
              <div className="px-4 py-3 border-b border-line flex items-center justify-between">
                <h3 className="text-sm font-bold text-ink-1">
                  {limit === 0 ? 'Todos os' : `Últimos ${games.length}`} Jogos
                </h3>
                <div className="hidden sm:flex items-center gap-3 text-[10px] text-ink-4 font-semibold">
                  <span className="flex items-center gap-1"><Flag className="w-3 h-3" />Escan.</span>
                  <span className="flex items-center gap-1"><AlertTriangle className="w-3 h-3" />Amar.</span>
                  <span className="flex items-center gap-1"><AlertCircle className="w-3 h-3" />Verm.</span>
                  <span className="flex items-center gap-1"><Shield className="w-3 h-3" />Faltas</span>
                </div>
              </div>

              <div className="divide-y divide-line/60">
                {games.map(g => {
                  const date = new Date(g.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                  const goalsColor = (g.total_goals || 0) >= 3
                    ? 'text-green-400' : (g.total_goals || 0) === 0 ? 'text-red-400' : 'text-ink-2'
                  return (
                    <div key={g.fixture_id}
                      className="flex items-center gap-2 px-4 py-2.5 hover:bg-surface-1/50 transition-colors">
                      <span className="font-mono text-xs text-ink-4 w-10 shrink-0 font-semibold">{date}</span>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          {g.home_team_id && (
                            <img src={`/api/proxy/team/${g.home_team_id}.png`} alt=""
                              width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                          <span className="text-sm text-ink-2 font-semibold truncate">{g.home_team}</span>
                          <span className={`font-mono text-sm font-black shrink-0 mx-0.5 ${goalsColor}`}>
                            {g.home_goals ?? '?'} – {g.away_goals ?? '?'}
                          </span>
                          <span className="text-sm text-ink-2 font-semibold truncate">{g.away_team}</span>
                          {g.away_team_id && (
                            <img src={`/api/proxy/team/${g.away_team_id}.png`} alt=""
                              width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                        </div>
                      </div>

                      <div className="font-mono flex items-center gap-1 shrink-0">
                        <span className="text-xs bg-surface-2 px-1.5 py-0.5 rounded text-ink-2 font-semibold min-w-[1.75rem] text-center">
                          {g.total_corners ?? '–'}
                        </span>
                        <span className={`text-xs px-1.5 py-0.5 rounded font-semibold min-w-[1.75rem] text-center ${
                          (g.total_yellow_cards || 0) >= 4
                            ? 'bg-yellow-500/10 text-yellow-400' : 'bg-surface-2 text-ink-2'
                        }`}>
                          {g.total_yellow_cards ?? '–'}
                        </span>
                        {(g.total_red_cards || 0) > 0 ? (
                          <span className="text-xs bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded font-semibold min-w-[1.75rem] text-center">
                            {g.total_red_cards}
                          </span>
                        ) : (
                          <span className="text-xs text-line-strong px-1.5 py-0.5 min-w-[1.75rem] text-center">–</span>
                        )}
                        <span className="hidden sm:block text-xs text-ink-4 px-1.5 py-0.5 min-w-[2rem] text-center">
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
    <PageShell
      title="Estatísticas"
      description="Tendências por liga e ranking por time nos mercados que a IA analisa."
      noindex
      width="full"
      bar={{
        title: 'Estatísticas',
        sub: 'Tendências por liga · clique em um card para ver o ranking por time',
      }}
    >
      <EstatisticasContent />
    </PageShell>
  )
}
