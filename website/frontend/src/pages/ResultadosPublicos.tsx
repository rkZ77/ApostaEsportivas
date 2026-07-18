import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import { Helmet } from 'react-helmet-async'
import { Share2 } from 'lucide-react'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { winRate as calcWinRate } from '../utils/format'
import { TeamLogo, LeagueLogo } from '../components/TeamLogo'
import { useShareResultsImage, useShareTodayGamesImage } from '../hooks/useShareStoryImage'
import FilterPanel, { FilterGroup } from '../components/FilterPanel'

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
}

const SRC_LBL: Record<string, string> = { vip: 'VIP', free: 'Free', multiplas: 'Múlt.', alavancagem: 'Alav.' }
const SOURCES = ['all', 'vip', 'free', 'multiplas', 'alavancagem']
const SOURCE_LABELS: Record<string, string> = { all: 'Todos', vip: 'VIP', free: 'Free', multiplas: 'Múltiplas', alavancagem: 'Alavancagem' }

function BarChart({ days }: { days: DayResult[] }) {
  if (!days.length) return null
  const maxTotal = Math.max(...days.map(d => d.total), 1)
  return (
    <div className="flex items-end gap-0.5 h-16 w-full overflow-hidden">
      {days.map((d, i) => {
        const heightPct = (d.total / maxTotal) * 100
        const isGreen = d.greens >= d.reds
        return (
          <div key={i} className="flex-1 flex flex-col items-center justify-end group relative" title={`${d.match_date}: ${d.greens}G / ${d.reds}R`}>
            <div
              className={`w-full rounded-sm transition-opacity group-hover:opacity-80 ${isGreen ? 'bg-green-500/60' : 'bg-red-500/50'}`}
              style={{ height: `${heightPct}%`, minHeight: 2 }}
            />
          </div>
        )
      })}
    </div>
  )
}

export default function ResultadosPublicos() {
  const [data, setData] = useState<PublicData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [source, setSource] = useState('all')
  const [month, setMonth] = useState('')
  const [todayGames, setTodayGames] = useState<any[]>([])
  const [recentLeagueFilter, setRecentLeagueFilter] = useState<string>('')

  const shareResults = useShareResultsImage()
  const shareTodayGames = useShareTodayGamesImage()

  useEffect(() => {
    setLoading(true)
    setError(false)
    const params: Record<string, string> = {}
    if (source !== 'all') params.source = source
    if (month) params.month = month
    api.get('/public/results', { params })
      .then(r => setData(r.data))
      .catch(() => { setData(null); setError(true) })
      .finally(() => setLoading(false))
    setRecentLeagueFilter('')
  }, [source, month])

  useEffect(() => {
    api.get('/public/fixtures-today')
      .then(r => setTodayGames(r.data ?? []))
      .catch(() => {})
  }, [])

  const s = data?.summary
  const winRatePct = calcWinRate(s?.greens ?? 0, s?.total ?? 0)
  const profit  = s ? Number(s.profit) : null
  const months   = data?.available_months ?? []
  const recent   = data?.recent ?? []
  const byDay    = data?.by_day ?? []
  const byLeague = data?.by_league ?? []

  const now = new Date()
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const todayResult = byDay.find(d => d.match_date === todayStr)
  const todayWinRate = todayResult ? calcWinRate(todayResult.greens, todayResult.total) : null

  return (
    <>
      <Helmet>
        <title>Resultados · Pick IA</title>
        <meta name="description" content="Histórico completo dos picks da IA com win rate auditável, lucro acumulado e picks recentes." />
      </Helmet>

      <div className="min-h-screen bg-black text-white">
        {/* Nav */}
        <nav className="border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-sm sticky top-0 z-40">
          <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
            <Link to="/" className="text-white font-black text-lg tracking-tight">
              Pick<span className="text-green-400">IA</span>
            </Link>
            <Link to="/login" className="text-xs font-bold text-green-400 border border-green-500/30 px-3 py-1.5 rounded-lg hover:bg-green-500/10 transition-colors">
              Entrar
            </Link>
          </div>
        </nav>

        <main className="max-w-5xl mx-auto px-4 py-10">
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-black mb-2">Resultados da IA</h1>
            <p className="text-zinc-400 text-sm">Histórico auditável de todos os picks. Atualizado automaticamente.</p>
          </div>

          {/* Filtros */}
          <FilterPanel
            accent="green"
            groups={[
              {
                key: 'source', label: 'Fonte',
                options: SOURCES.map(src => ({ value: src, label: SOURCE_LABELS[src] })),
                value: source, onChange: setSource,
              },
              ...(months.length > 0 ? [{
                key: 'month', label: 'Mês',
                options: [{ value: '', label: 'Todos os meses' }, ...months.map(m => ({ value: m, label: m }))],
                value: month, onChange: setMonth,
              } as FilterGroup] : []),
            ]}
          />

          {loading ? (
            <div className="flex justify-center py-20">
              <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-16 text-zinc-500">
              Não foi possível carregar os resultados agora. Tente novamente em instantes.
            </div>
          ) : !s || s.total === 0 ? (
            <div className="text-center py-16 text-zinc-500">Nenhum resultado encontrado para os filtros selecionados.</div>
          ) : (
            <>
              {/* Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
                {[
                  { label: 'Win Rate',  value: `${winRatePct}%`,            color: (winRatePct ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-300' },
                  { label: 'Total',     value: String(s.total),          color: 'text-white' },
                  { label: 'Greens',    value: String(s.greens),         color: 'text-green-400' },
                  { label: 'Lucro (u)', value: `${profit != null && profit >= 0 ? '+' : ''}${profit?.toFixed(1) ?? '0'}u`, color: (profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-zinc-950 border border-zinc-800 rounded-2xl p-4 text-center">
                    <div className={`text-2xl font-black ${color}`}>{value}</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">{label}</div>
                  </div>
                ))}
              </div>

              {/* Compartilhar */}
              <div className="flex flex-wrap gap-2 justify-center mb-8">
                <button
                  onClick={() => shareResults.share({ winRatePct: winRatePct ?? 0, total: s.total, greens: s.greens, reds: s.reds, profit: profit ?? 0 })}
                  disabled={shareResults.sharing}
                  className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                >
                  <Share2 className="w-3.5 h-3.5" />
                  {shareResults.shared ? 'Compartilhado!' : shareResults.sharing ? 'Gerando...' : 'Compartilhar resultado'}
                </button>
                {todayResult && todayResult.total > 0 && (
                  <button
                    onClick={() => shareResults.share({
                      winRatePct: todayWinRate ?? 0,
                      total: todayResult.total,
                      greens: todayResult.greens,
                      reds: todayResult.reds,
                      profit: Number(todayResult.profit),
                      badgeLabel: 'RESULTADO DE HOJE',
                      footerText: new Date(todayStr + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' }),
                      shareText: `Hoje a IA da Pick IA fechou ${todayResult.greens}G / ${todayResult.reds}R (${Math.round(todayWinRate ?? 0)}%). Histórico 100% auditável.`,
                    })}
                    disabled={shareResults.sharing}
                    className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                  >
                    <Share2 className="w-3.5 h-3.5" />
                    {shareResults.shared ? 'Compartilhado!' : shareResults.sharing ? 'Gerando...' : 'Compartilhar resultado de hoje'}
                  </button>
                )}
                {todayGames.length > 0 && (
                  <button
                    onClick={() => shareTodayGames.share(todayGames.map(g => ({
                      homeTeamName: g.home_team, awayTeamName: g.away_team,
                      homeTeamId: g.home_team_id, awayTeamId: g.away_team_id,
                      leagueName: g.league_name, matchDatetime: g.match_datetime,
                    })))}
                    disabled={shareTodayGames.sharing}
                    className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg bg-yellow-400/10 border border-yellow-400/30 text-yellow-400 hover:bg-yellow-400/20 transition-colors disabled:opacity-50"
                  >
                    <Share2 className="w-3.5 h-3.5" />
                    {shareTodayGames.shared ? 'Compartilhado!' : shareTodayGames.sharing ? 'Gerando...' : 'Compartilhar jogos de hoje'}
                  </button>
                )}
              </div>

              {/* Gráfico por dia */}
              {byDay.length > 1 && (
                <div className="bg-zinc-950 border border-zinc-800 rounded-2xl p-5 mb-8">
                  <p className="text-sm text-zinc-500 font-bold mb-4">Picks por dia</p>
                  <BarChart days={byDay} />
                  <div className="flex items-center gap-4 mt-3">
                    <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-sm bg-green-500/60" /><span className="text-[10px] text-zinc-600">Mais greens</span></div>
                    <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-sm bg-red-500/50" /><span className="text-[10px] text-zinc-600">Mais reds</span></div>
                  </div>
                </div>
              )}

              {/* Resultados por liga */}
              {byLeague.length > 0 && (
                <div className="bg-zinc-950 border border-zinc-800 rounded-2xl overflow-hidden mb-8">
                  <div className="px-5 py-3 border-b border-zinc-800">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Resultados por liga</span>
                  </div>
                  <div className="divide-y divide-zinc-800/50">
                    {byLeague.map((lg) => {
                      const wr = calcWinRate(lg.greens, lg.total)
                      const p  = Number(lg.profit)
                      return (
                        <div key={`${lg.league_id ?? lg.league_name}`} className="flex items-center gap-3 px-5 py-3">
                          {lg.league_id != null
                            ? <LeagueLogo id={lg.league_id} name={lg.league_name} />
                            : <div className="w-4.5 h-4.5 rounded-full bg-zinc-800 shrink-0" />}
                          <span className="text-sm font-semibold text-white flex-1 min-w-0 truncate">{lg.league_name}</span>
                          <span className="text-[11px] text-zinc-600 shrink-0 hidden sm:block">{lg.total} picks</span>
                          <span className={`text-xs font-black w-12 text-right shrink-0 ${(wr ?? 0) >= 55 ? 'text-green-400' : 'text-zinc-400'}`}>
                            {wr}%
                          </span>
                          <span className={`text-xs font-black w-16 text-right shrink-0 ${p >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {p >= 0 ? '+' : ''}{p.toFixed(1)}u
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Lista recente */}
              {recent.length > 0 && (() => {
                const recentLeagues = Array.from(new Set(recent.map(t => t.league_name).filter(Boolean))) as string[]
                const filteredRecent = recentLeagueFilter ? recent.filter(t => t.league_name === recentLeagueFilter) : recent
                return (
                <div className="bg-zinc-950 border border-zinc-800 rounded-2xl overflow-hidden">
                  <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Picks recentes</span>
                    <span className="text-[10px] text-zinc-600">{filteredRecent.length} resultados</span>
                  </div>
                  {recentLeagues.length > 1 && (
                    <div className="flex gap-2 flex-wrap px-4 pt-3">
                      <button
                        onClick={() => setRecentLeagueFilter('')}
                        className={`text-[11px] px-2.5 py-1 rounded-lg border font-semibold transition-colors ${!recentLeagueFilter ? 'bg-green-500/15 border-green-500/40 text-green-400' : 'border-zinc-800 text-zinc-500 hover:border-zinc-700'}`}
                      >
                        Todas
                      </button>
                      {recentLeagues.map(lg => (
                        <button
                          key={lg}
                          onClick={() => setRecentLeagueFilter(lg === recentLeagueFilter ? '' : lg)}
                          className={`text-[11px] px-2.5 py-1 rounded-lg border font-semibold transition-colors ${recentLeagueFilter === lg ? 'bg-green-500/15 border-green-500/40 text-green-400' : 'border-zinc-800 text-zinc-500 hover:border-zinc-700'}`}
                        >
                          {lg}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="divide-y divide-zinc-800/50">
                    {filteredRecent.map((tip, i) => (
                      <div key={i} className="flex items-center gap-2 px-4 py-3">
                        <span className="text-[10px] text-zinc-600 shrink-0 w-12">
                          {new Date(tip.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                        </span>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[tip.source] ?? ''}`}>
                          {SRC_LBL[tip.source] ?? tip.source}
                        </span>
                        <div className="flex items-center gap-1 flex-1 min-w-0">
                          <TeamLogo id={tip.home_team_id} name={tip.home_team_name} size={16} />
                          <span className="text-xs text-zinc-300 truncate">{tip.home_team_name}{tip.away_team_name ? ` x ${tip.away_team_name}` : ''}</span>
                        </div>
                        <span className="text-[11px] text-zinc-500 shrink-0 hidden sm:block truncate max-w-[100px]">
                          {tip.market?.split(' ').slice(0, 3).join(' ')} {tip.line ?? ''}
                        </span>
                        <span className="text-xs font-bold text-zinc-400 shrink-0">{Number(tip.odd).toFixed(2)}</span>
                        {(() => {
                          const rs = getResultStyle(tip.result)
                          return (
                            <span className={`text-xs font-black px-2 py-0.5 rounded border shrink-0 ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-zinc-500'}`}>
                              {rs ? rs.label : tip.result}
                            </span>
                          )
                        })()}
                      </div>
                    ))}
                  </div>
                </div>
                )
              })()}
            </>
          )}

          {/* CTA */}
          <div className="mt-12 text-center">
            <p className="text-zinc-500 text-sm mb-4">Quer receber esses picks antes de acontecerem?</p>
            <Link to="/login" className="inline-block bg-green-500 hover:bg-green-400 text-black font-black px-8 py-3.5 rounded-xl text-sm transition-colors">
              Criar conta · 2 dias VIP grátis
            </Link>
          </div>
        </main>
      </div>
    </>
  )
}
