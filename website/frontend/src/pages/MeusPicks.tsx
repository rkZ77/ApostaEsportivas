import { useEffect, useState, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import Navbar from '../components/Navbar'
import { translateMarket } from '../utils/marketTranslate'
import SuggestionDetail from '../components/SuggestionDetail'
import ProfitChart from '../components/ProfitChart'
import { fmtBRL, fmtSigned, winRate as calcWinRate } from '../utils/format'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { TeamLogo } from '../components/TeamLogo'
import BackButton from '../components/BackButton'

const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.', bingo: 'Bingo',
}

const pnlColor = (v: number | null) =>
  v == null ? 'text-zinc-600' : v > 0 ? 'text-green-500' : v < 0 ? 'text-red-400' : 'text-zinc-400'

export default function MeusPicks() {
  const navigate = useNavigate()

  const [data,       setData]       = useState<any>(null)
  const [loading,    setLoading]    = useState(true)
  const [tab,        setTab]        = useState<'pendentes' | 'resolvidos'>('pendentes')
  const [dayOffset,  setDayOffset]  = useState(0)
  const [detailPick,   setDetailPick]   = useState<{ id: number; pick_type: string } | null>(null)
  const [showRemoved,  setShowRemoved]  = useState(false)
  const [autoSwitched, setAutoSwitched] = useState(false)
  const load = useCallback(() => {
    setLoading(true)
    api.get('/banca')
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // Auto-muda para Resolvidos na 1ª carga se não houver pendentes
  useEffect(() => {
    if (data && !autoSwitched) {
      setAutoSwitched(true)
      const pend = (data.entries ?? []).filter((e: any) => !e.result)
      if (pend.length === 0) setTab('resolvidos')
    }
  }, [data])

  const handleUnfollow = async (pick_id: number, pick_type: string) => {
    try {
      await api.delete(`/banca/follow/${pick_id}/${pick_type}`)
      load()
      setShowRemoved(true)
      setTimeout(() => setShowRemoved(false), 3000)
    } catch { /* silently ignore */ }
  }

  const [daysBack, setDaysBack] = useState<number | 'thismonth' | 'lastmonth'>(0)
  const [todayPage, setTodayPage] = useState(0)
  const PAGE_SIZE = 15

  const changeTab = (t: 'pendentes' | 'resolvidos') => {
    setTab(t)
    setDayOffset(0)
    setDaysBack(0)
    setTodayPage(0)
  }

  function isoDateDaysAgo(n: number) {
    const d = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }))
    d.setDate(d.getDate() - n)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  function monthBounds(offset: number) {
    const now = new Date()
    const y = now.getFullYear(), m = now.getMonth() + offset
    const from = new Date(y, m, 1)
    const to   = new Date(y, m + 1, 0)
    const fmt  = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    return { from: fmt(from), to: fmt(to) }
  }

  const allEntries: any[] = data?.entries ?? []
  const pendentes  = allEntries.filter(e => !e.result)
  // Resolvidos: mais recente primeiro
  const resolvidos = allEntries
    .filter(e => e.result)
    .sort((a, b) => new Date(b.followed_at ?? 0).getTime() - new Date(a.followed_at ?? 0).getTime())
  const tabEntries = tab === 'pendentes' ? pendentes : resolvidos

  const todayKey     = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
  const yesterdayKey = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

  const dayLabel = (key: string) =>
    key === todayKey     ? 'Hoje'
    : key === yesterdayKey ? 'Ontem'
    : new Date(key + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })

  // Entradas filtradas pelo período selecionado (para stats + lista)
  const filteredByPeriod = daysBack === 0
    ? allEntries
    : allEntries.filter((e: any) => {
        if (!e.followed_at) return false
        const dayKey = new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
        if (daysBack === 'thismonth')  { const r = monthBounds(0);  return dayKey >= r.from && dayKey <= r.to }
        if (daysBack === 'lastmonth') { const r = monthBounds(-1); return dayKey >= r.from && dayKey <= r.to }
        if (typeof daysBack === 'number') {
          return daysBack < 0 ? dayKey === todayKey : dayKey >= isoDateDaysAgo(daysBack)
        }
        return true
      })

  const filteredTabEntries = daysBack === 0 ? tabEntries : filteredByPeriod.filter((e: any) =>
    tab === 'pendentes' ? !e.result : !!e.result
  )

  // Navegação por dia dentro do filtro
  const uniqueDatesFiltered = Array.from(new Set(
    filteredTabEntries.map((e: any) =>
      e.followed_at
        ? new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
        : null
    ).filter(Boolean)
  )).sort((a, b) => (b as string).localeCompare(a as string)) as string[]

  const clampedOffset = Math.min(dayOffset, Math.max(0, uniqueDatesFiltered.length - 1))
  const selectedKey   = uniqueDatesFiltered[clampedOffset] ?? todayKey
  const pageItems     = daysBack === 0
    ? filteredTabEntries  // Hoje: mostra tudo sem separar por dia
    : filteredTabEntries.filter((e: any) =>
        e.followed_at &&
        new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' }) === selectedKey
      )
  const hasPrev = clampedOffset < uniqueDatesFiltered.length - 1
  const hasNext = clampedOffset > 0

  const displayItems = daysBack === 0
    ? pageItems.slice(todayPage * PAGE_SIZE, (todayPage + 1) * PAGE_SIZE)
    : pageItems

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      {detailPick && (
        <SuggestionDetail
          id={detailPick.id}
          pickType={detailPick.pick_type}
          onClose={() => setDetailPick(null)}
        />
      )}

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BackButton />
            <div>
              <h1 className="text-base font-black text-white">Meus Picks</h1>
              <p className="text-zinc-500 text-xs mt-0.5">Suas apostas pendentes e resolvidas</p>
            </div>
          </div>
        </div>
      </div>

      <main className="max-w-5xl mx-auto px-4 py-6">
        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-4">

            {/* Filtros de período · pills */}
            {allEntries.length > 0 && (
              <div className="flex gap-2 flex-wrap">
                {([
                  { label: 'Todos',        value: 0 },
                  { label: 'Hoje',         value: -1 },
                  { label: 'Semana',       value: 7 },
                  { label: 'Este mês',     value: 'thismonth' },
                  { label: 'Mês passado',  value: 'lastmonth' },
                ] as { label: string; value: number | 'thismonth' | 'lastmonth' }[]).map(({ label, value }) => (
                  <button
                    key={String(value)}
                    onClick={() => { setDaysBack(value); setDayOffset(0); setTodayPage(0) }}
                    className={`px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${
                      daysBack === value
                        ? 'bg-green-500/15 border-green-500/50 text-green-400'
                        : 'border-zinc-700 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}

            {/* Resumo · filtra pelo período selecionado */}
            {allEntries.length > 0 && (() => {
              const periodEntries = filteredByPeriod
              const resolved = periodEntries.filter((e: any) => e.result)
              const greenCount = resolved.filter((e: any) => e.result === 'GREEN' || e.result === 'HALF-WIN').length
              const redCount   = resolved.filter((e: any) => e.result === 'RED'   || e.result === 'HALF-LOSS').length
              const pnl = daysBack === 0
                ? (data?.total_pnl ?? 0)
                : resolved.reduce((acc: number, e: any) => acc + (Number(e.pnl) || 0), 0)
              const wr = calcWinRate(greenCount, resolved.length) ?? 0
              const pnlStr = pnl === 0 ? 'R$ 0' : fmtSigned(pnl)
              return (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                  <div className="card p-3 text-center">
                    <div className="text-2xl font-black text-white">{periodEntries.length}</div>
                    <div className="text-[10px] text-zinc-500 uppercase mt-1">Apostas</div>
                  </div>
                  <div className="card p-3 text-center">
                    <div className={`text-lg sm:text-xl font-black ${pnl > 0 ? 'text-green-500' : pnl < 0 ? 'text-red-400' : 'text-zinc-400'}`}>{pnlStr}</div>
                    <div className="text-[10px] text-zinc-500 uppercase mt-1">
                      {daysBack === 0 ? 'Total' : daysBack === 'thismonth' ? 'Este mês' : daysBack === 'lastmonth' ? 'Mês passado' : `Últimos ${daysBack}d`}
                    </div>
                  </div>
                  <div className="card p-3 text-center">
                    <div className={`text-2xl font-black ${wr >= 55 ? 'text-green-500' : 'text-zinc-400'}`}>{wr}%</div>
                    <div className="text-[10px] text-zinc-500 uppercase mt-1">Win rate</div>
                  </div>
                  <div className="card p-3 text-center border-green-500/20">
                    <div className="text-2xl font-black text-green-400">{greenCount}</div>
                    <div className="text-[10px] text-zinc-500 uppercase mt-1">GREEN</div>
                  </div>
                  <div className="card p-3 text-center border-red-500/20">
                    <div className="text-2xl font-black text-red-400">{redCount}</div>
                    <div className="text-[10px] text-zinc-500 uppercase mt-1">RED</div>
                  </div>
                </div>
              )
            })()}

            {/* Evolução da banca */}
            {(data?.chart?.length ?? 0) >= 2 && (() => {
              const allChart = (data.chart ?? []).map((p: any, i: number, arr: any[]) => ({
                match_date: p.date,
                profit: i === 0
                  ? p.bankroll - (data?.bankroll_start ?? 100)
                  : p.bankroll - arr[i - 1].bankroll,
              }))
              const chartFiltered = daysBack === 0
                ? allChart
                : (typeof daysBack === 'number' && daysBack < 0)
                ? allChart.filter((c: any) => c.match_date === todayKey)
                : typeof daysBack === 'number'
                ? allChart.filter((c: any) => c.match_date >= isoDateDaysAgo(daysBack))
                : (() => { const r = monthBounds(daysBack === 'thismonth' ? 0 : -1); return allChart.filter((c: any) => c.match_date >= r.from && c.match_date <= r.to) })()
              if (chartFiltered.length < 2) return null
              const pnl = data?.total_pnl ?? 0
              return (
                <div className="card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold text-zinc-500 uppercase">Evolução da Banca</h3>
                    <span className={`text-sm font-black ${pnl >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                      {fmtSigned(pnl)}
                    </span>
                  </div>
                  <ProfitChart data={chartFiltered} unit="R$" />
                </div>
              )
            })()}

            {/* Tabs */}
            <div className="flex gap-2">
              <button
                onClick={() => changeTab('pendentes')}
                className={`px-4 py-2 rounded-xl text-sm font-bold border transition-colors ${
                  tab === 'pendentes'
                    ? 'bg-yellow-400/10 border-yellow-400/30 text-yellow-400'
                    : 'border-zinc-700 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300'
                }`}
              >
                Pendentes ({pendentes.length})
              </button>
              <button
                onClick={() => changeTab('resolvidos')}
                className={`px-4 py-2 rounded-xl text-sm font-bold border transition-colors ${
                  tab === 'resolvidos'
                    ? 'bg-green-500/10 border-green-500/30 text-green-400'
                    : 'border-zinc-700 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300'
                }`}
              >
                Resolvidos ({resolvidos.length})
              </button>
            </div>

            {/* Lista */}
            {filteredTabEntries.length === 0 ? (
              <div className="card p-12 text-center border-dashed">
                <p className="text-zinc-500 text-sm font-semibold mb-2">
                  {tab === 'pendentes' ? 'Nenhuma aposta pendente' : 'Nenhuma aposta resolvida ainda'}
                </p>
                <p className="text-zinc-600 text-xs mb-4">
                  Clique em "Apostar" nos picks para registrar suas apostas.
                </p>
                <button onClick={() => navigate('/picks')} className="btn-primary text-sm px-6 py-2.5">
                  Ver picks
                </button>
              </div>
            ) : (
              <>
                {/* Navegação de dia · só aparece quando um filtro de período está ativo */}
                {(typeof daysBack === 'number' ? daysBack > 0 : true) && uniqueDatesFiltered.length > 1 && (
                  <div className="flex items-center justify-between bg-zinc-900 border border-zinc-800 rounded-xl px-2 py-2">
                    <button
                      onClick={() => setDayOffset(o => o + 1)}
                      disabled={!hasPrev}
                      className="flex items-center justify-center w-10 h-10 rounded-lg text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-20 transition-colors"
                    >
                      <ChevronLeft className="w-5 h-5" />
                    </button>
                    <div className="text-center">
                      <div className="flex items-center justify-center gap-1.5">
                        <span className="text-sm font-black text-white capitalize">{dayLabel(selectedKey)}</span>
                        {clampedOffset > 0 && (
                          <button
                            onClick={() => setDayOffset(0)}
                            className="text-[10px] text-green-400 hover:text-green-300 font-bold transition-colors border border-green-500/30 px-1.5 py-0.5 rounded"
                          >
                            Mais recente
                          </button>
                        )}
                      </div>
                      <div className="text-[10px] text-zinc-600 mt-0.5">{pageItems.length} pick{pageItems.length !== 1 ? 's' : ''}</div>
                    </div>
                    <button
                      onClick={() => setDayOffset(o => o - 1)}
                      disabled={!hasNext}
                      className="flex items-center justify-center w-10 h-10 rounded-lg text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-20 transition-colors"
                    >
                      <ChevronRight className="w-5 h-5" />
                    </button>
                  </div>
                )}

                {/* Picks do dia */}
                {pageItems.length === 0 ? (
                  <div className="card p-8 text-center border-dashed">
                    <p className="text-zinc-600 text-sm">Nenhum pick neste dia.</p>
                  </div>
                ) : (
                  <div className="card overflow-hidden">
                    <div className="divide-y divide-zinc-800/60">
                      {displayItems.map((e: any) => {
                        return (
                          <button
                            key={e.id}
                            onClick={() => setDetailPick({ id: e.pick_id, pick_type: e.pick_type })}
                            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/40 transition-colors text-left"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                                <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[e.pick_type] ?? ''}`}>
                                  {SOURCE_LBL[e.pick_type] ?? e.pick_type}
                                </span>
                                <TeamLogo id={e.home_team_id} name={e.home_team_name ?? ''} size={16} />
                                <span className="text-sm font-semibold text-white truncate">
                                  {e.home_team_name
                                    ? e.home_team_name
                                    : e.pick_type === 'multipla'
                                    ? 'Múltipla'
                                    : e.pick_type === 'alavancagem'
                                    ? 'Alavancagem'
                                    : e.pick_type === 'bingo'
                                    ? `Bingo #${e.pick_id}`
                                    : e.market ?? `Pick #${e.pick_id}`}
                                </span>
                                {e.away_team_name && (
                                  <>
                                    <span className="text-zinc-600 text-xs shrink-0">vs</span>
                                    <TeamLogo id={e.away_team_id} name={e.away_team_name} size={16} />
                                    <span className="text-sm font-semibold text-white truncate">{e.away_team_name}</span>
                                  </>
                                )}
                              </div>
                              <p className="text-xs text-zinc-600 truncate">
                                {translateMarket(e.market) ?? ''}
                                {e.line ? ` · ${e.line}` : ''}
                                {e.actual_odd
                                  ? <> · <span className="text-zinc-400">Odd {Number(e.actual_odd).toFixed(2)}</span>{Math.abs(Number(e.actual_odd) - Number(e.odd)) > 0.001 ? <span className="text-zinc-600"> (pick: {Number(e.odd).toFixed(2)})</span> : null}</>
                                  : e.odd ? ` · Odd ${Number(e.odd).toFixed(2)}` : ''}
                              </p>
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {e.result ? (() => {
                                const rs = getResultStyle(e.result)
                                return (
                                  <span className={`text-xs font-black px-2 py-0.5 rounded-lg border ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-zinc-500'}`}>
                                    {rs ? rs.label : e.result}
                                  </span>
                                )
                              })() : (
                                <span className="text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-2 py-0.5 rounded-lg font-bold">
                                  Pendente
                                </span>
                              )}
                              <span className={`text-sm font-black w-20 text-right ${pnlColor(e.pnl)}`}>
                                {e.pnl != null ? fmtSigned(e.pnl) : ''}
                              </span>
                              {tab === 'pendentes' && (
                                <button
                                  onClick={ev => { ev.stopPropagation(); handleUnfollow(e.pick_id, e.pick_type) }}
                                  className="flex items-center justify-center w-8 h-8 rounded-lg text-zinc-600 hover:text-red-400 hover:bg-red-400/10 transition-colors shrink-0"
                                  title="Remover pick"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Paginação · só no modo Todos (daysBack=0) */}
                {daysBack === 0 && filteredTabEntries.length > PAGE_SIZE && (
                  <div className="flex items-center justify-center gap-2 flex-wrap">
                    <button
                      disabled={todayPage === 0}
                      onClick={() => setTodayPage(p => p - 1)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-30 transition-colors"
                    >Ant</button>
                    <span className="text-xs text-zinc-500">
                      {todayPage * PAGE_SIZE + 1}–{Math.min((todayPage + 1) * PAGE_SIZE, filteredTabEntries.length)} de {filteredTabEntries.length}
                    </span>
                    <button
                      disabled={(todayPage + 1) * PAGE_SIZE >= filteredTabEntries.length}
                      onClick={() => setTodayPage(p => p + 1)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-30 transition-colors"
                    >Próx</button>
                  </div>
                )}
              </>
            )}

          </div>
        )}
      </main>

      {showRemoved && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-red-600 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg whitespace-nowrap">
          Pick removido da sua banca
        </div>
      )}
    </div>
  )
}
