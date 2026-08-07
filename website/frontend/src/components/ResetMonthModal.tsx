import { useState } from 'react'
import { motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { backdropFade, dialogScale } from '../lib/motion'
import { fmtSigned } from '../utils/format'

/*
 * Aviso de "zerar o mês".
 *
 * A ação é irreversível e não tem desfazer, então o card não pergunta "tem
 * certeza?" e sim MOSTRA o que vai embora e o que fica. "Tem certeza" é uma
 * pergunta que ninguém lê; uma lista com o número real de apostas e o saldo
 * que some, sim.
 *
 * O botão de confirmar é vermelho e é o único vermelho da tela · quem chegou
 * aqui sem querer não confunde com o de fechar.
 */
export default function ResetMonthModal({
  mes, apostas, pnl, onConfirm, onClose,
}: {
  mes: string
  /** Quantas apostas do mês somem. Vem do mesmo cálculo do fechamento mensal. */
  apostas: number
  pnl: number
  onConfirm: () => Promise<void>
  onClose: () => void
}) {
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')

  const confirmar = async () => {
    setErro('')
    setSalvando(true)
    try {
      await onConfirm()
    } catch (e: any) {
      setErro(e?.response?.data?.detail ?? 'Não foi possível zerar agora. Tente de novo.')
      setSalvando(false)
    }
  }

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4"
      onClick={onClose}
    >
      <motion.div
        variants={dialogScale}
        onClick={e => e.stopPropagation()}
        className="bg-surface-1 border border-red-500/30 rounded-lg p-6 w-full max-w-md overflow-y-auto max-h-[92dvh]"
      >
        <div className="flex items-start gap-3 mb-4">
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <div>
            <h2 className="text-ink-1 font-bold text-lg leading-tight">Zerar {mes}</h2>
            <p className="text-ink-3 text-xs mt-1">Não dá pra desfazer depois.</p>
          </div>
        </div>

        <div className="bg-surface-0 border border-line rounded-lg divide-y divide-line/60 mb-4">
          <div className="px-4 py-3">
            <p className="text-[11px] text-ink-3 mb-2 font-semibold">Some da sua banca</p>
            <ul className="space-y-1.5 text-xs text-ink-2">
              <li className="flex items-center justify-between gap-3">
                <span>Apostas registradas em {mes}</span>
                <span className="font-mono font-bold text-ink-1 tabular-nums">{apostas}</span>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span>Saldo do mês</span>
                <span className={`font-mono font-bold tabular-nums ${pnl > 0 ? 'text-green-500' : pnl < 0 ? 'text-red-400' : 'text-ink-2'}`}>
                  {pnl === 0 ? 'R$ 0' : fmtSigned(pnl)}
                </span>
              </li>
            </ul>
          </div>

          <div className="px-4 py-3">
            <p className="text-[11px] text-ink-3 mb-2 font-semibold">Continua como está</p>
            <ul className="space-y-1 text-xs text-ink-3">
              <li>Meses anteriores e os fechamentos já confirmados</li>
              <li>Sua banca inicial, o valor da unidade e a meta</li>
              <li>Seus saques registrados</li>
              <li>Os picks de alavancagem, que têm banca própria</li>
            </ul>
          </div>
        </div>

        <p className="text-[11px] text-ink-4 leading-relaxed mb-5">
          As apostas somem só da sua banca · os picks em si continuam publicados e você
          pode registrar de novo os que quiser. Sua banca volta a ser o que era no
          começo de {mes}.
        </p>

        {erro && <p className="text-red-400 text-xs mb-3">{erro}</p>}

        <div className="flex flex-col-reverse sm:flex-row gap-2">
          <button onClick={onClose} disabled={salvando} className="btn-ghost flex-1 py-2.5 text-sm">
            Cancelar
          </button>
          <button
            onClick={confirmar}
            disabled={salvando || apostas === 0}
            className="flex-1 py-2.5 text-sm font-bold rounded-md bg-red-500/15 border border-red-500/40 text-red-400 hover:bg-red-500/25 transition-colors disabled:opacity-40"
          >
            {salvando ? 'Zerando...' : apostas === 0 ? 'Nada pra zerar' : `Zerar as ${apostas} apostas`}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
