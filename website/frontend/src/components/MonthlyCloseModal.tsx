import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, X, RefreshCw, Settings, BadgeCheck } from 'lucide-react'
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

const MOCK_DATA: CloseData = {
  month_label: 'Junho 2026',
  month_key: '2026-06',
  total_pnl: 187.50,
  greens: 14,
  reds: 6,
  push: 1,
  half_wins: 2,
  half_loss: 1,
  total_resolved: 24,
  total_followed: 26,
  bankroll_start: 500,
  bankroll_current: 687.50,
  unit_value: 5,
}

interface Props {
  onClose: () => void
  onOpenSetup: () => void
}

export default function MonthlyCloseModal({ onClose, onOpenSetup }: Props) {
  const isPreview = new URLSearchParams(window.location.search).get('preview') === 'monthly'

  const [data, setData]         = useState<CloseData | null>(isPreview ? MOCK_DATA : null)
  const [loading, setLoading]   = useState(!isPreview)
  const [updating, setUpdating] = useState(false)
  const [updated, setUpdated]   = useState(false)

  useEffect(() => {
    if (isPreview) return
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
    } catch { /* usuário pode tentar pelo setup */ }
    finally { setUpdating(false) }
  }

  const handleClose = () => { dismissMonthlyClose(); onClose() }
  const handleOpenSetup = () => { dismissMonthlyClose(); onOpenSetup() }

  if (loading) return null

  if (!data || data.total_followed === 0) {
    dismissMonthlyClose()
    onClose()
    return null
  }

  const isProfit   = data.total_pnl >= 0
  const pnlAbs     = Math.abs(data.total_pnl)
  const ganhoU     = data.unit_value > 0 ? data.total_pnl / data.unit_value : 0
  const winRate    = data.total_resolved > 0 ? Math.round(data.greens / data.total_resolved * 100) : 0
  const planMonths = isProfit ? Math.floor(data.total_pnl / PLAN_MONTHLY_REF) : 0
  const paidPlan   = isProfit && data.total_pnl >= PLAN_MONTHLY_REF

  const distTotal = data.greens + data.reds + data.push + data.half_wins + data.half_loss
  const distItems = [
    { label: 'GREEN',  value: data.greens,    color: 'bg-green-500' },
    { label: 'RED',    value: data.reds,       color: 'bg-red-500'  },
    { label: '½ WIN',  value: data.half_wins,  color: 'bg-teal-500' },
    { label: '½ LOSS', value: data.half_loss,  color: 'bg-orange-500' },
    { label: 'PUSH',   value: data.push,       color: 'bg-zinc-500' },
  ].filter(d => d.value > 0)

  const accent = isProfit ? 'text-green-400' : 'text-red-400'
  const accentBg = isProfit
    ? 'bg-green-500/10 border-green-500/20'
    : 'bg-red-500/10 border-red-500/20'

  return (
    <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[9998] flex items-end sm:items-center justify-center">
      <div className="bg-zinc-950 border border-zinc-800 rounded-t-2xl sm:rounded-2xl w-full sm:max-w-sm shadow-2xl overflow-y-auto max-h-[92dvh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div>
            <p className="text-[10px] font-black text-zinc-500 uppercase tracking-widest mb-0.5">
              Fechamento mensal
            </p>
            <h2 className="text-white font-black text-xl">{data.month_label}</h2>
          </div>
          <button
            onClick={handleClose}
            className="w-8 h-8 flex items-center justify-center rounded-full border border-zinc-800 text-zinc-500 hover:text-white hover:border-zinc-600 transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Bloco P&L principal — vertical para não quebrar com números grandes */}
        <div className={`mx-5 rounded-xl px-4 py-4 mb-3 border ${accentBg}`}>
          {/* Ícone + R$ */}
          <div className={`flex items-center gap-2 mb-1 ${accent}`}>
            {isProfit ? <TrendingUp className="w-5 h-5 shrink-0" /> : <TrendingDown className="w-5 h-5 shrink-0" />}
            <span className="text-[28px] leading-tight font-black break-all">
              {isProfit ? '+' : '−'}{fmtBRL(pnlAbs)}
            </span>
          </div>
          {/* Unidades — linha separada, menor */}
          <p className={`text-sm font-black ml-7 mb-3 ${accent} opacity-75`}>
            {ganhoU >= 0 ? '+' : ''}{ganhoU.toFixed(1)} unidades
            <span className="text-zinc-600 font-normal ml-1">(1u = {fmtBRL(data.unit_value)})</span>
          </p>
          {/* Linha picks + win rate */}
          <div className="flex items-center justify-between pt-2 border-t border-white/5">
            <span className="text-[11px] text-zinc-500">
              {data.greens}G · {data.reds}R
              {data.half_wins > 0 ? ` · ${data.half_wins}½W` : ''}
              {data.half_loss > 0 ? ` · ${data.half_loss}½L` : ''}
              {data.push > 0 ? ` · ${data.push}P` : ''}
              {' '}· {data.total_resolved} picks
            </span>
            <span className={`text-[11px] font-bold ${winRate >= 55 ? 'text-green-400' : 'text-zinc-400'}`}>
              {winRate}% win rate
            </span>
          </div>
        </div>

        {/* Banca início → fim */}
        {(() => {
          const bancaNoInicio = data.bankroll_current - data.total_pnl
          return (
            <div className="mx-5 mb-3 flex items-center gap-3 bg-zinc-900 rounded-xl border border-zinc-800 px-4 py-3">
              <div className="flex-1 min-w-0">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Início do mês</p>
                <p className="text-sm font-black text-zinc-300 truncate">{fmtBRL(bancaNoInicio)}</p>
              </div>
              <div className={`w-6 h-px shrink-0 ${isProfit ? 'bg-green-500/50' : 'bg-red-500/50'}`} />
              <div className="flex-1 min-w-0 text-right">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Fim do mês</p>
                <p className={`text-sm font-black truncate ${accent}`}>{fmtBRL(data.bankroll_current)}</p>
              </div>
            </div>
          )
        })()}

        {/* Assinatura paga com lucro */}
        {paidPlan && (
          <div className="mx-5 mb-3 bg-green-500/10 border border-green-500/20 rounded-xl px-4 py-3 flex items-center gap-3">
            <BadgeCheck className="w-5 h-5 shrink-0 text-green-400" />
            <p className="text-sm font-black text-green-300 leading-snug">
              Esse mês você já pagou sua assinatura do Pick IA com o lucro
            </p>
          </div>
        )}

        {/* Distribuição */}
        {distTotal > 0 && (
          <div className="mx-5 mb-4">
            <div className="flex h-1.5 rounded-full overflow-hidden gap-px">
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

        {/* Ações */}
        <div className="px-5 pb-6 space-y-2">
          {updated ? (
            <div className="w-full py-3 rounded-xl bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-black text-center">
              Banca atualizada para {fmtBRL(data.bankroll_current)}
            </div>
          ) : (
            <button
              onClick={handleUpdateBanca}
              disabled={updating}
              className="btn-primary w-full py-3 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
            >
              <RefreshCw className="w-4 h-4 shrink-0" />
              <span className="truncate">
                {updating ? 'Atualizando...' : `Usar ${fmtBRL(data.bankroll_current)} como nova base`}
              </span>
            </button>
          )}

          <button
            onClick={handleOpenSetup}
            className="btn-ghost w-full py-3 text-sm flex items-center justify-center gap-2"
          >
            <Settings className="w-4 h-4 shrink-0" />
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
