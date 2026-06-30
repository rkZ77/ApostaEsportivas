import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'
import { Helmet } from 'react-helmet-async'

interface Summary {
  total: number; greens: number; reds: number; push: number
  profit: number; stake_total: number; roi: number
}
interface DayResult { match_date: string; total: number; greens: number; reds: number; profit: number }
interface RecentTip {
  match_date: string
  home_team_name: string; away_team_name?: string
  home_team_id?: number; away_team_id?: number
  market?: string; line?: string; odd: number
  result: string; profit: number; source: string
}
interface PublicData {
  available_months: string[]
  summary: Summary
  by_day: DayResult[]
  recent: RecentTip[]
}

const RESULT_CLS: Record<string, string> = {
  GREEN:       'bg-green-500/15 text-green-400 border-green-500/30',
  RED:         'bg-red-500/15 text-red-400 border-red-500/30',
  PUSH:        'bg-zinc-700/40 text-zinc-400 border-zinc-700',
  'HALF-WIN':  'bg-teal-500/15 text-teal-400 border-teal-500/30',
  'HALF-LOSS': 'bg-orange-500/15 text-orange-400 border-orange-500/30',
}
const RESULT_LBL: Record<string, string> = {
  GREEN: 'GREEN', RED: 'RED', PUSH: 'PUSH', 'HALF-WIN': '½ WIN', 'HALF-LOSS': '½ LOSS',
}
const SRC_CLS: Record<string, string> = {
  vip:         'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  free:        'text-green-400 bg-green-500/10 border-green-500/20',
  multiplas:   'text-blue-400 bg-blue-400/10 border-blue-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
}
const SRC_LBL: Record<string, string> = { vip: 'VIP', free: 'Free', multiplas: 'Múlt.', alavancagem: 'Alav.' }
const SOURCES = ['all', 'vip', 'free', 'multiplas', 'alavancagem']
const SOURCE_LABELS: Record<string, string> = { all: 'Todos', vip: 'VIP', free: 'Free', multiplas: 'Múltiplas', alavancagem: 'Alavancagem' }

function TEAM_LOGO(id?: number) { return id ? `/api/proxy/team/${id}.png` : null }

function TeamMini({ id, name }: { id?: number; name: string }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={16} height={16}
      className="w-4 h-4 object-contain shrink-0"
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

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
  const [source, setSource] = useState('all')
  const [month, setMonth] = useState('')

  useEffect(() => {
    setLoading(true)
    const params: Record<string, string> = {}
    if (source !== 'all') params.source = source
    if (month) params.month = month
    axios.get('/api/public/results', { params })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [source, month])

  const s = data?.summary
  const winRate = s && s.total > 0 ? Math.round((s.greens / s.total) * 100) : null
  const profit  = s ? Number(s.profit) : null
  const months  = data?.available_months ?? []
  const recent  = data?.recent ?? []
  const byDay   = data?.by_day ?? []

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
          <div className="flex flex-wrap gap-2 mb-6 justify-center">
            {SOURCES.map(src => (
              <button
                key={src}
                onClick={() => setSource(src)}
                className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors ${source === src ? 'bg-green-500/15 border-green-500/40 text-green-400' : 'border-zinc-800 text-zinc-500 hover:border-zinc-700'}`}
              >
                {SOURCE_LABELS[src]}
              </button>
            ))}
          </div>
          {months.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-8 justify-center">
              <button
                onClick={() => setMonth('')}
                className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors ${!month ? 'bg-zinc-700/40 border-zinc-600 text-zinc-300' : 'border-zinc-800 text-zinc-600 hover:border-zinc-700'}`}
              >
                Todos os meses
              </button>
              {months.slice(0, 6).map(m => (
                <button
                  key={m}
                  onClick={() => setMonth(m === month ? '' : m)}
                  className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors ${month === m ? 'bg-zinc-700/40 border-zinc-600 text-zinc-300' : 'border-zinc-800 text-zinc-600 hover:border-zinc-700'}`}
                >
                  {m}
                </button>
              ))}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-20">
              <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
            </div>
          ) : !s || s.total === 0 ? (
            <div className="text-center py-16 text-zinc-500">Nenhum resultado encontrado para os filtros selecionados.</div>
          ) : (
            <>
              {/* Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
                {[
                  { label: 'Win Rate',  value: `${winRate}%`,            color: (winRate ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-300' },
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

              {/* Lista recente */}
              {recent.length > 0 && (
                <div className="bg-zinc-950 border border-zinc-800 rounded-2xl overflow-hidden">
                  <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Picks recentes</span>
                    <span className="text-[10px] text-zinc-600">{recent.length} resultados</span>
                  </div>
                  <div className="divide-y divide-zinc-800/50">
                    {recent.map((tip, i) => (
                      <div key={i} className="flex items-center gap-2 px-4 py-3">
                        <span className="text-[10px] text-zinc-600 shrink-0 w-12">
                          {new Date(tip.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                        </span>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${SRC_CLS[tip.source] ?? ''}`}>
                          {SRC_LBL[tip.source] ?? tip.source}
                        </span>
                        <div className="flex items-center gap-1 flex-1 min-w-0">
                          <TeamMini id={tip.home_team_id} name={tip.home_team_name} />
                          <span className="text-xs text-zinc-300 truncate">{tip.home_team_name}{tip.away_team_name ? ` x ${tip.away_team_name}` : ''}</span>
                        </div>
                        <span className="text-[11px] text-zinc-500 shrink-0 hidden sm:block truncate max-w-[100px]">
                          {tip.market?.split(' ').slice(0, 3).join(' ')} {tip.line ?? ''}
                        </span>
                        <span className="text-xs font-bold text-zinc-400 shrink-0">{Number(tip.odd).toFixed(2)}</span>
                        <span className={`text-xs font-black px-2 py-0.5 rounded border shrink-0 ${RESULT_CLS[tip.result] ?? 'text-zinc-500'}`}>
                          {RESULT_LBL[tip.result] ?? tip.result}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
