import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, Info } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { backdropFade, dialogScale } from '../lib/motion'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import ProfitChart from '../components/ProfitChart'
import SuggestionDetail from '../components/SuggestionDetail'
import { fmtBRL, fmtSigned } from '../utils/format'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { TeamLogo } from '../components/TeamLogo'
import BackButton from '../components/BackButton'
import FilterPanel from '../components/FilterPanel'
import NumberTicker from '../components/ui/NumberTicker'
import MonthlyCloseSection from '../components/MonthlyCloseSection'

const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.',
}

// lock overlay para free
// modal de setup
function SetupModal({ current, locked, onSave, onClose, onWithdraw }: {
  current: { start: number; goal: number | null; unitValue: number }
  locked?: boolean
  onSave: (start: number, goal: number | null, unitValue: number) => void
  onClose: () => void
  onWithdraw: () => void
}) {
  const [start,     setStart]     = useState(String(current.start))
  const [goal,      setGoal]      = useState(current.goal ? String(current.goal) : '')
  const [unitValue, setUnitValue] = useState(String(current.unitValue))
  const [err,       setErr]       = useState('')
  const [loading,   setLoading]   = useState(false)

  const startNum  = parseFloat(start.replace(',', '.')) || 0
  const uvNum     = parseFloat(unitValue.replace(',', '.')) || 0
  const suggested = startNum > 0 ? (startNum / 100).toFixed(2) : ''

  // Validação de risco de banca em tempo real
  const totalUnits   = startNum > 0 && uvNum > 0 ? startNum / uvNum : null
  const unitPct      = startNum > 0 && uvNum > 0 ? (uvNum / startNum) * 100 : null
  const isBlocked    = totalUnits !== null && totalUnits < 20
  const isWarning    = totalUnits !== null && totalUnits >= 20 && totalUnits < 50
  const maxUnitSafe  = startNum > 0 ? (startNum / 20).toFixed(2) : null

  const bancaStatus = isBlocked ? 'blocked'
    : isWarning ? 'warning'
    : totalUnits !== null ? 'ok'
    : null

  const handleSave = async () => {
    setErr('')
    const s  = parseFloat(start.replace(',', '.'))
    const g  = goal ? parseFloat(goal.replace(',', '.')) : null
    const uv = parseFloat(unitValue.replace(',', '.'))
    if (!s || s <= 0)          { setErr('Banca inicial deve ser maior que zero.'); return }
    if (g !== null && g <= s)  { setErr('Meta deve ser maior que a banca inicial.'); return }
    if (!uv || uv <= 0)        { setErr('Valor da unidade deve ser maior que zero.'); return }
    if (isBlocked)             { setErr(`Unidade muito alta. Máximo permitido: ${fmtBRL(parseFloat(maxUnitSafe ?? '0'))} para ter 20 unidades mínimas.`); return }
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

  if (locked) {
    return (
      <motion.div
        variants={backdropFade} initial="hidden" animate="visible" exit="exit"
        className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4" onClick={onClose}
      >
        <motion.div variants={dialogScale} className="bg-zinc-900 border border-zinc-700 rounded-lg p-6 max-w-sm w-full overflow-y-auto max-h-[92dvh]"
          onClick={e => e.stopPropagation()}>
          <h2 className="text-white font-black text-lg mb-2">Já configurada este mês</h2>
          <p className="text-zinc-400 text-sm leading-relaxed mb-4">
            Pra manter o histórico de risco confiável, a banca só pode ser configurada uma vez por
            mês. Se você quer tirar um valor agora, use o botão "Sacar" (fica registrado no
            histórico). Pra reconfigurar do zero, espera o fechamento mensal automático.
          </p>
          <div className="flex flex-col gap-2">
            <button onClick={() => { onClose(); onWithdraw() }} className="btn-primary w-full py-2.5 text-sm">
              Sacar da banca
            </button>
            <button onClick={onClose} className="btn-ghost w-full py-2.5 text-sm">Entendi</button>
          </div>
        </motion.div>
      </motion.div>
    )
  }

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4"
    >
      <motion.div variants={dialogScale} className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 w-full max-w-sm overflow-y-auto max-h-[92dvh]">
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
            <input
              type="number" min="0.01" step="0.01" value={unitValue}
              onChange={e => setUnitValue(e.target.value)}
              className={`input w-full ${isBlocked ? 'border-red-500/60 focus:border-red-500' : isWarning ? 'border-yellow-500/60 focus:border-yellow-500' : ''}`}
              placeholder="Ex: 5"
            />
            {startNum > 0 && (
              <p className="text-zinc-600 text-xs mt-1">
                Sugerido: <button type="button" onClick={() => setUnitValue(suggested)}
                  className="text-green-500 underline hover:text-green-400">
                  {fmtBRL(parseFloat(suggested) || 0)}
                </button>
                {' '}(1% da banca, gestão conservadora)
              </p>
            )}

            {/* Indicador de saúde da banca */}
            {bancaStatus === 'blocked' && totalUnits !== null && (
              <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-xs">
                <p className="text-red-400 font-black mb-0.5">Bloqueado · risco de ruína</p>
                <p className="text-red-300">
                  Com R${fmtBRL(uvNum)} por unidade sua banca teria apenas <strong>{Math.floor(totalUnits)} unidades</strong>.
                  Menos de 20 unidades é alto risco de ruína total.
                </p>
                <p className="text-red-400 mt-1 font-semibold">
                  Máximo permitido: <button type="button" onClick={() => setUnitValue(maxUnitSafe ?? '')}
                    className="underline hover:text-red-300">{fmtBRL(parseFloat(maxUnitSafe ?? '0'))}</button> por unidade
                </p>
              </div>
            )}
            {bancaStatus === 'warning' && totalUnits !== null && unitPct !== null && (
              <div className="mt-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2 text-xs">
                <p className="text-yellow-400 font-black mb-0.5">Atenção · unidade acima do ideal</p>
                <p className="text-yellow-300">
                  Sua banca teria <strong>{Math.floor(totalUnits)} unidades</strong> ({unitPct.toFixed(1)}% por unidade).
                  Recomendado: mínimo 50 unidades (≤ 2% por unidade).
                </p>
                <p className="text-yellow-400 mt-1 font-semibold">
                  Ideal: <button type="button" onClick={() => setUnitValue(suggested)}
                    className="underline hover:text-yellow-300">{fmtBRL(parseFloat(suggested) || 0)}</button> por unidade
                </p>
              </div>
            )}
            {bancaStatus === 'ok' && totalUnits !== null && (
              <div className="mt-2 flex items-center gap-1.5 text-xs text-green-500">
                <span className="font-bold">Banca saudável</span>
                <span className="text-zinc-600">·</span>
                <span className="text-zinc-400">{Math.floor(totalUnits)} unidades totais</span>
              </div>
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
          <p>Pick recomenda 2u: você aposta 2 × R$ {unitValue || '?'} = <strong className="text-white">{fmtBRL((parseFloat(unitValue) || 0) * 2)}</strong></p>
          <p className="text-zinc-500 mt-0.5">Yield = lucro em unidades / unidades apostadas × 100%</p>
        </div>

        {err && <p className="text-red-400 text-xs mt-3">{err}</p>}

        <div className="flex gap-3 mt-5">
          <button onClick={handleSave} disabled={loading || isBlocked}
            className="btn-primary flex-1 py-2.5 disabled:opacity-40 disabled:cursor-not-allowed">
            {loading ? 'Salvando...' : 'Salvar'}
          </button>
          <button onClick={onClose} className="btn-ghost flex-1 py-2.5 text-sm">Cancelar</button>
        </div>
      </motion.div>
    </motion.div>
  )
}

function monthRange(offset: number) {
  // offset 0 = este mes, -1 = mes passado
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth() + 1 + offset
  const date = new Date(y, m - 1, 1)
  const from = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-01`
  const last = new Date(date.getFullYear(), date.getMonth() + 1, 0)
  const to   = `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`
  return { from, to }
}

type PeriodKey = number | 'thismonth' | 'lastmonth'

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: 0,           label: 'Tudo' },
  { key: 1,           label: 'Hoje' },
  { key: 7,           label: '7 dias' },
  { key: 30,          label: '30 dias' },
  { key: 'thismonth', label: 'Este mês' },
  { key: 'lastmonth', label: 'Mês passado' },
]

export default function Banca() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const [data,    setData]    = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(false)
  const [period,  setPeriod]  = useState<PeriodKey>(0)
  const [showSetup, setShowSetup]           = useState(false)
  const [detailPick, setDetailPick] = useState<{ id: number; pick_type: string } | null>(null)

  const load = useCallback((p: PeriodKey) => {
    setLoading(true)
    setError(false)
    let params: Record<string, string | number> = {}
    if (p === 'thismonth') {
      const r = monthRange(0); params = { from_date: r.from, to_date: r.to }
    } else if (p === 'lastmonth') {
      const r = monthRange(-1); params = { from_date: r.from, to_date: r.to }
    } else if (typeof p === 'number' && p > 0) {
      params = { days: p }
    }
    api.get('/banca', { params })
      .then(r => setData(r.data))
      .catch(() => setError(true))
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

  // ganho em unidades (exclui alavancagem, igual ao total_pnl)
  const ganhoUnidades = (data?.unit_value ?? 0) > 0 ? (data?.total_pnl ?? 0) / data.unit_value : 0

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

      <AnimatePresence>
      {showSetup && (
        <SetupModal
          current={{ start: data?.bankroll_start ?? 100, goal: data?.bankroll_goal ?? null, unitValue: data?.unit_value ?? 1 }}
          locked={data?.can_configure === false}
          onSave={handleSave}
          onClose={() => setShowSetup(false)}
          onWithdraw={() => navigate('/banca/saque')}
        />
      )}
      </AnimatePresence>

      <AnimatePresence>
      {detailPick && (
        <SuggestionDetail
          id={detailPick.id}
          pickType={detailPick.pick_type}
          onClose={() => setDetailPick(null)}
        />
      )}
      </AnimatePresence>

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BackButton />
            <div>
              <h1 className="text-base font-black text-white">Minha Banca</h1>
              <div className="flex items-center gap-2 mt-0.5">
                <p className="text-zinc-500 text-xs hidden sm:block">Acompanhe o crescimento dos picks que você apostou</p>
                {data?.unit_value && (
                  <span className="text-xs font-semibold text-zinc-400">
                    1 unidade = <span className="text-white font-black">{fmtBRL(Number(data.unit_value))}</span>
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            <Link to="/meus-picks" className="btn-ghost text-xs px-3 py-2 hidden sm:inline-flex">
              Meus Picks
            </Link>
            <button onClick={() => navigate('/banca/saque')} className="btn-ghost text-xs px-3 py-2">
              Sacar
            </button>
            <button
              onClick={() => setShowSetup(true)}
              className={`btn-ghost text-xs px-3 py-2 ${data?.can_configure === false ? 'opacity-50' : ''}`}
              title={data?.can_configure === false ? 'Já configurada este mês' : undefined}
            >
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
        ) : error ? (
          <div className="card p-10 text-center">
            <p className="text-zinc-400 font-semibold mb-1">Erro ao carregar sua banca</p>
            <p className="text-zinc-600 text-sm mb-4">Não foi possível conectar ao servidor. Verifique sua conexão.</p>
            <button onClick={() => load(period)} className="text-sm text-green-400 hover:text-green-300 font-semibold transition-colors">
              Tentar novamente
            </button>
          </div>
        ) : (
          <div className="space-y-6">

            {/* Filtro de período */}
            <FilterPanel
              accent="green"
              groups={[{
                key: 'period', label: 'Período',
                options: PERIODS.map(p => ({ value: String(p.key), label: p.label })),
                value: String(period),
                onChange: v => {
                  const found = PERIODS.find(p => String(p.key) === v)
                  if (found) setPeriod(found.key)
                },
              }]}
            />

            {/* Stats principais */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  label: 'Banca atual',
                  value: data?.total_pnl ?? 0,
                  formatter: (v: number) => fmtSigned(v),
                  color: (data?.total_pnl ?? 0) >= 0 ? 'text-green-500' : 'text-red-400',
                  sub: `${fmtBRL(current)} banca total`,
                },
                {
                  label: 'Yield (tipster)',
                  value: data?.yield_roi ?? 0,
                  formatter: (v: number) => `${v >= 0 ? '+' : ''}${Math.round(v)}%`,
                  color: (data?.yield_roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400',
                  sub: data?.ia_roi != null
                    ? `ROI da IA: ${data.ia_roi >= 0 ? '+' : ''}${data.ia_roi}%`
                    : `ROI banca: ${(data?.roi ?? 0) >= 0 ? '+' : ''}${data?.roi ?? 0}%`,
                },
                {
                  label: 'Win rate',
                  value: data?.win_rate ?? 0,
                  formatter: (v: number) => `${Math.round(v)}%`,
                  color: (data?.win_rate ?? 0) >= 55 ? 'text-green-500' : 'text-zinc-400',
                  sub: `${data?.greens ?? 0}G / ${data?.reds ?? 0}R de ${data?.total_resolved ?? 0}`,
                },
                {
                  label: 'Ganho p/ unidade',
                  value: ganhoUnidades,
                  formatter: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}u`,
                  color: ganhoUnidades >= 0 ? 'text-green-500' : 'text-red-400',
                  sub: 'excl. alavancagem',
                },
              ].map(({ label, value, formatter, color, sub }) => (
                <div key={label} className="stat-card text-center">
                  <NumberTicker value={value} formatter={formatter} className={`font-mono text-3xl font-black ${color}`} />
                  <div className="text-xs text-zinc-500 uppercase mt-1">{label}</div>
                  <div className="text-[10px] text-zinc-700 mt-0.5">{sub}</div>
                </div>
              ))}
            </div>

            {/* Aviso alavancagem */}
            <div className="flex items-center gap-1.5 -mt-2 text-[11px] text-zinc-600">
              <Info className="w-3 h-3 shrink-0" />
              <span>Picks de Alavancagem não são contabilizados nesta banca</span>
            </div>

            {/* Meta de banca */}
            {goal ? (
              <div className="card p-5">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <p className="text-xs text-zinc-500 uppercase font-semibold mb-0.5">Meta de banca</p>
                    <p className="font-mono text-white font-black">
                      {fmtBRL(current)}
                      <span className="text-zinc-600 font-normal text-sm"> / {fmtBRL(goal)}</span>
                    </p>
                  </div>
                  <span className={`font-mono text-2xl font-black ${goalPct >= 100 ? 'text-green-400' : 'text-zinc-300'}`}>
                    {goalPct >= 100 ? 'Meta atingida!' : `${goalPct}%`}
                  </span>
                </div>
                <div className="bg-zinc-800 rounded-full h-3 overflow-hidden">
                  <motion.div
                    className={`h-3 rounded-full ${goalPct >= 100 ? 'bg-green-400' : 'bg-green-500'}`}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.max(2, goalPct)}%` }}
                    transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
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
                  <p className="text-xs text-zinc-500 uppercase font-semibold">Evolução da banca</p>
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
                <p className="text-xs text-zinc-500 uppercase font-semibold mb-4">Sequência pessoal</p>
                <div className="flex items-center justify-around">
                  <div className="text-center">
                    <div className={`text-4xl font-black ${data?.streak_type === 'green' ? 'text-green-500' : data?.streak_type === 'red' ? 'text-red-400' : 'text-zinc-600'}`}>
                      {data?.streak > 0 ? data.streak : ''}
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">
                      {data?.streak_type === 'green' ? 'Greens seguidos' : data?.streak_type === 'red' ? 'Reds seguidos' : 'Sequência atual'}
                    </div>
                  </div>
                  <div className="w-px h-12 bg-zinc-800" />
                  <div className="text-center">
                    <div className="text-4xl font-black text-yellow-400">
                      {data?.best_streak > 0 ? data.best_streak : ''}
                    </div>
                    <div className="text-xs text-zinc-500 mt-1">Melhor sequência</div>
                  </div>
                </div>
              </div>

              {/* Distribuição de resultados */}
              <div className="card p-5">
                <p className="text-xs text-zinc-500 uppercase font-semibold mb-4">Distribuição de resultados</p>
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
                    <p className="text-xs text-green-500 font-black uppercase mb-2">Melhor pick apostado</p>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <TeamLogo id={data.best_pick.home_team_id} name={data.best_pick.home_team_name ?? ''} size={16} />
                          <p className="text-sm text-white font-semibold">{data.best_pick.home_team_name ?? `Pick #${data.best_pick.pick_id}`}</p>
                        </div>
                        <p className="text-xs text-zinc-500">{data.best_pick.market ?? ''}</p>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border mt-1 inline-block ${PICK_TYPE_CLS[data.best_pick.pick_type] ?? ''}`}>
                          {SOURCE_LBL[data.best_pick.pick_type] ?? data.best_pick.pick_type}
                        </span>
                      </div>
                      <span className="font-mono text-2xl font-black text-green-500">
                        +{fmtBRL(data.best_pick.pnl)}
                      </span>
                    </div>
                  </div>
                )}
                {data?.worst_pick && data.worst_pick.pnl < 0 && (
                  <div className="card p-4 border-red-500/20 bg-red-500/5">
                    <p className="text-xs text-red-400 font-black uppercase mb-2">Pior pick apostado</p>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <TeamLogo id={data.worst_pick.home_team_id} name={data.worst_pick.home_team_name ?? ''} size={16} />
                          <p className="text-sm text-white font-semibold">{data.worst_pick.home_team_name ?? `Pick #${data.worst_pick.pick_id}`}</p>
                        </div>
                        <p className="text-xs text-zinc-500">{data.worst_pick.market ?? ''}</p>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border mt-1 inline-block ${PICK_TYPE_CLS[data.worst_pick.pick_type] ?? ''}`}>
                          {SOURCE_LBL[data.worst_pick.pick_type] ?? data.worst_pick.pick_type}
                        </span>
                      </div>
                      <span className="font-mono text-2xl font-black text-red-400">
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
                <p className="text-xs text-zinc-500 uppercase font-semibold mb-4">Você vs IA</p>
                <div className="font-mono grid grid-cols-3 gap-2 sm:gap-4">
                  <div className="text-center">
                    <div className={`text-xl sm:text-2xl font-black ${(data?.yield_roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
                      {(data?.yield_roi ?? 0) >= 0 ? '+' : ''}{data.yield_roi ?? 0}%
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 font-semibold">Seu Yield</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">lucro / unidades</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-xl sm:text-2xl font-black ${(data?.roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
                      {(data?.roi ?? 0) >= 0 ? '+' : ''}{data.roi ?? 0}%
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 font-semibold">ROI banca</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">{data.total_resolved} picks</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-xl sm:text-2xl font-black ${data.ia_roi >= 0 ? 'text-green-500' : 'text-red-400'}`}>
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
              const allEntries: any[] = [...(data?.entries ?? [])].reverse().slice(0, 10)
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
                            : e.pick_type === 'multipla' ? 'Múltipla'
                            : e.pick_type === 'alavancagem' ? 'Alavancagem'
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
                        {e.market ?? ''}
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
                    </div>
                  </button>
                )
              }

              return (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs text-zinc-500 uppercase font-semibold">
                      Últimos picks apostados
                    </p>
                    <Link to="/meus-picks" className="text-xs text-green-500 hover:text-green-400 transition-colors font-semibold">
                      Ver todos
                    </Link>
                  </div>

                  {!allEntries.length ? (
                    <div className="card p-12 text-center border-dashed">
                      <p className="text-zinc-500 text-sm font-semibold mb-2">Nenhum pick apostado ainda</p>
                      <p className="text-zinc-600 text-xs mb-4">
                        Clique em "Apostar" nos picks da página Picks para registrar suas apostas aqui.
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
                            <span className="text-[10px] font-black text-zinc-500 uppercase capitalize">
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

            <MonthlyCloseSection />

          </div>
        )}

      </main>
    </div>
  )
}
