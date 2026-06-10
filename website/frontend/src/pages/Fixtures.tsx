import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import Navbar from '../components/Navbar'

// Data de hoje no fuso de Brasília (toISOString retorna UTC e quebraria de madrugada)
const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  NS:   { label: 'Agendado',    color: 'text-zinc-400' },
  '1H': { label: 'AO VIVO 1T', color: 'text-green-400' },
  HT:   { label: 'Intervalo',  color: 'text-yellow-400' },
  '2H': { label: 'AO VIVO 2T', color: 'text-green-400' },
  ET:   { label: 'Prorr.',     color: 'text-orange-400' },
  FT:   { label: 'Encerrado',  color: 'text-zinc-500' },
  AET:  { label: 'Enc. Prorr.', color: 'text-zinc-500' },
  PEN:  { label: 'Pênaltis',   color: 'text-zinc-500' },
  CANC: { label: 'Cancelado',  color: 'text-red-500' },
  PST:  { label: 'Adiado',     color: 'text-red-400' },
}

function isLive(status: string)     { return ['1H', 'HT', '2H', 'ET', 'BT', 'P'].includes(status) }
function isFinished(status: string) { return ['FT', 'AET', 'PEN'].includes(status) }

const TEAM_LOGO = (id?: number) => id ? `https://media.api-sports.io/football/teams/${id}.png` : null

const LOCAL_LEAGUE_LOGOS: Record<number, string> = {
  1: '/logo-copa-mundo.png',
}
const leagueLogo = (league_id: number, apiLogo?: string) =>
  LOCAL_LEAGUE_LOGOS[league_id] ?? apiLogo

function TeamLogo({ id, name, side }: { id?: number; name: string; side: 'left' | 'right' }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={32} height={32}
      className={`w-8 h-8 object-contain shrink-0 ${side === 'left' ? 'order-last' : 'order-first'}`}
      onError={e => (e.currentTarget.style.display = 'none')}
      loading="lazy" />
  )
}

interface Fixture {
  fixture_id: number
  match_datetime: string
  home_team: string
  away_team: string
  home_team_id?: number
  away_team_id?: number
  league_name: string
  league_logo?: string
  league_flag?: string
  league_country?: string
  league_id: number
  status: string
  elapsed?: number | null
  home_goals: number | null
  away_goals: number | null
  has_pick?: boolean
  pick_market?: string | null
  pick_type_flag?: 'vip' | 'free' | null
}

export default function Fixtures() {
  const navigate                = useNavigate()
  const [date, setDate]         = useState(TODAY)
  const [fixtures, setFixtures] = useState<Fixture[]>([])
  const [loading, setLoading]   = useState(true)

  function fetchFixtures(d: string) {
    setLoading(true)
    api.get('/fixtures/today', { params: { date: d } })
      .then(r => setFixtures(r.data))
      .catch(() => setFixtures([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchFixtures(TODAY) }, [])

  // Agrupa por liga (preserva ordem de aparição)
  const grouped: { key: string; league_id: number; logo?: string; flag?: string; country?: string; games: Fixture[] }[] = []
  const seen = new Set<string>()
  for (const f of fixtures) {
    if (!seen.has(f.league_name)) {
      seen.add(f.league_name)
      grouped.push({
        key: f.league_name,
        league_id: f.league_id,
        logo: leagueLogo(f.league_id, f.league_logo),
        flag: f.league_flag,
        country: f.league_country,
        games: [],
      })
    }
    grouped.find(g => g.key === f.league_name)!.games.push(f)
  }

  const todayLabel = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })
  const liveCount  = fixtures.filter(f => isLive(f.status)).length
  const pickCount  = fixtures.filter(f => f.has_pick).length

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate(-1)} className="text-zinc-500 hover:text-white transition-colors text-lg leading-none">←</button>
            <div>
              <h1 className="text-base font-black text-white">Jogos do Dia</h1>
              <p className="text-zinc-500 text-xs mt-0.5 capitalize">{todayLabel}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {pickCount > 0 && (
              <div className="flex items-center gap-1.5 bg-green-500/10 border border-green-500/20 rounded-lg px-2.5 py-1.5">
                <svg className="w-3 h-3 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M9 12l-2-2-1.5 1.5L9 15l5.5-5.5L13 8l-4 4z" />
                  <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
                </svg>
                <span className="text-green-400 text-xs font-bold">{pickCount} {pickCount === 1 ? 'pick' : 'picks'} IA</span>
              </div>
            )}
            {liveCount > 0 && (
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
                <span className="text-green-500 text-xs font-bold">{liveCount} ao vivo</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <main className="max-w-5xl mx-auto px-4 py-6">

        {/* Banner informativo */}
        <div className="flex items-start gap-3 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 mb-5">
          <svg className="w-4 h-4 text-zinc-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p className="text-zinc-400 text-xs leading-relaxed">
              Exibindo apenas jogos das <span className="text-white font-semibold">ligas monitoradas pela IA</span>.
              Os picks são gerados automaticamente antes de cada rodada e aparecem com o badge <span className="text-green-400 font-semibold">Pick IA</span> no jogo correspondente.
            </p>
          </div>
        </div>

        {/* Navegação de data */}
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => { const d = new Date(date); d.setDate(d.getDate() - 1); const s = d.toISOString().slice(0, 10); setDate(s); fetchFixtures(s) }}
            className="btn-ghost text-sm px-3 py-2"
          >←</button>
          <input type="date" value={date}
            onChange={e => { setDate(e.target.value); fetchFixtures(e.target.value) }}
            className="input text-sm py-2 max-w-[160px]" />
          <button
            onClick={() => { const d = new Date(date); d.setDate(d.getDate() + 1); const s = d.toISOString().slice(0, 10); setDate(s); fetchFixtures(s) }}
            className="btn-ghost text-sm px-3 py-2"
          >→</button>
          <button
            onClick={() => { setDate(TODAY); fetchFixtures(TODAY) }}
            className={`text-xs px-3 py-2 rounded-lg border transition-colors ${date === TODAY ? 'border-green-500 text-green-500' : 'border-zinc-700 text-zinc-500 hover:border-zinc-500'}`}
          >
            Hoje
          </button>
          <span className="text-zinc-600 text-xs ml-auto">{fixtures.length} jogos</span>
        </div>

        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
          </div>
        ) : fixtures.length === 0 ? (
          <div className="card p-12 text-center border-dashed">
            <p className="text-zinc-600 text-sm">Nenhum jogo encontrado para esta data.</p>
            <p className="text-zinc-700 text-xs mt-2">As ligas monitoradas não têm jogos programados neste dia.</p>
          </div>
        ) : (
          <div className="space-y-5">
            {grouped.map(({ key: league, logo, flag, country, games }) => (
              <div key={league} className="card overflow-hidden">

                {/* Cabeçalho da liga com logo + bandeira */}
                <div className="px-4 py-3 bg-zinc-800/60 border-b border-zinc-800 flex items-center gap-2.5">
                  {logo && (
                    <img src={logo} alt={league} width={24} height={24}
                      className="w-6 h-6 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      loading="lazy" />
                  )}
                  <span className="text-xs font-bold text-zinc-300">{league}</span>
                  {country && (
                    <span className="text-xs text-zinc-600 font-normal">{country}</span>
                  )}
                  {flag && (
                    <img src={flag} alt={country ?? ''} width={18} height={13}
                      className="h-3.5 object-contain shrink-0 rounded-sm"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      loading="lazy" />
                  )}
                  <span className="text-xs text-zinc-600 ml-auto">{games.length} {games.length === 1 ? 'jogo' : 'jogos'}</span>
                </div>

                {/* Jogos */}
                <div className="divide-y divide-zinc-800/50">
                  {games.map(f => {
                    const st       = STATUS_MAP[f.status] ?? { label: f.status, color: 'text-zinc-500' }
                    const live     = isLive(f.status)
                    const finished = isFinished(f.status)
                    const time     = f.match_datetime
                      ? new Date(f.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
                      : '--:--'

                    return (
                      <div key={f.fixture_id} className={`flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/30 transition-colors ${f.has_pick ? 'border-l-2 border-green-500/40' : ''}`}>

                        {/* Hora / status */}
                        <div className="w-20 shrink-0 text-center">
                          {live ? (
                            <div className="flex flex-col items-center">
                              <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse mb-1" />
                              <span className="text-xs font-bold text-green-400 leading-tight">
                                {f.elapsed ? `${f.elapsed}'` : st.label}
                              </span>
                            </div>
                          ) : finished ? (
                            <span className={`text-xs ${st.color}`}>{st.label}</span>
                          ) : (
                            <span className="text-sm font-bold text-zinc-300">{time}</span>
                          )}
                        </div>

                        {/* Times + placar */}
                        <div className="flex-1 flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 flex-1 justify-end min-w-0">
                            <span className={`text-sm font-semibold truncate ${live ? 'text-white' : 'text-zinc-300'}`}>
                              {f.home_team}
                            </span>
                            <TeamLogo id={f.home_team_id} name={f.home_team} side="left" />
                          </div>

                          <div className="shrink-0 flex items-center gap-1.5">
                            {finished || live ? (
                              <>
                                <span className={`w-7 h-7 flex items-center justify-center rounded-lg text-sm font-black ${live ? 'bg-green-500/10 text-green-400' : 'bg-zinc-800 text-white'}`}>
                                  {f.home_goals ?? 0}
                                </span>
                                <span className="text-zinc-600 text-xs">×</span>
                                <span className={`w-7 h-7 flex items-center justify-center rounded-lg text-sm font-black ${live ? 'bg-green-500/10 text-green-400' : 'bg-zinc-800 text-white'}`}>
                                  {f.away_goals ?? 0}
                                </span>
                              </>
                            ) : (
                              <span className="text-zinc-600 text-sm font-bold px-2">vs</span>
                            )}
                          </div>

                          <div className="flex items-center gap-2 flex-1 justify-start min-w-0">
                            <TeamLogo id={f.away_team_id} name={f.away_team} side="right" />
                            <span className={`text-sm font-semibold truncate ${live ? 'text-white' : 'text-zinc-300'}`}>
                              {f.away_team}
                            </span>
                          </div>
                        </div>

                        {/* Badge de pick IA */}
                        {f.has_pick ? (
                          <div className="shrink-0 flex flex-col items-end gap-0.5">
                            <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border ${
                              f.pick_type_flag === 'vip'
                                ? 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
                                : 'text-green-400 bg-green-500/10 border-green-500/20'
                            }`}>
                              Pick IA
                            </span>
                            {f.pick_market && (
                              <span className="text-[10px] text-zinc-500 max-w-[72px] truncate text-right">
                                {f.pick_market}
                              </span>
                            )}
                          </div>
                        ) : (
                          <div className="w-[72px] shrink-0" />
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
