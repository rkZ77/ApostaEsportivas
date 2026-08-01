import { useCallback, useEffect, useState } from 'react'
import { CalendarCheck, ChevronRight, TrendingDown, TrendingUp } from 'lucide-react'
import api from '../services/api'
import { fmtBRL, fmtSigned } from '../utils/format'
import { useNotifications } from '../context/NotificationContext'

interface CloseRow {
  month_key: string
  month_label: string
  bankroll_start: number
  bankroll_end: number
  total_pnl: number
  profit_units: number | null
  greens: number
  reds: number
  half_wins: number
  half_loss: number
  push: number
  total_resolved: number
}

/**
 * Fechamento pendente + histórico mês a mês.
 *
 * O histórico já existia na tabela `banca_monthly_closes` desde que o
 * fechamento foi criado, mas nenhuma tela lia · o usuário só via o resumo do
 * mês uma vez, no popup, e nunca mais.
 */
export default function MonthlyCloseSection() {
  const { openMonthlyClose, monthlyCloseOpen } = useNotifications()
  const [pending, setPending] = useState<{ month_label: string; total_pnl: number } | null>(null)
  const [history, setHistory] = useState<CloseRow[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    Promise.all([
      api.get('/banca/monthly-close').catch(() => null),
      api.get('/banca/monthly-closes').catch(() => null),
    ]).then(([closeRes, histRes]) => {
      const c = closeRes?.data
      const hasActivity = c && (c.total_followed > 0 ||
        (c.alavancagem && (c.alavancagem.greens_this_month > 0 || c.alavancagem.reds_this_month > 0)))
      setPending(c && !c.already_closed && hasActivity
        ? { month_label: c.month_label, total_pnl: c.total_pnl }
        : null)
      setHistory(histRes?.data ?? [])
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // Recarrega quando o modal fecha · a banca pode ter acabado de ser confirmada
  useEffect(() => { if (!monthlyCloseOpen) load() }, [monthlyCloseOpen, load])

  if (loading || (!pending && history.length === 0)) return null

  return (
    <div>
      <p className="text-xs text-zinc-500 uppercase font-semibold mb-3">Fechamentos mensais</p>

      {pending && (
        <button
          onClick={openMonthlyClose}
          className="w-full card p-4 mb-3 border-yellow-400/30 bg-yellow-400/[0.06] flex items-center gap-3 text-left hover:border-yellow-400/50 transition-colors"
        >
          <CalendarCheck className="w-5 h-5 shrink-0 text-yellow-400" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-black text-white">Fechamento de {pending.month_label} disponível</p>
            <p className="text-xs text-zinc-400 leading-snug">
              {fmtSigned(pending.total_pnl)} no mês · confirme sua banca para começar o mês novo
            </p>
          </div>
          <ChevronRight className="w-4 h-4 shrink-0 text-zinc-500" />
        </button>
      )}

      {history.length > 0 && (
        <div className="card overflow-hidden divide-y divide-zinc-800/60">
          {history.map(h => {
            const profit = h.total_pnl >= 0
            return (
              <div key={h.month_key} className="px-4 py-3 flex items-center gap-3">
                {profit
                  ? <TrendingUp className="w-4 h-4 shrink-0 text-green-500" />
                  : <TrendingDown className="w-4 h-4 shrink-0 text-red-400" />}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-white capitalize truncate">{h.month_label}</p>
                  <p className="text-[11px] text-zinc-500 truncate">
                    {h.greens}G · {h.reds}R
                    {h.total_resolved ? ` em ${h.total_resolved} picks` : ''}
                    {' · '}{fmtBRL(h.bankroll_start)} para {fmtBRL(h.bankroll_end)}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className={`text-sm font-black ${profit ? 'text-green-500' : 'text-red-400'}`}>
                    {fmtSigned(h.total_pnl)}
                  </p>
                  {h.profit_units != null && (
                    <p className="text-[10px] text-zinc-600">
                      {h.profit_units >= 0 ? '+' : ''}{h.profit_units.toFixed(1)}u
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
