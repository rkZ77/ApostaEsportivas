import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarCheck, ChevronRight, History } from 'lucide-react'
import api from '../services/api'
import { fmtSigned } from '../utils/format'
import { useNotifications } from '../context/NotificationContext'

/**
 * Fechamento PENDENTE, e um caminho pro histórico.
 *
 * A lista mês a mês morava aqui embaixo e foi pra /banca/fechamentos. A
 * divisão é por natureza, não por tamanho: o fechamento pendente é AÇÃO (tem
 * prazo, muda a banca, precisa de confirmação) e por isso continua na tela
 * onde a banca é operada. O histórico é consulta, cresce um item por mês para
 * sempre, e empurrava tudo pra baixo sem limite numa página que já fala do
 * mês corrente.
 */
export default function MonthlyCloseSection() {
  const { openMonthlyClose, monthlyCloseOpen } = useNotifications()
  const [pending, setPending] = useState<{ month_label: string; total_pnl: number } | null>(null)
  const [historico, setHistorico] = useState(0)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    Promise.all([
      api.get('/banca/monthly-close').catch(() => null),
      api.get('/banca/monthly-closes').catch(() => null),
    ]).then(([closeRes, histRes]) => {
      const c = closeRes?.data
      // Campos do fechamento de alavancagem mudaram junto com os caminhos:
      // o que conta agora e caminho ENCERRADO (na mao ou na meta) e caminho
      // que estourou, nao green/red de degrau. Com os nomes velhos isto era
      // sempre falso e o fechamento sumia pra quem so tinha alavancagem.
      const alav = c?.alavancagem
      const hasActivity = c && (c.total_followed > 0 ||
        (alav && (alav.closed_this_month > 0 || alav.busted_this_month)))
      setPending(c && !c.already_closed && hasActivity
        ? { month_label: c.month_label, total_pnl: c.total_pnl }
        : null)
      setHistorico((histRes?.data ?? []).length)
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // Recarrega quando o modal fecha · a banca pode ter acabado de ser confirmada
  useEffect(() => { if (!monthlyCloseOpen) load() }, [monthlyCloseOpen, load])

  if (loading || (!pending && historico === 0)) return null

  return (
    <div>
      <p className="text-xs text-ink-3 font-semibold mb-3">Fechamentos mensais</p>

      {pending && (
        <button
          onClick={openMonthlyClose}
          className="w-full card p-4 mb-3 border-yellow-400/30 bg-yellow-400/[0.06] flex items-center gap-3 text-left hover:border-yellow-400/50 transition-colors"
        >
          <CalendarCheck className="w-5 h-5 shrink-0 text-yellow-400" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-black text-ink-1">Fechamento de {pending.month_label} disponível</p>
            <p className="text-xs text-ink-2 leading-snug">
              {fmtSigned(pending.total_pnl)} no mês, confirme sua banca para começar o mês novo
            </p>
          </div>
          <ChevronRight className="w-4 h-4 shrink-0 text-ink-3" />
        </button>
      )}

      {historico > 0 && (
        <Link
          to="/banca/fechamentos"
          className="card p-4 flex items-center gap-3 hover:border-line-strong transition-colors"
        >
          <History className="w-4 h-4 shrink-0 text-ink-3" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-ink-1">Ver fechamentos anteriores</p>
            <p className="text-[11px] text-ink-3">
              {historico === 1 ? '1 mês registrado' : `${historico} meses registrados`}
            </p>
          </div>
          <ChevronRight className="w-4 h-4 shrink-0 text-ink-3" />
        </Link>
      )}
    </div>
  )
}
