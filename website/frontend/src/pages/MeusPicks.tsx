import { useEffect, useState, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import Navbar from '../components/Navbar'
import SuggestionDetail from '../components/SuggestionDetail'

const fmtBRL = (v: number) =>
  'R$ ' + Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtSigned = (v: number) =>
  (v >= 0 ? '+' : '−') + fmtBRL(v)

const RESULT_CLS: Record<string, string> = {
  GREEN:       'bg-green-500/10 text-green-400 border border-green-500/30',
  RED:         'bg-red-500/10 text-red-400 border border-red-500/30',
  PUSH:        'bg-zinc-700/50 text-zinc-400 border border-zinc-700',
  'HALF-WIN':  'bg-teal-500/10 text-teal-400 border border-teal-500/30',
  'HALF-LOSS': 'bg-orange-500/10 text-orange-400 border border-orange-500/30',
}
const RESULT_LBL: Record<string, string> = {
  GREEN: 'GREEN', RED: 'RED', PUSH: 'PUSH', 'HALF-WIN': '½ WIN', 'HALF-LOSS': '½ LOSS',
}
const SOURCE_CLS: Record<string, string> = {
  vip:         'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  free:        'text-green-400 bg-green-500/10 border-green-500/20',
  multipla:    'text-blue-400 bg-blue-400/10 border-blue-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
}
const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.',
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
    await api.delete(`/banca/follow/${pick_id}/${pick_type}`).catch(() => {})
    load()
    setShowRemoved(true)
    setTimeout(() => setShowRemoved(false), 3000)
  }

  const changeTab = (t: 'pendentes' | 'resolvidos') => {
    setTab(t)
    setDayOffset(0)
  }

  const allEntries: any[] = data?.entries ?? []
  const pendentes  = allEntries.filter(e => !e.result)
  const resolvidos = allEntries.filter(e =>  e.result)
  const tabEntries = tab === 'pendentes' ? pendentes : resolvidos

  const todayKey     = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
  const yesterdayKey = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

  const dayLabel = (key: string) =>
    key === todayKey     ? 'Hoje'
    : key === yesterdayKey ? 'Ontem'
    : new Date(key + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })

  const uniqueDates = Array.from(new Set(
    tabEntries.map((e: any) =>
      e.followed_at
        ? new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
        : null
    ).filter(Boolean)
  )).sort((a, b) => (b as string).localeCompare(a as string)) as string[]

  const clampedOffset = Math.min(dayOffset, Math.max(0, uniqueDates.length - 1))
  const selectedKey   = uniqueDates[clampedOffset] ?? todayKey
  const pageItems     = tabEntries.filter((e: any) =>
    e.followed_at &&
    new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' }) === selectedKey
  )
  const hasPrev = clampedOffset < uniqueDates.length - 1
  const hasNext = clampedOffset > 0

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
            <button onClick={() => navigate(-1)} className="text-zinc-500 hover:text-white transition-colors text-lg leading-none">←</button>
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

            {/* Resumo */}
            {allEntries.length > 0 && (() => {
              const resolved = allEntries.filter(e => e.result)
              const greenCount = resolved.filter(e => e.result === 'GREEN' || e.result === 'HALF-WIN').length
              const redCount   = resolved.filter(e => e.result === 'RED'   || e.result === 'HALF-LOSS').length
              const pnl = data?.total_pnl ?? 0
              const pnlStr = pnl === 0 ? '0' : `${pnl > 0 ? '+' : ''}${Number(pnl).toFixed(2)}`
              return (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                  <div className="card p-3 text-center">
                    <div className="text-2xl font-black text-white">{allEntries.length}</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">Apostas</div>
                  </div>
                  <div className="card p-3 text-center">
                    <div className={`text-2xl font-black ${pnl > 0 ? 'text-green-500' : pnl < 0 ? 'text-red-400' : 'text-zinc-400'}`}>{pnlStr}</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">P&L total</div>
                  </div>
                  <div className="card p-3 text-center">
                    <div className={`text-2xl font-black ${(data?.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-400'}`}>{data?.win_rate ?? 0}%</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">Win rate</div>
                  </div>
                  <div className="card p-3 text-center border-green-500/20">
                    <div className="text-2xl font-black text-green-400">{greenCount}</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">GREEN</div>
                  </div>
                  <div className="card p-3 text-center border-red-500/20">
                    <div className="text-2xl font-black text-red-400">{redCount}</div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-1">RED</div>
                  </div>
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
            {tabEntries.length === 0 ? (
              <div className="card p-12 text-center border-dashed">
                <p className="text-zinc-500 text-sm font-semibold mb-2">
                  {tab === 'pendentes' ? 'Nenhuma aposta pendente' : 'Nenhuma aposta resolvida ainda'}
                </p>
                <p className="text-zinc-600 text-xs mb-4">
                  Clique em "+ Apostei" nos picks para registrar suas apostas.
                </p>
                <button onClick={() => navigate('/picks')} className="btn-primary text-sm px-6 py-2.5">
                  Ver picks
                </button>
              </div>
            ) : (
              <>
                {/* Navegação de dia */}
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
                      {selectedKey !== todayKey && (
                        <button
                          onClick={() => setDayOffset(0)}
                          className="text-[10px] text-green-400 hover:text-green-300 font-bold transition-colors border border-green-500/30 px-1.5 py-0.5 rounded"
                        >
                          Hoje
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

                {/* Picks do dia */}
                {pageItems.length === 0 ? (
                  <div className="card p-8 text-center border-dashed">
                    <p className="text-zinc-600 text-sm">Nenhum pick neste dia.</p>
                  </div>
                ) : (
                  <div className="card overflow-hidden">
                    <div className="divide-y divide-zinc-800/60">
                      {pageItems.map((e: any) => {
                        const homeSrc = e.home_team_id ? `/api/proxy/team/${e.home_team_id}.png` : null
                        const awaySrc = e.away_team_id ? `/api/proxy/team/${e.away_team_id}.png` : null
                        return (
                          <button
                            key={e.id}
                            onClick={() => setDetailPick({ id: e.pick_id, pick_type: e.pick_type })}
                            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/40 transition-colors text-left"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                                <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${SOURCE_CLS[e.pick_type] ?? ''}`}>
                                  {SOURCE_LBL[e.pick_type] ?? e.pick_type}
                                </span>
                                {homeSrc && (
                                  <img src={homeSrc} alt="" className="w-4 h-4 object-contain shrink-0"
                                    onError={ev => (ev.currentTarget.style.display = 'none')} />
                                )}
                                <span className="text-sm font-semibold text-white truncate">
                                  {e.home_team_name
                                    ? e.home_team_name
                                    : e.pick_type === 'multipla'
                                    ? 'Múltipla'
                                    : e.pick_type === 'alavancagem'
                                    ? 'Alavancagem'
                                    : e.market ?? `Pick #${e.pick_id}`}
                                </span>
                                {e.away_team_name && (
                                  <>
                                    <span className="text-zinc-600 text-xs shrink-0">vs</span>
                                    {awaySrc && (
                                      <img src={awaySrc} alt="" className="w-4 h-4 object-contain shrink-0"
                                        onError={ev => (ev.currentTarget.style.display = 'none')} />
                                    )}
                                    <span className="text-sm font-semibold text-white truncate">{e.away_team_name}</span>
                                  </>
                                )}
                              </div>
                              <p className="text-xs text-zinc-600 truncate">
                                {e.market ?? ''}
                                {e.line ? ` · ${e.line}` : ''}
                                {e.actual_odd
                                  ? <> · <span className="text-zinc-400">Odd {Number(e.actual_odd).toFixed(2)}</span>{Math.abs(Number(e.actual_odd) - Number(e.odd)) > 0.001 ? <span className="text-zinc-600"> (pick: {Number(e.odd).toFixed(2)})</span> : null}</>
                                  : e.odd ? ` · Odd ${Number(e.odd).toFixed(2)}` : ''}
                              </p>
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {e.result ? (
                                <span className={`text-xs font-black px-2 py-0.5 rounded-lg ${RESULT_CLS[e.result] ?? 'text-zinc-500'}`}>
                                  {RESULT_LBL[e.result] ?? e.result}
                                </span>
                              ) : (
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
