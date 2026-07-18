import { useEffect, useState, useCallback } from 'react'
import api from '../services/api'
import Navbar from '../components/Navbar'
import { translateMarket } from '../utils/marketTranslate'
import DailyGreensChart from '../components/DailyGreensChart'
import SuggestionDetail from '../components/SuggestionDetail'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { winRate as calcWinRate } from '../utils/format'
import { TeamLogo } from '../components/TeamLogo'
import BackButton from '../components/BackButton'
import FilterPanel, { FilterGroup } from '../components/FilterPanel'

const RESULTADO_OPTIONS = [
  { value: 'all', label: 'Todos' }, { value: 'GREEN', label: 'Green' }, { value: 'RED', label: 'Red' },
  { value: 'PUSH', label: 'Push' }, { value: 'HALF-WIN', label: '½ Win' }, { value: 'HALF-LOSS', label: '½ Loss' },
  { value: 'pending', label: 'Pendente' },
]

type Period  = '7d' | '30d' | '90d' | 'all' | 'custom'
type View    = 'resumo' | 'por_jogo' | 'por_mes'
type Source  = 'all' | 'vip' | 'free' | 'multipla' | 'alavancagem'

const SOURCES: { key: Source; label: string; cls: string }[] = [
  { key: 'all',         label: 'Todos',      cls: 'border-zinc-700 text-zinc-400 hover:border-zinc-500' },
  { key: 'vip',         label: 'VIP',        cls: 'border-yellow-500/40 text-yellow-400 hover:border-yellow-500' },
  { key: 'free',        label: 'Free',       cls: 'border-green-500/40 text-green-400 hover:border-green-500' },
  { key: 'multipla',    label: 'Múltipla',   cls: 'border-blue-500/40 text-blue-400 hover:border-blue-500' },
  { key: 'alavancagem', label: 'Alavancagem',cls: 'border-orange-500/40 text-orange-400 hover:border-orange-500' },
]

const PERIODS: { key: Period; label: string; days?: number }[] = [
  { key: '7d',     label: '7 dias',  days: 7 },
  { key: '30d',    label: '30 dias', days: 30 },
  { key: '90d',    label: '90 dias', days: 90 },
  { key: 'all',    label: 'Tudo' },
  { key: 'custom', label: 'Personalizado' },
]

function buildParams(p: Period, from?: string, to?: string): Record<string, string | number> {
  if (p === 'custom' && from && to) return { date_from: from, date_to: to }
  if (p === 'all') return { days: 3650 }
  const found = PERIODS.find(x => x.key === p)
  return found?.days ? { days: found.days } : {}
}

export default function Results() {
  const [view,       setView]       = useState<View>('resumo')
  const [period,     setPeriod]     = useState<Period>('30d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo,   setCustomTo]   = useState('')
  const [source,     setSource]     = useState<Source>('all')

  // Resumo
  const [stats,    setStats]    = useState<any>(null)
  const [loading,  setLoading]  = useState(true)

  // Por jogo
  const [games,       setGames]       = useState<any[]>([])
  const [gamesTotal,  setGamesTotal]  = useState(0)
  const [gamesPage,   setGamesPage]   = useState(0)
  const [gamesFilter, setGamesFilter] = useState('all')
  const [gamesLoading,setGamesLoading]= useState(false)
  const [detailPick,  setDetailPick]  = useState<{ id: number; pick_type: string } | null>(null)
  const PAGE_SIZE = 10

  // Por mês
  const [monthly,    setMonthly]    = useState<any[]>([])
  const [monthLoad,  setMonthLoad]  = useState(false)

  // Paginação tabela por dia
  const [dayPage,    setDayPage]    = useState(0)
  const DAY_PAGE_SIZE = 7

  // fetchers
  const fetchSummary = useCallback((p: Period, src: Source, from?: string, to?: string) => {
    setLoading(true)
    api.get('/suggestions/results', { params: { ...buildParams(p, from, to), source: src } })
      .then(r => setStats(r.data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false))
  }, [])

  const fetchGames = useCallback((p: Period, page: number, resultado: string, src: Source, from?: string, to?: string) => {
    setGamesLoading(true)
    const params: any = { ...buildParams(p, from, to), limit: PAGE_SIZE, offset: page * PAGE_SIZE, source: src }
    if (resultado !== 'all') params.resultado = resultado
    api.get('/suggestions/results/games', { params })
      .then(r => { setGames(r.data.items); setGamesTotal(r.data.total) })
      .catch(() => { setGames([]); setGamesTotal(0) })
      .finally(() => setGamesLoading(false))
  }, [])

  const fetchMonthly = useCallback((src: Source) => {
    setMonthLoad(true)
    api.get('/suggestions/results/monthly', { params: { source: src } })
      .then(r => setMonthly(r.data))
      .catch(() => setMonthly([]))
      .finally(() => setMonthLoad(false))
  }, [])

  useEffect(() => { fetchSummary('30d', 'all') }, [])

  useEffect(() => {
    if (view === 'por_jogo') fetchGames(period, 0, gamesFilter, source, customFrom, customTo)
    if (view === 'por_mes')  fetchMonthly(source)
  }, [view])

  function applySource(s: Source) {
    setSource(s); setGamesPage(0); setDayPage(0)
    if (view === 'resumo')   fetchSummary(period, s, customFrom || undefined, customTo || undefined)
    if (view === 'por_jogo') fetchGames(period, 0, gamesFilter, s, customFrom, customTo)
    if (view === 'por_mes')  fetchMonthly(s)
  }

  function applyPeriod(p: Period) {
    setPeriod(p); setGamesPage(0); setDayPage(0)
    if (p !== 'custom') {
      if (view === 'resumo')   fetchSummary(p, source)
      if (view === 'por_jogo') fetchGames(p, 0, gamesFilter, source)
    }
  }

  function applyCustom() {
    if (!customFrom || !customTo) return
    if (view === 'resumo')   fetchSummary('custom', source, customFrom, customTo)
    if (view === 'por_jogo') fetchGames('custom', 0, gamesFilter, source, customFrom, customTo)
  }

  // métricas
  const total   = stats?.total ?? 0
  const greens  = stats?.greens ?? 0
  const profit  = Number(stats?.profit_total ?? 0)
  const stake   = Number(stats?.stake_total ?? 0)
  const winRate = calcWinRate(greens, total) ?? 0

  // render
  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      {/* Modal de detalhe do pick */}
      {detailPick && (
        <SuggestionDetail
          id={detailPick.id}
          pickType={detailPick.pick_type}
          onClose={() => setDetailPick(null)}
        />
      )}

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-3">
          <BackButton />
          <div>
            <h1 className="text-base font-black text-white">Resultados da IA</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Performance histórica da IA · não inclui resultados pessoais da sua banca</p>
          </div>
        </div>
      </div>

      <main className="max-w-5xl mx-auto px-4 py-6">

        {/* View tabs */}
        <div className="flex border-b border-zinc-800 mb-5 overflow-x-auto">
          {([['resumo','Resumo'],['por_jogo','Por Jogo'],['por_mes','Por Mês']] as [View,string][]).map(([k,l]) => (
            <button key={k} onClick={() => setView(k)}
              className={`px-5 py-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
                view === k ? 'border-green-500 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}>{l}</button>
          ))}
        </div>

        {/* Filtros */}
        <FilterPanel
          accent="green"
          groups={[
            {
              key: 'source', label: 'Fonte',
              options: SOURCES.map(s => ({ value: s.key, label: s.label })),
              value: source, onChange: v => applySource(v as Source),
            },
            ...(view !== 'por_mes' ? [{
              key: 'period', label: 'Período',
              options: PERIODS.map(p => ({ value: p.key, label: p.label })),
              value: period, defaultValue: '30d', onChange: v => applyPeriod(v as Period),
            } as FilterGroup] : []),
            ...(view === 'por_jogo' ? [{
              key: 'resultado', label: 'Resultado',
              options: RESULTADO_OPTIONS,
              value: gamesFilter, onChange: (v: string) => { setGamesFilter(v); setGamesPage(0); fetchGames(period, 0, v, source, customFrom, customTo) },
            } as FilterGroup] : []),
          ]}
          extra={
            <div className="flex items-end gap-3">
              <div>
                <label className="text-xs text-zinc-500 block mb-1">De</label>
                <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} className="input text-sm py-2" />
              </div>
              <div>
                <label className="text-xs text-zinc-500 block mb-1">Até</label>
                <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)} className="input text-sm py-2" />
              </div>
              <button onClick={applyCustom} disabled={!customFrom || !customTo} className="btn-primary text-sm px-5 py-2">Buscar</button>
            </div>
          }
          extraWhen={view !== 'por_mes' && period === 'custom'}
        />

        {view === 'resumo' && (
          loading ? (
            <div className="card p-16 flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
            </div>
          ) : (
            <>
              {/* 4 métricas puras de performance da IA */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                {[
                  { label: 'Total picks', val: total,         color: 'text-white'     },
                  { label: 'Win rate',    val: `${winRate}%`, color: 'text-green-500' },
                  { label: 'Greens',      val: greens,        color: 'text-green-400' },
                  { label: 'Reds',        val: stats?.reds ?? 0, color: 'text-red-400' },
                ].map(({ label, val, color }) => (
                  <div key={label} className="stat-card text-center">
                    <div className={`text-4xl font-black ${color}`}>{val}</div>
                    <div className="text-xs text-zinc-500 uppercase tracking-wider">{label}</div>
                  </div>
                ))}
              </div>

              {/* Greens por dia */}
              {stats?.by_day?.length >= 2 && (
                <div className="card p-5 mb-5">
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider">Greens por dia</p>
                    <span className="text-xs text-zinc-600">{stats.by_day.length} dias</span>
                  </div>
                  <p className="text-[10px] text-zinc-700 mb-4">Barra verde = greens · Barra cinza = total de picks</p>
                  <DailyGreensChart data={stats.by_day} />
                </div>
              )}

              {/* Breakdown de resultados */}
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-3 mb-5">
                {[
                  { label: 'Green',  value: stats?.greens ?? 0,      color: 'text-green-400',  bg: 'bg-green-500/10'  },
                  { label: 'Red',    value: stats?.reds ?? 0,        color: 'text-red-400',    bg: 'bg-red-500/10'    },
                  { label: 'Push',   value: stats?.push ?? 0,        color: 'text-zinc-400',   bg: 'bg-zinc-800/60'   },
                  { label: '½ Win',  value: stats?.half_wins ?? 0,   color: 'text-teal-400',   bg: 'bg-teal-500/10'   },
                  { label: '½ Loss', value: stats?.half_losses ?? 0, color: 'text-orange-400', bg: 'bg-orange-500/10' },
                ].map(({ label, value, color, bg }) => (
                  <div key={label} className={`card p-4 text-center ${bg}`}>
                    <div className={`text-2xl font-black ${color}`}>{value}</div>
                    <div className="text-xs text-zinc-600 mt-1">{label}</div>
                  </div>
                ))}
              </div>

              {/* Por dia · com paginação */}
              {stats?.by_day?.length > 0 && (() => {
                const sorted = [...stats.by_day].sort((a: any, b: any) => b.match_date.localeCompare(a.match_date))
                const totalDayPages = Math.ceil(sorted.length / DAY_PAGE_SIZE)
                const daySlice = sorted.slice(dayPage * DAY_PAGE_SIZE, (dayPage + 1) * DAY_PAGE_SIZE)
                const goDay = (p: number) => setDayPage(p)
                return (
                  <div className="card overflow-hidden">
                    <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <span className="w-0.5 h-5 bg-green-500 rounded-full block" />
                        <h3 className="font-black text-white text-sm uppercase tracking-wider">Por dia</h3>
                      </div>
                      <span className="text-xs text-zinc-600">{sorted.length} dias</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm min-w-[460px]">
                        <thead>
                          <tr className="border-b border-zinc-800">
                            {['Data','Picks','Greens','Reds','Win %'].map(h => (
                              <th key={h} className="text-left text-zinc-500 font-medium px-3 sm:px-5 py-3 text-xs uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {daySlice.map((d: any) => {
                            const wr   = calcWinRate(d.greens, d.total) ?? 0
                            const reds = d.reds ?? (d.total - d.greens - (d.push ?? 0) - (d.half_wins ?? 0) - (d.half_losses ?? 0))
                            return (
                              <tr key={d.match_date} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                                <td className="px-3 sm:px-5 py-3 text-white font-medium">{new Date(d.match_date + 'T12:00:00').toLocaleDateString('pt-BR')}</td>
                                <td className="px-3 sm:px-5 py-3 text-zinc-300">{d.total}</td>
                                <td className="px-3 sm:px-5 py-3 text-green-500 font-semibold">{d.greens}</td>
                                <td className="px-3 sm:px-5 py-3 text-red-400 font-semibold">{reds}</td>
                                <td className="px-3 sm:px-5 py-3">
                                  <div className="flex items-center gap-2">
                                    <div className="bg-zinc-800 rounded-full h-1.5 w-16">
                                      <div className="bg-green-500 h-1.5 rounded-full" style={{ width: `${wr}%` }} />
                                    </div>
                                    <span className={`text-xs font-bold ${wr >= 55 ? 'text-green-400' : 'text-zinc-400'}`}>{wr}%</span>
                                  </div>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                    {totalDayPages > 1 && (
                      <div className="px-5 py-3 border-t border-zinc-800 flex items-center justify-center gap-1 flex-wrap">
                        <button disabled={dayPage === 0} onClick={() => goDay(dayPage - 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-30 transition-colors">Ant</button>
                        {Array.from({ length: totalDayPages }, (_, i) => (
                          <button key={i} onClick={() => goDay(i)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                              dayPage === i ? 'bg-green-500 border-green-500 text-black' : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                            }`}>{i + 1}</button>
                        ))}
                        <button disabled={dayPage >= totalDayPages - 1} onClick={() => goDay(dayPage + 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-30 transition-colors">Próx</button>
                      </div>
                    )}
                  </div>
                )
              })()}
            </>
          )
        )}

        {view === 'por_jogo' && (
          <div>
            <p className="text-zinc-600 text-xs mb-4">{gamesTotal} picks</p>

            {gamesLoading ? (
              <div className="card p-12 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
              </div>
            ) : games.length === 0 ? (
              <div className="card p-10 text-center border-dashed">
                <p className="text-zinc-600 text-sm">Nenhum pick encontrado.</p>
              </div>
            ) : (
              <>
                <div className="card overflow-hidden">
                  <div className="divide-y divide-zinc-800/60">
                    {games.map(g => {
                      const rs = getResultStyle(g.result)
                      const badge = rs ? `${rs.bg} ${rs.text} ${rs.border}` : 'bg-zinc-700/50 text-zinc-400 border-zinc-700'
                      return (
                        <div key={g.id}
                          className="flex items-center gap-2 px-3 sm:px-5 py-3 sm:py-3.5 hover:bg-zinc-900/50 transition-colors cursor-pointer"
                          onClick={() => setDetailPick({ id: g.id, pick_type: g.pick_type })}>
                          {/* Data */}
                          <div className="w-14 shrink-0 text-center">
                            <span className="text-xs text-zinc-500">
                              {new Date(g.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                            </span>
                          </div>

                          {/* Partida */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                              {g.pick_type && source === 'all' && (
                                <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[g.pick_type] ?? ''}`}>
                                  {g.pick_type === 'alavancagem' ? 'Alav.' : g.pick_type === 'multipla' ? 'Múlt.' : g.pick_type.toUpperCase()}
                                </span>
                              )}
                              <TeamLogo id={g.home_team_id} name={g.home_team_name} size={16} />
                              <span className="text-sm font-semibold text-white truncate">{g.home_team_name}</span>
                              {g.away_team_name && g.pick_type !== 'multipla' && (
                                <>
                                  <span className="text-zinc-600 text-xs shrink-0">vs</span>
                                  <span className="text-sm font-semibold text-white truncate">{g.away_team_name}</span>
                                  <TeamLogo id={g.away_team_id} name={g.away_team_name} size={16} />
                                </>
                              )}
                            </div>
                            <p className="text-xs text-zinc-500 truncate">
                              {translateMarket(g.market)}{g.line ? <> · <span className="text-zinc-400">{g.line}</span></> : ''}
                              {g.odd ? ` · Odd ${Number(g.odd).toFixed(2)}` : ''}
                            </p>
                          </div>

                          {/* Resultado */}
                          <div className="flex items-center shrink-0">
                            {g.result ? (
                              <span className={`text-xs font-black px-2.5 py-1 rounded-lg border ${badge}`}>
                                {rs ? rs.label : g.result}
                              </span>
                            ) : (
                              <span className="text-zinc-600 text-xs">Pendente</span>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Paginação numerada */}
                {gamesTotal > PAGE_SIZE && (() => {
                  const totalPages = Math.ceil(gamesTotal / PAGE_SIZE)
                  const goTo = (p: number) => { setGamesPage(p); fetchGames(period, p, gamesFilter, source, customFrom, customTo) }
                  const pages: (number | '...')[] = []
                  if (totalPages <= 7) {
                    for (let i = 0; i < totalPages; i++) pages.push(i)
                  } else {
                    pages.push(0)
                    if (gamesPage > 2) pages.push('...')
                    for (let i = Math.max(1, gamesPage - 1); i <= Math.min(totalPages - 2, gamesPage + 1); i++) pages.push(i)
                    if (gamesPage < totalPages - 3) pages.push('...')
                    pages.push(totalPages - 1)
                  }
                  return (
                    <div className="flex items-center justify-center gap-1 mt-4 flex-wrap">
                      <button disabled={gamesPage === 0} onClick={() => goTo(gamesPage - 1)}
                        className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-30 transition-colors">Ant</button>
                      {pages.map((pg, i) =>
                        pg === '...'
                          ? <span key={`e${i}`} className="px-2 text-zinc-600 text-xs">…</span>
                          : <button key={pg} onClick={() => goTo(pg as number)}
                              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                                gamesPage === pg
                                  ? 'bg-green-500 border-green-500 text-black'
                                  : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                              }`}>{(pg as number) + 1}</button>
                      )}
                      <button disabled={(gamesPage + 1) * PAGE_SIZE >= gamesTotal} onClick={() => goTo(gamesPage + 1)}
                        className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-30 transition-colors">Próx</button>
                    </div>
                  )
                })()}
              </>
            )}
          </div>
        )}

        {view === 'por_mes' && (
          monthLoad ? (
            <div className="card p-16 flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
            </div>
          ) : monthly.length === 0 ? (
            <div className="card p-10 text-center border-dashed">
              <p className="text-zinc-600 text-sm">Nenhum resultado mensal encontrado.</p>
            </div>
          ) : (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[460px]">
                  <thead>
                    <tr className="border-b border-zinc-800">
                      {['Mês','Picks','Greens','Reds','Win %'].map(h => (
                        <th key={h} className="text-left text-zinc-500 font-medium px-3 sm:px-5 py-3 text-xs uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {monthly.map(m => {
                      const wr   = m.win_rate ?? calcWinRate(m.greens, m.total) ?? 0
                      const reds = m.reds ?? (m.total - m.greens - (m.push ?? 0) - (m.half_wins ?? 0) - (m.half_losses ?? 0))
                      const [year, month] = (m.month ?? '').split('-')
                      const label = new Date(Number(year), Number(month) - 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
                      return (
                        <tr key={m.month} className="border-b border-zinc-800/50 hover:bg-zinc-900/50 transition-colors">
                          <td className="px-3 sm:px-5 py-3 text-white font-semibold capitalize">{label}</td>
                          <td className="px-3 sm:px-5 py-3 text-zinc-300">{m.total}</td>
                          <td className="px-3 sm:px-5 py-3 text-green-500 font-semibold">{m.greens}</td>
                          <td className="px-3 sm:px-5 py-3 text-red-400 font-semibold">{reds}</td>
                          <td className="px-3 sm:px-5 py-3">
                            <div className="flex items-center gap-2">
                              <div className="bg-zinc-800 rounded-full h-1.5 w-16">
                                <div className="bg-green-500 h-1.5 rounded-full" style={{ width: `${wr}%` }} />
                              </div>
                              <span className={`text-xs font-bold ${wr >= 55 ? 'text-green-400' : 'text-zinc-400'}`}>{wr}%</span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                    {/* Totais */}
                    {(() => {
                      const totT  = monthly.reduce((a, m) => a + (m.total ?? 0), 0)
                      const totG  = monthly.reduce((a, m) => a + (m.greens ?? 0), 0)
                      const totR  = monthly.reduce((a, m) => a + (m.reds ?? (m.total - m.greens - (m.push ?? 0) - (m.half_wins ?? 0) - (m.half_losses ?? 0))), 0)
                      const avgWR = calcWinRate(totG, totT) ?? 0
                      return (
                        <tr className="bg-zinc-900 border-t border-zinc-700">
                          <td className="px-3 sm:px-5 py-3 text-zinc-400 font-bold text-xs uppercase">Total</td>
                          <td className="px-3 sm:px-5 py-3 text-white font-black">{totT}</td>
                          <td className="px-3 sm:px-5 py-3 text-green-500 font-black">{totG}</td>
                          <td className="px-3 sm:px-5 py-3 text-red-400 font-black">{totR}</td>
                          <td className="px-3 sm:px-5 py-3 text-zinc-300 font-bold text-xs">{avgWR}%</td>
                        </tr>
                      )
                    })()}
                  </tbody>
                </table>
              </div>
            </div>
          )
        )}
      </main>
    </div>
  )
}
