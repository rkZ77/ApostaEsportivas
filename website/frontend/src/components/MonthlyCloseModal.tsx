import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, X, RefreshCw, Settings } from 'lucide-react'
import api from '../services/api'

const PLAN_MONTHLY_REF = 39.90

const fmtBRL = (v: number) =>
  'R$ ' + Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function getLastMonthKey(): string {
  const now = new Date()
  const y = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear()
  const m = now.getMonth() === 0 ? 12 : now.getMonth()
  return `${y}-${String(m).padStart(2, '0')}`
}

const LS_KEY = 'pickia_monthly_close'

export function shouldShowMonthlyClose(): boolean {
  const lastDismissed = localStorage.getItem(LS_KEY)
  return lastDismissed !== getLastMonthKey()
}

export function dismissMonthlyClose() {
  localStorage.setItem(LS_KEY, getLastMonthKey())
}

interface CloseData {
  month_label: string
  month_key: string
  total_pnl: number
  greens: number
  reds: number
  push: number
  half_wins: number
  half_loss: number
  total_resolved: number
  total_followed: number
  bankroll_start: number
  bankroll_current: number
  unit_value: number
}

interface Props {
  onClose: () => void
  onOpenSetup: () => void
}

export default function MonthlyCloseModal({ onClose, onOpenSetup }: Props) {
  const [data, setData]       = useState<CloseData | null>(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [updated, setUpdated]   = useState(false)

  useEffect(() => {
    api.get('/banca/monthly-close')
      .then(r => setData(r.data))
      .catch(() => { dismissMonthlyClose(); onClose() })
      .finally(() => setLoading(false))
  }, [])

  const handleUpdateBanca = async () => {
    if (!data) return
    setUpdating(true)
    try {
      await api.post('/banca/setup', {
        bankroll_start: data.bankroll_current,
        bankroll_goal: null,
        unit_value: data.unit_value,
      })
      setUpdated(true)
    } catch {
      // silently ignore; user can retry via setup
    } finally {
      setUpdating(false)
    }
  }

  const handleClose = () => {
    dismissMonthlyClose()
    onClose()
  }

  const handleOpenSetup = () => {
    dismissMonthlyClose()
    onOpenSetup()
  }

  if (loading) return null

  if (!data || data.total_followed === 0) {
    dismissMonthlyClose()
    onClose()
    return null
  }

  const isProfit  = data.total_pnl >= 0
  const pnlAbs    = Math.abs(data.total_pnl)
  const planMonths = isProfit ? Math.floor(data.total_pnl / PLAN_MONTHLY_REF) : 0
  const paidPlan  = isProfit && data.total_pnl >= PLAN_MONTHLY_REF

  const distTotal = data.greens + data.reds + data.push + data.half_wins + data.half_loss
  const distItems = [
    { label: 'GREEN',  value: data.greens,    color: 'bg-green-500' },
    { label: 'RED',    value: data.reds,      color: 'bg-red-500'   },
    { label: '½ WIN',  value: data.half_wins, color: 'bg-teal-500'  },
    { label: '½ LOSS', value: data.half_loss, color: 'bg-orange-500'},
    { label: 'PUSH',   value: data.push,      color: 'bg-zinc-500'  },
  ].filter(d => d.value > 0)

  return (
    <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[9998] flex items-center justify-center px-4">
      <div className="bg-zinc-950 border border-zinc-800 rounded-2xl w-full max-w-sm shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div>
            <p className="text-[10px] font-black text-zinc-500 uppercase tracking-widest mb-0.5">
              Fechamento mensal
            </p>
            <h2 className="text-white font-black text-lg">{data.month_label}</h2>
          </div>
          <button
            onClick={handleClose}
            className="w-8 h-8 flex items-center justify-center rounded-full border border-zinc-800 text-zinc-500 hover:text-white hover:border-zinc-600 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* P&L principal */}
        <div className={`mx-5 rounded-xl px-5 py-5 text-center mb-4 ${
          isProfit
            ? 'bg-green-500/10 border border-green-500/20'
            : 'bg-red-500/10 border border-red-500/20'
        }`}>
          <div className={`flex items-center justify-center gap-2 mb-1 ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
            {isProfit
              ? <TrendingUp className="w-5 h-5" />
              : <TrendingDown className="w-5 h-5" />}
            <span className="text-3xl font-black">
              {isProfit ? '+' : '−'}{fmtBRL(pnlAbs)}
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            {data.greens}G · {data.reds}R em {data.total_resolved} picks resolvidos
          </p>
        </div>

        {/* Mensagem de assinatura */}
        {paidPlan && (
          <div className="mx-5 mb-4 bg-zinc-900 rounded-xl px-4 py-3 text-center border border-zinc-800">
            <p className="text-sm font-black text-white mb-0.5">
              {planMonths >= 2
                ? `Seu lucro pagou ${planMonths} meses de assinatura`
                : 'Seu lucro pagou a assinatura deste mês'}
            </p>
            <p className="text-xs text-zinc-500">
              {planMonths >= 2
                ? `${fmtBRL(data.total_pnl)} ÷ ${fmtBRL(PLAN_MONTHLY_REF)}/mês = ${planMonths} meses`
                : `Lucro de ${fmtBRL(data.total_pnl)} vs ${fmtBRL(PLAN_MONTHLY_REF)} da assinatura mensal`}
            </p>
          </div>
        )}

        {/* Distribuição */}
        {distTotal > 0 && (
          <div className="mx-5 mb-5">
            <div className="flex h-2 rounded-full overflow-hidden gap-px">
              {distItems.map(d => (
                <div
                  key={d.label}
                  className={d.color}
                  style={{ width: `${Math.round(d.value / distTotal * 100)}%` }}
                />
              ))}
            </div>
            <div className="flex gap-3 mt-1.5 flex-wrap">
              {distItems.map(d => (
                <span key={d.label} className="text-[10px] text-zinc-500 font-semibold">
                  {d.label} {d.value}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Banca atual */}
        <div className="mx-5 mb-5 flex items-center justify-between text-xs text-zinc-500">
          <span>Banca atual</span>
          <span className={`font-black ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
            {fmtBRL(data.bankroll_current)}
          </span>
        </div>

        {/* Ações */}
        <div className="px-5 pb-5 space-y-2">
          {updated ? (
            <div className="w-full py-3 rounded-xl bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-black text-center">
              Banca atualizada para {fmtBRL(data.bankroll_current)}
            </div>
          ) : (
            <button
              onClick={handleUpdateBanca}
              disabled={updating}
              className="w-full py-3 rounded-xl bg-green-500 hover:bg-green-400 text-black text-sm font-black transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              {updating ? 'Atualizando...' : `Usar ${fmtBRL(data.bankroll_current)} como nova base`}
            </button>
          )}

          <button
            onClick={handleOpenSetup}
            className="w-full py-3 rounded-xl border border-zinc-700 hover:border-zinc-500 text-zinc-300 text-sm font-semibold transition-colors flex items-center justify-center gap-2"
          >
            <Settings className="w-4 h-4" />
            Definir novo valor de banca
          </button>

          <button
            onClick={handleClose}
            className="w-full py-2.5 text-zinc-600 hover:text-zinc-400 text-sm font-semibold transition-colors"
          >
            Fechar sem alterar
          </button>
        </div>
      </div>
    </div>
  )
}
