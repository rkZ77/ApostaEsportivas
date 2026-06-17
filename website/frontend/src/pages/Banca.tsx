import { useEffect, useState, useCallback } from 'react'
import { TrendingUp } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import ProfitChart from '../components/ProfitChart'
import SuggestionDetail from '../components/SuggestionDetail'

// formatação
const fmtBRL = (v: number) =>
  'R$ ' + Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtSigned = (v: number) =>
  (v >= 0 ? '+' : '−') + fmtBRL(v)

// constantes visuais
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

// lock overlay para free
// modal de setup
function SetupModal({ current, onSave, onClose }: {
  current: { start: number; goal: number | null; unitValue: number }
  onSave: (start: number, goal: number | null, unitValue: number) => void
  onClose: () => void
}) {
  const [start,     setStart]     = useState(String(current.start))
  const [goal,      setGoal]      = useState(current.goal ? String(current.goal) : '')
  const [unitValue, setUnitValue] = useState(String(current.unitValue))
  const [err,       setErr]       = useState('')
  const [loading,   setLoading]   = useState(false)

  const startNum    = parseFloat(start.replace(',', '.')) || 0
  const suggested   = startNum > 0 ? (startNum / 100).toFixed(2) : ''

  const handleSave = async () => {
    setErr('')
    const s  = parseFloat(start.replace(',', '.'))
    const g  = goal ? parseFloat(goal.replace(',', '.')) : null
    const uv = parseFloat(unitValue.replace(',', '.'))
    if (!s || s <= 0)          { setErr('Banca inicial deve ser maior que zero.'); return }
    if (g !== null && g <= s)  { setErr('Meta deve ser maior que a banca inicial.'); return }
    if (!uv || uv <= 0)        { setErr('Valor da unidade deve ser maior que zero.'); return }
    setLoading(true)
    try {
      await api.post('/banca/setup', { bankroll_start: s, bankroll_goal: g, unit_value: uv })
      onSave(s, g, uv)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Erro ao salvar.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 w-full max-w-sm">
        <h2 className="text-white font-black text-lg mb-1">Configurar banca</h2>
        <p className="text-zinc-500 text-xs mb-5">Define banca, unidade e meta como um tipster profissional.</p>

        <div className="space-y-4">
          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">Banca inicial (R$)</label>
            <input type="number" min="1" step="0.01" value={start}
              onChange={e => setStart(e.target.value)} className="input w-full" placeholder="Ex: 500" />
          </div>

          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">
              Valor de 1 unidade (R$)
              <span className="text-zinc-600 ml-1">quanto você aposta por unidade</span>
            </label>
            <input type="number" min="0.01" step="0.01" value={unitValue}
              onChange={e => setUnitValue(e.target.value)} className="input w-full" placeholder="Ex: 5" />
            {startNum > 0 && (
              <p className="text-zinc-600 text-xs mt-1">
                Sugerido: <button type="button" onClick={() => setUnitValue(suggested)}
                  className="text-green-500 underline hover:text-green-400">
                  {fmtBRL(parseFloat(suggested) || 0)}
                </button>
                {' '}(1% da banca, gestão conservadora)
              </p>
            )}
          </div>

          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">
              Meta de banca (R$) <span className="text-zinc-600">(opcional)</span>
            </label>
            <input type="number" min="1" step="0.01" value={goal}
              onChange={e => setGoal(e.target.value)} className="input w-full" placeholder="Ex: 1000" />
          </div>
        </div>

        <div className="mt-4 bg-zinc-800/50 rounded-lg px-3 py-2 text-xs text-zinc-400">
          <p className="font-semibold text-zinc-300 mb-0.5">Como funciona:</p>
          <p>Pick recomenda 2u → você aposta 2 × R$ {unitValue || '?'} = <strong className="text-white">{fmtBRL((parseFloat(unitValue) || 0) * 2)}</strong></p>
          <p className="text-zinc-500 mt-0.5">Yield = lucro em unidades / unidades apostadas × 100%</p>
        </div>

        {err && <p className="text-red-400 text-xs mt-3">{err}</p>}

        <div className="flex gap-3 mt-5">
          <button onClick={handleSave} disabled={loading} className="btn-primary flex-1 py-2.5">
            {loading ? 'Salvando...' : 'Salvar'}
          </button>
          <button onClick={onClose} className="btn-ghost flex-1 py-2.5 text-sm">Cancelar</button>
        </div>
      </div>
    </div>
  )
}

// componente principal
const PERIODS = [
  { key: 0,  label: 'Tudo' },
  { key: 7,  label: '7 dias' },
  { key: 30, label: '30 dias' },
  { key: 90, label: '90 dias' },
]

export default function Banca() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const [data,    setData]    = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [period,  setPeriod]  = useState(0)
  const [showSetup, setShowSetup] = useState(false)
  const [detailPick, setDetailPick] = useState<{ id: number; pick_type: string } | null>(null)

  const load = useCallback((days: number) => {
    setLoading(true)
    api.get('/banca', { params: days > 0 ? { days } : {} })
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load(period)
  }, [period, load])

  const handleSave = (start: number, goal: number | null, unitValue: number) => {
    setShowSetup(false)
    setData((d: any) => d ? { ...d, bankroll_start: start, bankroll_goal: goal, unit_value: unitValue } : d)
    load(period)
  }

  const pnlColor = (v: number | null) =>
    v == null ? 'text-zinc-600' : v > 0 ? 'text-green-500' : v < 0 ? 'text-red-400' : 'text-zinc-400'

  const chartData = (data?.chart ?? []).map((p: any, i: number, arr: any[]) => ({
    match_date: p.date,
    profit: i === 0
      ? p.bankroll - (data?.bankroll_start ?? 100)
      : p.bankroll - arr[i - 1].bankroll,
  }))

  // meta progress
  const goal    = data?.bankroll_goal ?? null
  const current = data?.bankroll_current ?? data?.bankroll_start ?? 0
  const start   = data?.bankroll_start ?? 100
  const goalPct = goal ? Math.min(100, Math.round(((current - start) / (goal - start)) * 100)) : 0

  // distribuição
  const distTotal = (data?.greens ?? 0) + (data?.reds ?? 0) + (data?.push ?? 0) + (data?.half_wins ?? 0) + (data?.half_loss ?? 0)
  const distItems = [
    { label: 'GREEN',   value: data?.greens    ?? 0, color: 'bg-green-500',  text: 'text-green-400'  },
    { label: 'RED',     value: data?.reds      ?? 0, color: 'bg-red-500',    text: 'text-red-400'    },
    { label: '½ WIN',   value: data?.half_wins ?? 0, color: 'bg-teal-500',   text: 'text-teal-400'   },
    { label: '½ LOSS',  value: data?.half_loss ?? 0, color: 'bg-orange-500', text: 'text-orange-400' },
    { label: 'PUSH',    value: data?.push      ?? 0, color: 'bg-zinc-500',   text: 'text-zinc-400'   },
  ]

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      {showSetup && (
        <SetupModal
          current={{ start: data?.bankroll_start ?? 100, goal: data?.bankroll_goal ?? null, unitValue: data?.unit_value ?? 1 }}
          onSave={handleSave}
          onClose={() => setShowSetup(false)}
        />
      )}

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
              <h1 className="text-base font-black text-white">Minha Banca</h1>
              <div className="flex items-center gap-2 mt-0.5">
                <p className="text-zinc-500 text-xs">Acompanhe o crescimento dos picks que você apostou</p>
                {data?.unit_value && (
                  <span className="text-[10px] bg-zinc-800 border border-zinc-700 text-zinc-400 px-2 py-0.5 rounded font-mono">
                    1u = {fmtBRL(Number(data.unit_value))}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link to="/meus-picks" className="btn-ghost text-xs px-3 py-2">
              Meus Picks
            </Link>
            <button onClick={() => setShowSetup(true)} className="btn-ghost text-xs px-3 py-2">
              Configurar
            </button>
          </div>
        </div>
      </div>

      <main className="max-w-5xl mx-auto px-4 py-6">
        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-6">

            {/* Filtro de período */}
            <div className="flex items-center gap-2 flex-wrap">
              {PERIODS.map(p => (
                <button key={p.key} onClick={() => setPeriod(p.key)}
                  className={`px-4 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                    period === p.key
                      ? 'bg-green-500 border-green-500 text-black'
                      : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                  }`}>{p.label}</button>
              ))}
            </div>

            {/* Stats principais */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  label: 'Banca atual',
                  value: fmtBRL(current),
                  color: (data?.total_pnl ?? 0) >= 0 ? 'text-green-500' : 'text-red-400',
                  sub: `${fmtSigned(data?.total_pnl ?? 0)} total`,
                },
                {
                  label: 'Yield (tipster)',
                  value: `${(data?.yield_roi ?? 0) >= 0 ? '+' : ''}${data?.yield_roi ?? 0}%`,
                  color: (data?.yield_roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400',
                  sub: data?.ia_roi != null
                    ? `ROI banca: ${(data?.roi ?? 0) >= 0 ? '+' : ''}${data?.roi ?? 0}%`
                    : `ROI banca: ${(data?.roi ?? 0) >= 0 ? '+' : ''}${data?.roi ?? 0}%`,
                },
                {
                  label: 'Win rate',
                  value: `${data?.win_rate ?? 0}%`,
                  color: (data?.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-400',
                  sub: `${data?.greens ?? 0}G / ${data?.reds ?? 0}R de ${data?.total_resolved ?? 0}`,
                },
                {
                  label: 'Streak atual',
                  value: data?.streak > 0
                    ? `${data.streak_type === 'green' ? '+' : '-'}${data.streak}`
                    : '',
                  color: data?.streak_type === 'green' ? 'text-green-500'
                       : data?.streak_type === 'red'   ? 'text-red-400'
                       : 'text-zinc-500',
                  sub: data?.best_streak > 0
                    ? `Melhor: ${data.best_streak} greens seguidos`
                    : 'Sem sequência ainda',
                },
              ].map(({ label, value, color, sub }) => (
                <div key={label} className="stat-card text-center">
                  <div className={`text-3xl font-black ${color}`}>{value}</div>
                  <div className="text-xs text-zinc-500 uppercase tracking-wider mt-1">{label}</div>
                  <div className="text-[10px] text-zinc-700 mt-0.5">{sub}</div>
                </div>
              ))}
            </div>

            {/* Meta de banca */}
            {goal ? (
              <div className="card p-5">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold mb-0.5">Meta de banca</p>
                    <p className="text-white font-black">
                      {fmtBRL(current)}
                      <span className="text-zinc-600 font-normal text-sm"> / {fmtBRL(goal)}</span>
                    </p>
                  </div>
                  <span className={`text-2xl font-black ${goalPct >= 100 ? 'text-green-400' : 'text-zinc-300'}`}>
                    {goalPct >= 100 ? 'Meta atingida!' : `${goalPct}%`}
                  </span>
                </div>
                <div className="bg-zinc-800 rounded-full h-3 overflow-hidden">
                  <div
                    className={`h-3 rounded-full transition-all duration-500 ${goalPct >= 100 ? 'bg-green-400' : 'bg-green-500'}`}
                    style={{ width: `${Math.max(2, goalPct)}%` }}
                  />
                </div>
                <p className="text-xs text-zinc-600 mt-2">
                  Faltam {fmtBRL(Math.max(0, goal - current))} para atingir a meta
                </p>
              </div>
            ) : (
              <button
                onClick={() => setShowSetup(true)}
                className="w-full card p-4 border-dashed text-center text-xs text-zinc-500 hover:text-zinc-300 hover:border-zinc-600 transition-colors"
              >
                + Definir meta de banca
              </button>
            )}

            {/* Gráfico de evolução */}
            {chartData.length >= 2 && (
              <div className="card p-5">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold">Evolução da banca</p>
                  <span className={`text-sm font-black ${(data?.total_pnl ?? 0) >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                    {fmtSigned(data?.total_pnl ?? 0)}
                  </span>
                </div>
                <ProfitChart data={chartData} unit="R$" />
              </div>
            )}

            {/* Streak + Distribuição */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

              {/* Streak pessoal */}
              <div className="card p-5">
                <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold mb-4">Sequencia pessoal</p>
                <div className="flex items-center justify-around">
                  <div className="text-center">
                    <div className={`text-4xl font-black ${data?.streak_type === 'green' ? 'text-green-500' : data?.streak_type === 'red' ? 'text-red-400' : 'text-zinc-600'}`}>
                      {data?.streak > 0 ? data.streak : ''}
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">
                      {data?.streak_type === 'green' ? 'Greens seguidos' : data?.streak_type === 'red' ? 'Reds seguidos' : 'Sequencia atual'}
                    </div>
                  </div>
                  <div className="w-px h-12 bg-zinc-800" />
                  <div className="text-center">
                    <div className="text-4xl font-black text-yellow-400">
                      {data?.best_streak > 0 ? data.best_streak : ''}
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">Melhor sequencia</div>
                  </div>
                </div>
              </div>

              {/* Distribuição de resultados */}
              <div className="card p-5">
                <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold mb-4">Distribuicao de resultados</p>
                {distTotal === 0 ? (
                  <p className="text-zinc-600 text-xs text-center py-4">Sem picks resolvidos ainda.</p>
                ) : (
                  <div className="space-y-2">
                    {distItems.map(({ label, value, color, text }) => (
                      <div key={label} className="flex items-center gap-2">
                        <span className={`text-[10px] font-black w-12 text-right shrink-0 ${text}`}>{label}</span>
                        <div className="flex-1 bg-zinc-800 rounded-full h-2 overflow-hidden">
                          <div
                            className={`h-2 rounded-full ${color}`}
                            style={{ width: `${distTotal > 0 ? Math.round(value / distTotal * 100) : 0}%` }}
                          />
                        </div>
                        <span className="text-xs text-zinc-500 w-8 text-right shrink-0">{value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Melhor e pior pick */}
            {(data?.best_pick || data?.worst_pick) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {data?.best_pick && (
                  <div className="card p-4 border-green-500/20 bg-green-500/5">
                    <p className="text-xs text-green-500 font-black uppercase tracking-wider mb-2">Melhor pick apostado</p>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          {data.best_pick.home_team_id && (
                            <img src={`/api/proxy/team/${data.best_pick.home_team_id}.png`}
                              alt="" className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                          <p className="text-sm text-white font-semibold">{data.best_pick.home_team_name ?? `Pick #${data.best_pick.pick_id}`}</p>
                        </div>
                        <p className="text-xs text-zinc-500">{data.best_pick.market ?? ''}</p>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border mt-1 inline-block ${SOURCE_CLS[data.best_pick.pick_type] ?? ''}`}>
                          {SOURCE_LBL[data.best_pick.pick_type] ?? data.best_pick.pick_type}
                        </span>
                      </div>
                      <span className="text-2xl font-black text-green-500">
                        +{fmtBRL(data.best_pick.pnl)}
                      </span>
                    </div>
                  </div>
                )}
                {data?.worst_pick && data.worst_pick.pnl < 0 && (
                  <div className="card p-4 border-red-500/20 bg-red-500/5">
                    <p className="text-xs text-red-400 font-black uppercase tracking-wider mb-2">Pior pick apostado</p>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          {data.worst_pick.home_team_id && (
                            <img src={`/api/proxy/team/${data.worst_pick.home_team_id}.png`}
                              alt="" className="w-4 h-4 object-contain shrink-0"
                              onError={e => (e.currentTarget.style.display = 'none')} />
                          )}
                          <p className="text-sm text-white font-semibold">{data.worst_pick.home_team_name ?? `Pick #${data.worst_pick.pick_id}`}</p>
                        </div>
                        <p className="text-xs text-zinc-500">{data.worst_pick.market ?? ''}</p>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border mt-1 inline-block ${SOURCE_CLS[data.worst_pick.pick_type] ?? ''}`}>
                          {SOURCE_LBL[data.worst_pick.pick_type] ?? data.worst_pick.pick_type}
                        </span>
                      </div>
                      <span className="text-2xl font-black text-red-400">
                        −{fmtBRL(Math.abs(data.worst_pick.pnl))}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Comparação com IA */}
            {data?.ia_roi != null && (
              <div className="card p-5">
                <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold mb-4">Você vs IA</p>
                <div className="grid grid-cols-3 gap-4">
                  <div className="text-center">
                    <div className={`text-2xl font-black ${(data?.yield_roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
                      {(data?.yield_roi ?? 0) >= 0 ? '+' : ''}{data.yield_roi ?? 0}%
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 font-semibold">Seu Yield</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">lucro / unidades</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-2xl font-black ${(data?.roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
                      {(data?.roi ?? 0) >= 0 ? '+' : ''}{data.roi ?? 0}%
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 font-semibold">ROI banca</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">{data.total_resolved} picks</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-2xl font-black ${data.ia_roi >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                      {data.ia_roi >= 0 ? '+' : ''}{data.ia_roi}%
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 font-semibold">Yield da IA</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">todos os picks VIP</div>
                  </div>
                </div>
                {data.yield_roi != null && data.ia_roi != null && (
                  <div className={`mt-4 text-center text-xs font-semibold ${data.yield_roi >= data.ia_roi ? 'text-green-400' : 'text-zinc-500'}`}>
                    {data.yield_roi >= data.ia_roi
                      ? <span className="flex items-center justify-center gap-1"><TrendingUp className="w-3.5 h-3.5" /> Você está superando a IA neste período!</span>
                      : `Diferença de ${(data.ia_roi - data.yield_roi).toFixed(1)}% em relação à IA`}
                  </div>
                )}
              </div>
            )}

            {/* Lista de picks agrupada por data */}
            {(() => {
              const allEntries: any[] = (data?.entries ?? []).slice(0, 6)
              const todayKey     = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
              const yesterdayKey = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
              const dayLabel = (key: string) =>
                key === todayKey     ? 'Hoje'
                : key === yesterdayKey ? 'Ontem'
                : new Date(key + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })

              const grouped = allEntries.reduce((acc: Record<string, any[]>, e: any) => {
                const key = e.followed_at
                  ? new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
                  : 'sem-data'
                if (!acc[key]) acc[key] = []
                acc[key].push(e)
                return acc
              }, {})
              const sortedKeys = Object.keys(grouped).sort((a, b) => b.localeCompare(a))

              const PickRow = ({ e }: { e: any }) => {
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
                            : e.pick_type === 'multipla' ? 'Múltipla'
                            : e.pick_type === 'alavancagem' ? 'Alavancagem'
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
                    </div>
                  </button>
                )
              }

              return (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold">
                      Últimos picks apostados
                    </p>
                    <Link to="/meus-picks" className="text-xs text-green-500 hover:text-green-400 transition-colors font-semibold">
                      Ver todos →
                    </Link>
                  </div>

                  {!allEntries.length ? (
                    <div className="card p-12 text-center border-dashed">
                      <p className="text-zinc-500 text-sm font-semibold mb-2">Nenhum pick apostado ainda</p>
                      <p className="text-zinc-600 text-xs mb-4">
                        Clique em "Apostei" nos picks da página Picks para registrar suas apostas aqui.
                      </p>
                      <button onClick={() => navigate('/picks')} className="btn-primary text-sm px-6 py-2.5">
                        Ver picks
                      </button>
                    </div>
                  ) : (
                    <div className="card overflow-hidden">
                      {sortedKeys.map(dateKey => (
                        <div key={dateKey}>
                          <div className="flex items-center gap-2 px-4 py-2 bg-zinc-900/60 border-b border-zinc-800/60">
                            <span className="text-[10px] font-black text-zinc-500 uppercase tracking-wider capitalize">
                              {dayLabel(dateKey)}
                            </span>
                            <span className="text-[10px] text-zinc-700">{grouped[dateKey].length} pick{grouped[dateKey].length !== 1 ? 's' : ''}</span>
                          </div>
                          <div className="divide-y divide-zinc-800/60">
                            {grouped[dateKey].map((e: any) => <PickRow key={e.id} e={e} />)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })()}

          </div>
        )}

      </main>
    </div>
  )
}
