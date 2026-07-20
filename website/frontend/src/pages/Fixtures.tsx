import { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import Navbar from '../components/Navbar'
import FixtureStatsModal from '../components/FixtureStatsModal'
import { EstatisticasContent } from './Estatisticas'
import { useAuth } from '../context/AuthContext'
import BackButton from '../components/BackButton'

// Data de hoje no fuso de Brasília (toISOString retorna UTC e quebraria de madrugada)
const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

function shiftDate(dateStr: string, days: number): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  const dt = new Date(y, m - 1, d + days)
  return dt.toLocaleDateString('en-CA')
}

function formatDateLabel(dateStr: string): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })
}

const DAY_SHORT = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']

function DateStrip({ date, onChange }: { date: string; onChange: (d: string) => void }) {
  const stripRef = useRef<HTMLDivElement>(null)
  // Pivot: semana começando 3 dias antes da data selecionada (7 dias visíveis)
  const [anchor, setAnchor] = useState(() => shiftDate(date, -3))

  const days = Array.from({ length: 7 }, (_, i) => shiftDate(anchor, i))

  const prev = () => setAnchor(a => shiftDate(a, -7))
  const next = () => setAnchor(a => shiftDate(a, 7))
  const goToday = () => {
    setAnchor(shiftDate(TODAY, -3))
    onChange(TODAY)
  }

  return (
    <div className="flex items-center gap-1">
      <button onClick={prev}
        className="w-7 h-7 flex items-center justify-center rounded-lg text-zinc-500 hover:text-white hover:bg-zinc-800 transition-colors text-sm shrink-0">
        ‹
      </button>
      <div ref={stripRef} className="flex gap-1 overflow-hidden">
        {days.map(d => {
          const [y, mo, dy] = d.split('-').map(Number)
          const dt = new Date(y, mo - 1, dy)
          const isToday  = d === TODAY
          const isActive = d === date
          return (
            <button key={d} onClick={() => onChange(d)}
              className={`flex flex-col items-center justify-center w-10 h-12 rounded-xl transition-all shrink-0 ${
                isActive
                  ? 'bg-green-500 text-black font-black shadow-lg shadow-green-500/20'
                  : isToday
                  ? 'bg-green-500/10 border border-green-500/30 text-green-400 font-semibold'
                  : 'text-zinc-400 hover:bg-zinc-800 hover:text-white'
              }`}>
              <span className="text-[9px] uppercase tracking-wider leading-none mb-0.5">
                {DAY_SHORT[dt.getDay()]}
              </span>
              <span className="text-sm font-black leading-none">{dy}</span>
            </button>
          )
        })}
      </div>
      <button onClick={next}
        className="w-7 h-7 flex items-center justify-center rounded-lg text-zinc-500 hover:text-white hover:bg-zinc-800 transition-colors text-sm shrink-0">
        ›
      </button>
      {date !== TODAY && (
        <button onClick={goToday}
          className="text-[10px] font-bold px-2 py-1 rounded-lg border border-green-500/40 text-green-500 hover:bg-green-500/10 transition-colors shrink-0 ml-0.5">
          Hoje
        </button>
      )}
    </div>
  )
}

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

const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null

const LOCAL_LEAGUE_LOGOS: Record<number, string> = {
  1: '/logo-copa-mundo.png',
}
const leagueLogo = (league_id: number) =>
  LOCAL_LEAGUE_LOGOS[league_id] ?? `/api/proxy/league/${league_id}.png`

function TeamLogo({ id, name, side }: { id?: number; name: string; side: 'left' | 'right' }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={32} height={32}
      className={`w-8 h-8 object-contain shrink-0 ${side === 'left' ? 'order-last' : 'order-first'}`}
      onError={e => (e.currentTarget.style.display = 'none')} />
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

interface LiveStats {
  home_corners: number
  away_corners: number
  home_shots_on: number
  away_shots_on: number
  home_yellow: number
  away_yellow: number
  home_possession: number
  away_possession: number
}

type PageTab = 'jogos' | 'estatistica'

export default function Fixtures() {
  const { isVip, isAdmin, user }   = useAuth()
  const canSeeStats = isVip || isAdmin || user?.plan === 'trial'
  const [pageTab, setPageTab]      = useState<PageTab>('jogos')
  const [date, setDate]            = useState(TODAY)
  const [fixtures, setFixtures]    = useState<Fixture[]>([])
  const [loading, setLoading]      = useState(true)
  const [statsFixture, setStatsFixture] = useState<Fixture | null>(null)
  const [lockPrompt, setLockPrompt]    = useState(false)
  const [collapsed, setCollapsed]      = useState<Set<string>>(new Set())
  const [liveStats, setLiveStats]      = useState<Record<number, LiveStats>>({})

  function fetchFixtures(d: string) {
    setLoading(true)
    api.get('/fixtures/today', { params: { date: d } })
      .then(r => setFixtures(r.data))
      .catch(() => setFixtures([]))
      .finally(() => setLoading(false))
  }

  function handleDateChange(d: string) {
    setDate(d)
    setLiveStats({})
    fetchFixtures(d)
  }

  function toggleCollapse(key: string) {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  useEffect(() => { fetchFixtures(TODAY) }, [])

  // Atualiza estatísticas ao vivo a cada 30s para jogos em andamento
  useEffect(() => {
    const liveGames = fixtures.filter(f => isLive(f.status))
    if (liveGames.length === 0) return
    const fetchAll = () => {
      liveGames.forEach(f => {
        api.get(`/live/fixture/${f.fixture_id}/live-stats`)
          .then(r => setLiveStats(prev => ({ ...prev, [f.fixture_id]: r.data })))
          .catch(() => {})
      })
    }
    fetchAll()
    const timer = setInterval(fetchAll, 30_000)
    return () => clearInterval(timer)
  }, [fixtures])

  // Agrupa por liga (preserva ordem de aparição)
  const grouped: { key: string; league_id: number; logo?: string; flag?: string; country?: string; games: Fixture[] }[] = []
  const seen = new Set<string>()
  for (const f of fixtures) {
    if (!seen.has(f.league_name)) {
      seen.add(f.league_name)
      grouped.push({
        key: f.league_name,
        league_id: f.league_id,
        logo: leagueLogo(f.league_id),
        flag: f.league_flag,
        country: f.league_country,
        games: [],
      })
    }
    grouped.find(g => g.key === f.league_name)!.games.push(f)
  }

  const dateLabel  = formatDateLabel(date)
  const liveCount  = fixtures.filter(f => isLive(f.status)).length
  const pickCount  = fixtures.filter(f => f.has_pick).length

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 pt-4 pb-0">
          {/* Título + badges */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <BackButton />
              <div>
                <h1 className="text-base font-black text-white">Jogos</h1>
                <p className="text-zinc-500 text-xs mt-0.5 capitalize">{dateLabel}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {pageTab === 'jogos' && pickCount > 0 && (
                <div className="hidden sm:flex items-center gap-1.5 bg-green-500/10 border border-green-500/20 rounded-lg px-2.5 py-1.5">
                  <span className="text-green-400 text-xs font-bold">{pickCount} picks IA</span>
                </div>
              )}
              {pageTab === 'jogos' && liveCount > 0 && (
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
                  <span className="text-green-500 text-xs font-bold">{liveCount} ao vivo</span>
                </div>
              )}
            </div>
          </div>

          {/* Strip de dias */}
          {pageTab === 'jogos' && (
            <div className="mb-3">
              <DateStrip date={date} onChange={handleDateChange} />
            </div>
          )}
          {/* Page tabs */}
          <div className="flex border-b border-zinc-800">
            {([
              { key: 'jogos',       label: 'Jogos' },
              { key: 'estatistica', label: 'Estatísticas' },
            ] as { key: PageTab; label: string }[]).map(t => (
              <button
                key={t.key}
                onClick={() => setPageTab(t.key)}
                className={`px-4 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px ${
                  pageTab === t.key
                    ? 'text-white border-green-500'
                    : 'text-zinc-500 border-transparent hover:text-zinc-300'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {pageTab === 'estatistica' && (
        <main className="max-w-5xl mx-auto px-4 py-6">
          <EstatisticasContent />
        </main>
      )}

      {pageTab === 'jogos' && <main className="max-w-5xl mx-auto px-4 py-6">

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
            {grouped.map(({ key: league, league_id, logo, flag, country, games }) => {
              const isCopa = league_id === 1
              return (
              <div key={league} className={`card overflow-hidden ${isCopa ? 'border border-yellow-500/20' : ''}`}>

                {/* Cabeçalho da liga com logo + bandeira (clicável para recolher) */}
                <div
                  className={`px-4 py-3 border-b flex items-center gap-2.5 cursor-pointer select-none ${isCopa ? 'bg-yellow-950/40 border-yellow-700/30' : 'bg-zinc-800/60 border-zinc-800'}`}
                  onClick={() => toggleCollapse(league)}
                >
                  {logo && (
                    <img src={logo} alt={league} width={24} height={24}
                      className="w-6 h-6 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      />
                  )}
                  <span className={`text-xs font-bold ${isCopa ? 'text-yellow-300' : 'text-zinc-300'}`}>{league}</span>
                  {country && (
                    <span className={`text-xs font-normal ${isCopa ? 'text-yellow-700' : 'text-zinc-600'}`}>{country}</span>
                  )}
                  {flag && (
                    <img src={flag} alt={country ?? ''} width={18} height={13}
                      className="h-3.5 object-contain shrink-0 rounded-sm"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      />
                  )}
                  {isCopa && <span className="text-[10px] font-black text-yellow-500 uppercase tracking-wider ml-1">Copa do Mundo</span>}
                  <span className={`text-xs ml-auto ${isCopa ? 'text-yellow-700' : 'text-zinc-600'}`}>{games.length} {games.length === 1 ? 'jogo' : 'jogos'}</span>
                  <svg
                    className={`w-3.5 h-3.5 shrink-0 transition-transform duration-200 ${collapsed.has(league) ? '-rotate-90' : ''} ${isCopa ? 'text-yellow-700' : 'text-zinc-600'}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>

                {/* Jogos */}
                {!collapsed.has(league) && <div className="divide-y divide-zinc-800/50">
                  {games.map(f => {
                    const st       = STATUS_MAP[f.status] ?? { label: f.status, color: 'text-zinc-500' }
                    const live     = isLive(f.status)
                    const finished = isFinished(f.status)
                    const time     = f.match_datetime
                      ? new Date(f.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
                      : '--:--'

                    const ls = liveStats[f.fixture_id]

                    return (
                      <div key={f.fixture_id}>
                      <div
                        className={`flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/30 transition-colors cursor-pointer ${f.has_pick ? 'border-l-2 border-green-500/40' : ''}`}
                        onClick={() => canSeeStats ? setStatsFixture(f) : setLockPrompt(true)}
                      >

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

                        {/* Badge de pick IA + lock hint */}
                        <div className="shrink-0 flex flex-col items-end gap-0.5 w-[72px]">
                          {f.has_pick && (
                            <>
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
                            </>
                          )}
                          {!canSeeStats && (
                            <svg className="w-3 h-3 text-zinc-700 mt-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                            </svg>
                          )}
                        </div>
                      </div>

                      {/* Stats ao vivo · aparece apenas quando o jogo está em andamento */}
                      {live && ls && (
                        <div className="px-4 py-2 bg-green-950/20 border-t border-green-900/20 grid grid-cols-4 gap-1 text-center">
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-0.5">Esc</div>
                            <div className="text-xs font-bold text-zinc-300">{ls.home_corners} <span className="text-zinc-600">-</span> {ls.away_corners}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-0.5">Fin</div>
                            <div className="text-xs font-bold text-zinc-300">{ls.home_shots_on} <span className="text-zinc-600">-</span> {ls.away_shots_on}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-0.5">Cart</div>
                            <div className="text-xs font-bold text-zinc-300">{ls.home_yellow} <span className="text-zinc-600">-</span> {ls.away_yellow}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-0.5">Posse</div>
                            <div className="text-xs font-bold text-zinc-300">{ls.home_possession}% <span className="text-zinc-600">-</span> {ls.away_possession}%</div>
                          </div>
                        </div>
                      )}
                      </div>
                    )
                  })}
                </div>}
              </div>
            )
            })}
          </div>
        )}
      </main>}

      {statsFixture && (
        <FixtureStatsModal
          fixture={statsFixture}
          onClose={() => setStatsFixture(null)}
        />
      )}

      {/* Lock modal para usuários free */}
      {lockPrompt && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4"
          onClick={() => setLockPrompt(false)}>
          <div className="bg-zinc-950 border border-zinc-800 rounded-2xl p-8 max-w-sm w-full text-center shadow-2xl overflow-y-auto max-h-[92dvh]"
            onClick={e => e.stopPropagation()}>
            <div className="w-14 h-14 rounded-full bg-yellow-400/10 border border-yellow-400/20 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <h3 className="text-white font-black text-lg mb-2">Análise exclusiva VIP</h3>
            <p className="text-zinc-400 text-sm mb-6 leading-relaxed">
              Médias de gols, escanteios, cartões, histórico H2H e estatísticas completas por time. Disponível para assinantes VIP.
            </p>
            <Link to="/checkout"
              className="block bg-yellow-400 hover:bg-yellow-300 text-black font-black px-6 py-3 rounded-xl transition-colors text-sm mb-3">
              Assinar VIP
            </Link>
            <button onClick={() => setLockPrompt(false)}
              className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors">
              Fechar
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
