import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import api from '../services/api'
import { Helmet } from 'react-helmet-async'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { winRate as calcWinRate } from '../utils/format'
import { TeamLogo, LeagueLogo } from '../components/TeamLogo'
import FilterPanel, { FilterGroup } from '../components/FilterPanel'
import { useAuth } from '../context/AuthContext'
import PageShell from '../components/PageShell'
import { Button, Spinner } from '../components/ui'
import SuggestionDetail from '../components/SuggestionDetail'
import DailyGreensChart from '../components/DailyGreensChart'

const RESULTADO_OPTIONS = [
  { value: 'all', label: 'Todos' }, { value: 'GREEN', label: 'Green' }, { value: 'RED', label: 'Red' },
  { value: 'PUSH', label: 'Push' }, { value: 'HALF-WIN', label: '½ Win' }, { value: 'HALF-LOSS', label: '½ Loss' },
  { value: 'pending', label: 'Pendente' },
]
const GAMES_PAGE_SIZE = 10

interface Summary {
  total: number; greens: number; reds: number; push: number
  profit: number; stake_total: number; roi: number
}
interface DayResult { match_date: string; total: number; greens: number; reds: number; profit: number }
interface LeagueResult {
  league_id: number | null; league_name: string
  total: number; greens: number; reds: number; profit: number; stake_total: number
}
interface RecentTip {
  match_date: string
  home_team_name: string; away_team_name?: string
  home_team_id?: number; away_team_id?: number
  market?: string; line?: string; odd: number
  result: string; profit: number; source: string
  league_id?: number | null; league_name?: string
}
interface PublicData {
  available_months: string[]
  summary: Summary
  by_day: DayResult[]
  by_league: LeagueResult[]
  recent: RecentTip[]
  recent_total: number
}

/* Os seis pipelines. Faltas e defesas ficavam de fora daqui mesmo o backend
   ja incluindo os dois no agregado: o filtro nao os oferecia e o badge da
   lista caia no valor cru ("faltas" em vez de "Faltas"). */
const SRC_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multiplas: 'Múlt.', alavancagem: 'Alav.',
  faltas: 'Faltas', goleiros: 'Defesas',
}
const SOURCES = ['all', 'vip', 'free', 'multiplas', 'alavancagem', 'faltas', 'goleiros']
const SOURCE_LABELS: Record<string, string> = {
  all: 'Todos', vip: 'VIP', free: 'Free', multiplas: 'Múltiplas',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
}

export default function ResultadosPublicos() {
  const [data, setData] = useState<PublicData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [source, setSource] = useState('all')
  const [month, setMonth] = useState('')
  const [recentLeagueFilter, setRecentLeagueFilter] = useState<string>('')

  const { user } = useAuth()
  const [tab, setTab] = useState<'resumo' | 'por_liga' | 'por_jogo' | 'por_mes'>('resumo')

  // "Picks recentes" · paginação (server-side, ver recent_limit/recent_offset em /public/results)
  const RECENT_PAGE_SIZE = 10
  const [recentPage, setRecentPage] = useState(0)
  const handleSourceChange = (v: string) => { setSource(v); setRecentPage(0); setRecentLeagueFilter('') }
  const handleMonthChange = (v: string) => { setMonth(v); setRecentPage(0); setRecentLeagueFilter('') }

  // "Por Jogo" · exige login (mesmos dados detalhados que antes só existiam em /results)
  const [games, setGames]           = useState<any[]>([])
  const [gamesTotal, setGamesTotal] = useState(0)
  const [gamesPage, setGamesPage]   = useState(0)
  const [gamesFilter, setGamesFilter] = useState('all')
  const [gamesLoading, setGamesLoading] = useState(false)
  const [detailPick, setDetailPick] = useState<{ id: number; pick_type: string } | null>(null)

  // "Por Mês" · também exige login
  const [monthly, setMonthly]   = useState<any[]>([])
  const [monthLoad, setMonthLoad] = useState(false)

  const monthDateRange = (m: string): { date_from?: string; date_to?: string } => {
    if (!m) return {}
    const [y, mo] = m.split('-').map(Number)
    const lastDay = new Date(y, mo, 0).getDate()
    return { date_from: `${m}-01`, date_to: `${m}-${String(lastDay).padStart(2, '0')}` }
  }

  const fetchGames = useCallback((page: number, resultado: string, src: string, m: string) => {
    setGamesLoading(true)
    const { date_from, date_to } = monthDateRange(m)
    const params: any = { limit: GAMES_PAGE_SIZE, offset: page * GAMES_PAGE_SIZE, source: src, days: 3650 }
    if (date_from) params.date_from = date_from
    if (date_to) params.date_to = date_to
    if (resultado !== 'all') params.resultado = resultado
    api.get('/suggestions/results/games', { params })
      .then(r => { setGames(r.data.items); setGamesTotal(r.data.total) })
      .catch(() => { setGames([]); setGamesTotal(0) })
      .finally(() => setGamesLoading(false))
  }, [])

  const fetchMonthly = useCallback((src: string) => {
    setMonthLoad(true)
    api.get('/suggestions/results/monthly', { params: { source: src } })
      .then(r => setMonthly(r.data))
      .catch(() => setMonthly([]))
      .finally(() => setMonthLoad(false))
  }, [])

  useEffect(() => {
    if (!user) return
    if (tab === 'por_jogo') fetchGames(0, gamesFilter, source, month)
    if (tab === 'por_mes')  fetchMonthly(source)
    setGamesPage(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, user, source, month])

  useEffect(() => {
    setLoading(true)
    setError(false)
    const params: Record<string, string | number> = {
      recent_limit: RECENT_PAGE_SIZE,
      recent_offset: recentPage * RECENT_PAGE_SIZE,
    }
    if (source !== 'all') params.source = source
    if (month) params.month = month
    api.get('/public/results', { params })
      .then(r => setData(r.data))
      .catch(() => { setData(null); setError(true) })
      .finally(() => setLoading(false))
  }, [source, month, recentPage])

  const s = data?.summary
  const winRatePct = calcWinRate(s?.greens ?? 0, s?.total ?? 0)
  const months   = data?.available_months ?? []
  const recent   = data?.recent ?? []
  const recentTotal = data?.recent_total ?? 0
  const byDay    = data?.by_day ?? []
  const byLeague = data?.by_league ?? []

  // Metricas derivadas de acerto e cobertura. Esta pagina fala de acuracia da
  // IA, entao nada aqui pode virar dinheiro ou unidade: quem quer ver retorno
  // tem a Banca, que e' por usuario e depende da stake de cada um.
  const leaguesCovered = byLeague.length
  const daysWithPicks  = byDay.length
  const avgPerDay = daysWithPicks > 0 && s ? s.total / daysWithPicks : null
  // Liga com melhor aproveitamento. Piso de 5 picks pra uma liga com 1 green
  // em 1 pick nao aparecer como "melhor" em 100%.
  const bestLeague = byLeague
    .filter(l => l.total >= 5)
    .map(l => ({ name: l.league_name, id: l.league_id, wr: calcWinRate(l.greens, l.total) ?? 0 }))
    .sort((a, b) => b.wr - a.wr)[0] ?? null
  // Maior sequencia de dias seguidos com saldo positivo (mais greens que reds).
  const bestStreak = (() => {
    let cur = 0, best = 0
    for (const d of [...byDay].sort((a, b) => a.match_date.localeCompare(b.match_date))) {
      if (d.greens > d.reds) { cur += 1; best = Math.max(best, cur) } else { cur = 0 }
    }
    return best
  })()

  return (
    <PageShell
      title="Resultados · Pick IA"
      description="Histórico completo dos picks da IA com win rate auditável por liga, por jogo e por mês. Todos os picks registrados, qualquer pessoa pode conferir."
      canonical="https://pickia.com.br/resultados"
      nav={user ? true : (
        <nav className="border-b border-line/60 bg-surface-0/80 backdrop-blur-sm sticky top-0 z-40">
          <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
            <Link to="/" className="font-display text-ink-1 font-semibold text-lg tracking-tight">
              Pick<span className="text-accent">IA</span>
            </Link>
            <Button to="/login" variant="ghost" size="sm">Entrar</Button>
          </div>
        </nav>
      )}
      bar={{
        back: true,
        title: 'Resultados da IA',
        sub: 'Histórico auditável de todos os picks. Atualizado automaticamente.',
      }}
    >
        <AnimatePresence>
        {detailPick && (
          <SuggestionDetail
            id={detailPick.id}
            pickType={detailPick.pick_type}
            onClose={() => setDetailPick(null)}
          />
        )}
        </AnimatePresence>

          {/* Filtros */}
          <FilterPanel
            accent="green"
            groups={[
              {
                key: 'source', label: 'Fonte',
                options: SOURCES.map(src => ({ value: src, label: SOURCE_LABELS[src] })),
                value: source, onChange: handleSourceChange,
              },
              ...(months.length > 0 ? [{
                key: 'month', label: 'Mês',
                options: [{ value: '', label: 'Todos os meses' }, ...months.map(m => ({ value: m, label: m }))],
                value: month, onChange: handleMonthChange,
              } as FilterGroup] : []),
            ]}
          />

          {/* Abas · Por Liga e' publica; Por Jogo/Por Mes exigem login (dado detalhado por usuario) */}
          <div className="flex border-b border-line mb-6 overflow-x-auto">
            {/* Por Jogo/Por Mes exigem login, mas a aba aparece pra todo mundo:
                sumir da barra sem explicacao fazia parecer que a pagina estava
                quebrada. Deslogado, a aba abre um convite pra entrar. */}
            {([
              ['resumo', 'Resumo'], ['por_liga', 'Por Liga'],
              ['por_jogo', 'Por Jogo'], ['por_mes', 'Por Mês'],
            ] as [typeof tab, string][]).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`tab px-5 py-3 text-sm font-semibold ${tab === k ? 'tab-active' : ''}`}>{l}</button>
            ))}
          </div>

          {tab === 'resumo' && (loading ? (
            <div className="flex justify-center py-20">
              <Spinner size="lg" />
            </div>
          ) : error ? (
            <div className="text-center py-16 text-ink-3">
              Não foi possível carregar os resultados agora. Tente novamente em instantes.
            </div>
          ) : !s || s.total === 0 ? (
            <div className="text-center py-16 text-ink-3">Nenhum resultado encontrado para os filtros selecionados.</div>
          ) : (
            <>
              {/* Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
                {[
                  { label: 'Win Rate', value: `${winRatePct}%`,   color: (winRatePct ?? 0) >= 55 ? 'text-green-500' : 'text-ink-2' },
                  { label: 'Picks',    value: String(s.total),    color: 'text-ink-1' },
                  { label: 'Greens',   value: String(s.greens),   color: 'text-green-400' },
                  { label: 'Reds',     value: String(s.reds),     color: 'text-red-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="stat-tile">
                    <div className={`stat-value ${color}`}>{value}</div>
                    <div className="stat-label">{label}</div>
                  </div>
                ))}
              </div>

              {/* Cobertura e consistencia · segunda leva de numeros, todos de
                  volume/acerto. Nenhum deles vira dinheiro. */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
                {[
                  { label: 'Ligas',        value: String(leaguesCovered), color: 'text-ink-1' },
                  { label: 'Dias com pick', value: String(daysWithPicks),  color: 'text-ink-1' },
                  { label: 'Picks por dia', value: avgPerDay != null ? avgPerDay.toFixed(1) : '·', color: 'text-ink-1' },
                  { label: 'Seq. positiva', value: bestStreak > 0 ? `${bestStreak}d` : '·', color: bestStreak > 0 ? 'text-green-400' : 'text-ink-2' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="stat-tile">
                    <div className={`stat-value ${color}`}>{value}</div>
                    <div className="stat-label">{label}</div>
                  </div>
                ))}
              </div>

              {/* Gráfico por dia */}
              {byDay.length > 1 && (
                <div className="panel p-5 mb-8">
                  <p className="panel-label mb-4">Picks por dia</p>
                  <DailyGreensChart data={byDay} />
                </div>
              )}

              {/* Liga com melhor aproveitamento */}
              {bestLeague && (
                <div className="panel mb-8">
                  <div className="panel-head">
                    <span className="panel-label">Melhor aproveitamento</span>
                    <span className="panel-meta">mín. 5 picks</span>
                  </div>
                  <div className="flex items-center gap-3 px-5 py-4">
                    {bestLeague.id != null
                      ? <LeagueLogo id={bestLeague.id} name={bestLeague.name} />
                      : <div className="w-4.5 h-4.5 rounded-full bg-surface-2 shrink-0" />}
                    <span className="text-sm font-semibold text-ink-1 flex-1 min-w-0 truncate">{bestLeague.name}</span>
                    <span className="font-mono text-xl font-black text-green-400 shrink-0">{bestLeague.wr}%</span>
                  </div>
                </div>
              )}

              {/* Aproveitamento por liga · barra em vez de so' numero, pra dar
                  leitura visual de quais ligas a IA acerta mais. */}
              {byLeague.length > 1 && (
                <div className="panel mb-8">
                  <div className="panel-head">
                    <span className="panel-label">Aproveitamento por liga</span>
                    <span className="panel-meta">{byLeague.length} ligas</span>
                  </div>
                  <div className="px-5 py-4 space-y-3">
                    {[...byLeague]
                      .map(lg => ({ ...lg, wr: calcWinRate(lg.greens, lg.total) ?? 0 }))
                      .sort((a, b) => b.wr - a.wr)
                      .map(lg => (
                        <div key={`bar-${lg.league_id ?? lg.league_name}`} className="flex items-center gap-3">
                          <span className="text-[11px] text-ink-3 w-28 shrink-0 truncate">{lg.league_name}</span>
                          <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${lg.wr >= 55 ? 'bg-green-500' : 'bg-ink-4'}`}
                              style={{ width: `${Math.max(2, Math.min(100, lg.wr))}%` }}
                            />
                          </div>
                          <span className="font-mono text-[11px] font-bold text-ink-2 w-9 text-right shrink-0">{lg.wr}%</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Lista recente */}
              {recent.length > 0 && (() => {
                const recentLeagues = Array.from(new Set(recent.map(t => t.league_name).filter(Boolean))) as string[]
                const filteredRecent = recentLeagueFilter ? recent.filter(t => t.league_name === recentLeagueFilter) : recent
                return (
                <div className="panel">
                  <div className="panel-head">
                    <span className="panel-label">Picks recentes</span>
                    <span className="panel-meta">{recentTotal} resultados</span>
                  </div>
                  {recentLeagues.length > 1 && (
                    <div className="flex gap-2 flex-wrap px-4 pt-3">
                      <button
                        onClick={() => setRecentLeagueFilter('')}
                        className={`pill ${!recentLeagueFilter ? 'pill-active' : ''}`}
                      >
                        Todas
                      </button>
                      {recentLeagues.map(lg => (
                        <button
                          key={lg}
                          onClick={() => setRecentLeagueFilter(lg === recentLeagueFilter ? '' : lg)}
                          className={`pill ${recentLeagueFilter === lg ? 'pill-active' : ''}`}
                        >
                          {lg}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="divide-y divide-line/50">
                    {filteredRecent.map((tip, i) => (
                      <div key={i} className="flex items-center gap-2 px-4 py-3">
                        <span className="text-[10px] text-ink-4 shrink-0 w-12">
                          {new Date(tip.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                        </span>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[tip.source] ?? ''}`}>
                          {SRC_LBL[tip.source] ?? tip.source}
                        </span>
                        <div className="flex items-center gap-1.5 flex-1 min-w-0">
                          <div className="flex items-center gap-1 min-w-0 shrink">
                            <TeamLogo id={tip.home_team_id} name={tip.home_team_name} size={16} />
                            <span className="text-xs text-ink-2 truncate">{tip.home_team_name}</span>
                          </div>
                          {tip.away_team_name && (
                            <>
                              <span className="text-[10px] text-ink-4 shrink-0">x</span>
                              <div className="flex items-center gap-1 min-w-0 shrink">
                                <TeamLogo id={tip.away_team_id} name={tip.away_team_name} size={16} />
                                <span className="text-xs text-ink-2 truncate">{tip.away_team_name}</span>
                              </div>
                            </>
                          )}
                        </div>
                        <span className="text-[11px] text-ink-3 shrink-0 hidden sm:block truncate max-w-[100px]">
                          {tip.market?.split(' ').slice(0, 3).join(' ')} {tip.line ?? ''}
                        </span>
                        <span className="font-mono text-xs font-bold text-ink-2 shrink-0">{Number(tip.odd).toFixed(2)}</span>
                        {(() => {
                          const rs = getResultStyle(tip.result)
                          return (
                            <span className={`text-xs font-black px-2 py-0.5 rounded border shrink-0 ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-ink-3'}`}>
                              {rs ? rs.label : tip.result}
                            </span>
                          )
                        })()}
                      </div>
                    ))}
                  </div>
                  {recentTotal > RECENT_PAGE_SIZE && (() => {
                    const totalPages = Math.ceil(recentTotal / RECENT_PAGE_SIZE)
                    return (
                      <div className="flex items-center justify-center gap-1 py-4 border-t border-line/50">
                        <button disabled={recentPage === 0} onClick={() => setRecentPage(p => p - 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors">Ant</button>
                        <span className="text-xs text-ink-3 px-2">{recentPage + 1} / {totalPages}</span>
                        <button disabled={(recentPage + 1) * RECENT_PAGE_SIZE >= recentTotal} onClick={() => setRecentPage(p => p + 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors">Próx</button>
                      </div>
                    )
                  })()}
                </div>
                )
              })()}
            </>
          ))}

          {tab === 'por_liga' && (loading ? (
            <div className="flex justify-center py-20">
              <Spinner size="lg" />
            </div>
          ) : error ? (
            <div className="text-center py-16 text-ink-3">
              Não foi possível carregar os resultados agora. Tente novamente em instantes.
            </div>
          ) : byLeague.length === 0 ? (
            <div className="text-center py-16 text-ink-3">Nenhum resultado de liga encontrado para os filtros selecionados.</div>
          ) : (
            <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
              <div className="px-5 py-3 border-b border-line">
                <span className="text-xs font-bold text-ink-2">Resultados por liga</span>
              </div>
              <div className="divide-y divide-line/50">
                {byLeague.map((lg) => {
                  const wr = calcWinRate(lg.greens, lg.total)
                  return (
                    <div key={`${lg.league_id ?? lg.league_name}`} className="flex items-center gap-3 px-5 py-3">
                      {lg.league_id != null
                        ? <LeagueLogo id={lg.league_id} name={lg.league_name} />
                        : <div className="w-4.5 h-4.5 rounded-full bg-surface-2 shrink-0" />}
                      <span className="text-sm font-semibold text-ink-1 flex-1 min-w-0 truncate">{lg.league_name}</span>
                      <span className="text-[11px] text-ink-4 shrink-0 hidden sm:block">{lg.total} picks</span>
                      <span className="font-mono text-[11px] text-ink-4 w-16 text-right shrink-0 hidden sm:block">
                        {lg.greens}G · {lg.reds}R
                      </span>
                      <span className={`font-mono text-xs font-black w-12 text-right shrink-0 ${(wr ?? 0) >= 55 ? 'text-green-400' : 'text-ink-2'}`}>
                        {wr}%
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}

          {(tab === 'por_jogo' || tab === 'por_mes') && !user && (
            <div className="panel px-5 py-14 text-center">
              <p className="text-sm text-ink-2 font-semibold mb-1">
                {tab === 'por_jogo' ? 'Resultado pick a pick' : 'Fechamento mês a mês'}
              </p>
              <p className="text-xs text-ink-3 mb-5 max-w-sm mx-auto leading-relaxed">
                Essa visão detalhada é para quem tem conta. Criar é de graça e leva menos de um minuto.
              </p>
              <Link to="/login?mode=register" className="btn-primary inline-block text-sm">
                Criar conta grátis
              </Link>
            </div>
          )}

          {tab === 'por_jogo' && user && (
            <div>
              <div className="mb-4">
                <FilterPanel
                  accent="green"
                  groups={[{
                    key: 'resultado', label: 'Resultado',
                    options: RESULTADO_OPTIONS,
                    value: gamesFilter, onChange: (v: string) => { setGamesFilter(v); setGamesPage(0); fetchGames(0, v, source, month) },
                  }]}
                />
              </div>
              <p className="text-ink-4 text-xs mb-4">{gamesTotal} picks</p>
              {gamesLoading ? (
                <div className="flex justify-center py-16">
                  <Spinner size="lg" />
                </div>
              ) : games.length === 0 ? (
                <div className="text-center py-16 text-ink-3 text-sm">Nenhum pick encontrado.</div>
              ) : (
                <>
                  <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
                    <div className="divide-y divide-line/50">
                      {games.map(g => {
                        const rs = getResultStyle(g.result)
                        const badge = rs ? `${rs.bg} ${rs.text} ${rs.border}` : 'bg-surface-3/50 text-ink-2 border-line-strong'
                        return (
                          <div key={`${g.pick_type}-${g.id}`}
                            className="flex items-center gap-2 px-4 py-3 hover:bg-surface-1/50 transition-colors cursor-pointer"
                            onClick={() => setDetailPick({ id: g.id, pick_type: g.pick_type })}>
                            <span className="text-[10px] text-ink-4 shrink-0 w-12">
                              {new Date(g.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                            </span>
                            {g.pick_type && source === 'all' && (
                              <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[g.pick_type] ?? ''}`}>
                                {g.pick_type === 'alavancagem' ? 'Alav.' : g.pick_type === 'multipla' ? 'Múlt.' : g.pick_type.toUpperCase()}
                              </span>
                            )}
                            <div className="flex items-center gap-1.5 flex-1 min-w-0">
                              <div className="flex items-center gap-1 min-w-0 shrink">
                                <TeamLogo id={g.home_team_id} name={g.home_team_name} size={16} />
                                <span className="text-xs text-ink-2 truncate">{g.home_team_name}</span>
                              </div>
                              {g.away_team_name && g.pick_type !== 'multipla' && (
                                <>
                                  <span className="text-[10px] text-ink-4 shrink-0">x</span>
                                  <div className="flex items-center gap-1 min-w-0 shrink">
                                    <TeamLogo id={g.away_team_id} name={g.away_team_name} size={16} />
                                    <span className="text-xs text-ink-2 truncate">{g.away_team_name}</span>
                                  </div>
                                </>
                              )}
                            </div>
                            <span className="text-[11px] text-ink-3 shrink-0 hidden sm:block truncate max-w-[120px]">
                              {g.market}{g.line ? ` · ${g.line}` : ''}
                            </span>
                            <span className="font-mono text-xs font-bold text-ink-2 shrink-0">{g.odd ? Number(g.odd).toFixed(2) : ''}</span>
                            {g.result ? (
                              <span className={`text-xs font-black px-2 py-0.5 rounded border shrink-0 ${badge}`}>{rs ? rs.label : g.result}</span>
                            ) : (
                              <span className="text-ink-4 text-xs shrink-0">Pendente</span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                  {gamesTotal > GAMES_PAGE_SIZE && (() => {
                    const totalPages = Math.ceil(gamesTotal / GAMES_PAGE_SIZE)
                    const goTo = (p: number) => { setGamesPage(p); fetchGames(p, gamesFilter, source, month) }
                    return (
                      <div className="flex items-center justify-center gap-1 mt-4 flex-wrap">
                        <button disabled={gamesPage === 0} onClick={() => goTo(gamesPage - 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors">Ant</button>
                        <span className="text-xs text-ink-3 px-2">{gamesPage + 1} / {totalPages}</span>
                        <button disabled={(gamesPage + 1) * GAMES_PAGE_SIZE >= gamesTotal} onClick={() => goTo(gamesPage + 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors">Próx</button>
                      </div>
                    )
                  })()}
                </>
              )}
            </div>
          )}

          {tab === 'por_mes' && user && (
            monthLoad ? (
              <div className="flex justify-center py-16">
                <Spinner size="lg" />
              </div>
            ) : monthly.length === 0 ? (
              <div className="text-center py-16 text-ink-3 text-sm">Nenhum resultado mensal encontrado.</div>
            ) : (
              <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[460px]">
                    <thead>
                      <tr className="border-b border-line">
                        {['Mês', 'Picks', 'Greens', 'Reds', 'Win %'].map(h => (
                          <th key={h} className="text-left text-ink-3 font-medium px-3 sm:px-5 py-3 text-xs">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="font-mono">
                      {monthly.map((m: any) => {
                        const wr = m.win_rate ?? calcWinRate(m.greens, m.total) ?? 0
                        const reds = m.reds ?? 0
                        const [year, mo] = (m.month ?? '').split('-')
                        const label = new Date(Number(year), Number(mo) - 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
                        return (
                          <tr key={m.month} className="border-b border-line/50 hover:bg-surface-1/50 transition-colors">
                            <td className="px-3 sm:px-5 py-3 text-ink-1 font-semibold capitalize font-sans">{label}</td>
                            <td className="px-3 sm:px-5 py-3 text-ink-2">{m.total}</td>
                            <td className="px-3 sm:px-5 py-3 text-green-500 font-semibold">{m.greens}</td>
                            <td className="px-3 sm:px-5 py-3 text-red-400 font-semibold">{reds}</td>
                            <td className="px-3 sm:px-5 py-3">
                              <div className="flex items-center gap-2">
                                <div className="bg-surface-2 rounded-full h-1.5 w-16">
                                  <div className="bg-green-500 h-1.5 rounded-full" style={{ width: `${wr}%` }} />
                                </div>
                                <span className={`text-xs font-bold ${wr >= 55 ? 'text-green-400' : 'text-ink-2'}`}>{wr}%</span>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          )}

          {/* CTA · só faz sentido pra quem ainda não tem conta */}
          {!user && (
          <div className="mt-12 text-center">
            <p className="text-ink-3 text-sm mb-4">Quer receber esses picks antes de acontecerem?</p>
            <Button to="/login?mode=register" size="lg">
              Criar conta · 2 dias VIP grátis
            </Button>
          </div>
          )}
    </PageShell>
  )
}
