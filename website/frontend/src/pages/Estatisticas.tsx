import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import api from '../services/api'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id: number) =>
  LOCAL_LEAGUE_LOGOS[id] ?? `/api/proxy/league/${id}.png`

interface League { league_id: number; name: string; season: number; logo_url: string }
interface Game {
  fixture_id: number; match_date: string
  home_team: string; away_team: string
  home_goals: number; away_goals: number; total_goals: number
  total_corners: number; total_yellow_cards: number; total_red_cards: number
  home_shots_on: number; away_shots_on: number
  home_team_id?: number; away_team_id?: number
}
interface Summary {
  total_games: number; avg_goals: number; avg_corners: number
  avg_yellow_cards: number; avg_red_cards: number
  btts_pct: number; over25_pct: number
}

function TrendIcon({ value, high, low }: { value: number; high: number; low: number }) {
  if (value >= high) return <TrendingUp className="w-3.5 h-3.5 text-green-400" />
  if (value <= low)  return <TrendingDown className="w-3.5 h-3.5 text-red-400" />
  return <Minus className="w-3.5 h-3.5 text-zinc-500" />
}

function trendLabel(value: number, high: number, low: number) {
  if (value >= high) return { label: 'Alto', cls: 'text-green-400' }
  if (value <= low)  return { label: 'Baixo', cls: 'text-red-400' }
  return { label: 'Médio', cls: 'text-zinc-400' }
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div>
  )
}

export default function Estatisticas() {
  const [leagues, setLeagues]       = useState<League[]>([])
  const [leagueId, setLeagueId]     = useState<number | null>(null)
  const [limit, setLimit]           = useState(15)
  const [games, setGames]           = useState<Game[]>([])
  const [summary, setSummary]       = useState<Summary | null>(null)
  const [loading, setLoading]       = useState(false)
  const [leaguesLoading, setLeaguesLoading] = useState(true)

  useEffect(() => {
    api.get('/public/leagues')
      .then(r => {
        const ls: League[] = r.data
        setLeagues(ls)
        if (ls.length > 0) setLeagueId(ls[0].league_id)
      })
      .catch(() => {})
      .finally(() => setLeaguesLoading(false))
  }, [])

  useEffect(() => {
    if (!leagueId) return
    setLoading(true)
    api.get('/suggestions/liga/tendencias', { params: { league_id: leagueId, limit } })
      .then(r => {
        setGames(r.data.games ?? [])
        setSummary(r.data.summary ?? null)
      })
      .catch(() => { setGames([]); setSummary(null) })
      .finally(() => setLoading(false))
  }, [leagueId, limit])

  const selectedLeague = leagues.find(l => l.league_id === leagueId)

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      {/* Header */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-base font-black text-white tracking-tight">Estatísticas</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Tendências por liga — últimos jogos</p>
          </div>
        </div>
      </div>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">

        {/* Filtros */}
        <div className="card p-4 flex flex-col sm:flex-row gap-3 items-start sm:items-center">
          {/* Seletor de liga */}
          <div className="flex-1">
            <label className="text-[10px] text-zinc-600 font-semibold uppercase tracking-widest block mb-1.5">Liga</label>
            {leaguesLoading ? (
              <div className="h-9 bg-zinc-800 rounded-lg animate-pulse w-48" />
            ) : (
              <div className="flex flex-wrap gap-2">
                {leagues.map(l => (
                  <button
                    key={l.league_id}
                    onClick={() => setLeagueId(l.league_id)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors ${
                      leagueId === l.league_id
                        ? 'bg-green-500/10 border-green-500/40 text-green-400'
                        : 'border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-300'
                    }`}
                  >
                    <img
                      src={LEAGUE_LOGO(l.league_id)}
                      alt={l.name}
                      className="w-4 h-4 object-contain"
                      onError={e => (e.currentTarget.style.display = 'none')}
                    />
                    {l.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Número de jogos */}
          <div className="shrink-0">
            <label className="text-[10px] text-zinc-600 font-semibold uppercase tracking-widest block mb-1.5">Jogos</label>
            <div className="flex gap-1">
              {[10, 15, 20, 30].map(n => (
                <button
                  key={n}
                  onClick={() => setLimit(n)}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors ${
                    limit === n
                      ? 'bg-zinc-700 border-zinc-600 text-white'
                      : 'border-zinc-800 text-zinc-500 hover:border-zinc-700 hover:text-zinc-400'
                  }`}
                >
                  {n}
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
            {/* Header da liga selecionada */}
            {selectedLeague && (
              <div className="flex items-center gap-3">
                <img
                  src={LEAGUE_LOGO(selectedLeague.league_id)}
                  alt={selectedLeague.name}
                  className="w-8 h-8 object-contain"
                  onError={e => (e.currentTarget.style.display = 'none')}
                />
                <div>
                  <h2 className="text-white font-black text-base">{selectedLeague.name}</h2>
                  <p className="text-zinc-500 text-xs">Temporada {selectedLeague.season} · {summary.total_games} jogos analisados</p>
                </div>
              </div>
            )}

            {/* Cards de médias */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {([
                { emoji: '⚽', label: 'Gols/jogo',      numVal: summary.avg_goals,        display: String(summary.avg_goals),        high: 2.5,  low: 1.5 },
                { emoji: '🟨', label: 'Amarelos/jogo',  numVal: summary.avg_yellow_cards, display: String(summary.avg_yellow_cards), high: 3.5,  low: 2   },
                { emoji: '🟥', label: 'Vermelhos/jogo', numVal: summary.avg_red_cards,    display: String(summary.avg_red_cards),    high: 0.3,  low: 0   },
                { emoji: '⛳', label: 'Escanteios/jogo',numVal: summary.avg_corners,       display: String(summary.avg_corners),      high: 10,   low: 7   },
                { emoji: '🎯', label: 'BTTS',           numVal: summary.btts_pct,          display: `${summary.btts_pct}%`,           high: 55,   low: 35  },
                { emoji: '📈', label: 'Over 2.5',       numVal: summary.over25_pct,        display: `${summary.over25_pct}%`,         high: 55,   low: 35  },
              ] as const).map(({ emoji, label, numVal, display, high, low }) => {
                const { label: tLabel, cls } = trendLabel(numVal, high, low)
                return (
                  <div key={label} className="card p-4 text-center">
                    <div className="text-xl mb-1">{emoji}</div>
                    <div className={`text-2xl font-black ${cls}`}>{display}</div>
                    <div className="text-[10px] text-zinc-600 font-semibold mt-0.5 leading-tight">{label}</div>
                    <div className={`flex items-center justify-center gap-1 mt-1 text-[10px] font-bold ${cls}`}>
                      <TrendIcon value={numVal} high={high} low={low} />
                      {tLabel}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Tabela de jogos */}
            <div className="card overflow-hidden p-0">
              <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
                <h3 className="text-sm font-black text-white">Últimos {games.length} Jogos</h3>
                <div className="hidden sm:flex items-center gap-4 text-[10px] text-zinc-600 font-semibold">
                  <span>⛳ Escan.</span>
                  <span>🟨 Amar.</span>
                  <span>🟥 Verm.</span>
                </div>
              </div>

              <div className="divide-y divide-zinc-800/60">
                {games.map(g => {
                  const date = new Date(g.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                  const goalsColor = (g.total_goals || 0) >= 3
                    ? 'text-green-400'
                    : (g.total_goals || 0) === 0
                    ? 'text-red-400'
                    : 'text-zinc-300'

                  return (
                    <div key={g.fixture_id} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-900/50 transition-colors">
                      {/* Data */}
                      <span className="text-xs text-zinc-600 w-10 shrink-0 font-semibold">{date}</span>

                      {/* Times e placar */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          {g.home_team_id && (
                            <img src={`/api/proxy/team/${g.home_team_id}.png`} alt="" className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                          <span className="text-sm text-zinc-300 font-semibold truncate">{g.home_team}</span>
                          <span className={`text-sm font-black shrink-0 mx-1 ${goalsColor}`}>
                            {g.home_goals ?? '?'} – {g.away_goals ?? '?'}
                          </span>
                          <span className="text-sm text-zinc-300 font-semibold truncate">{g.away_team}</span>
                          {g.away_team_id && (
                            <img src={`/api/proxy/team/${g.away_team_id}.png`} alt="" className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                        </div>
                      </div>

                      {/* Stats */}
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-xs bg-zinc-800 px-2 py-0.5 rounded text-zinc-400 font-semibold min-w-[2rem] text-center">
                          ⛳{g.total_corners ?? '–'}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded font-semibold min-w-[2rem] text-center ${
                          (g.total_yellow_cards || 0) >= 4
                            ? 'bg-yellow-500/10 text-yellow-400'
                            : 'bg-zinc-800 text-zinc-400'
                        }`}>
                          🟨{g.total_yellow_cards ?? '–'}
                        </span>
                        {(g.total_red_cards || 0) > 0 ? (
                          <span className="text-xs bg-red-500/10 text-red-400 px-2 py-0.5 rounded font-semibold min-w-[2rem] text-center">
                            🟥{g.total_red_cards}
                          </span>
                        ) : (
                          <span className="text-xs text-zinc-700 min-w-[2rem] text-center">🟥–</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </main>

      <Footer />
    </div>
  )
}
