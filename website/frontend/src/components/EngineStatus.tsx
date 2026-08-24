import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, CircleDashed, Loader2, XCircle } from 'lucide-react'
import api from '../services/api'
import { LiveDot } from './ui'

/*
 * Indicador de "a IA está rodando agora".
 *
 * Lê /admin/pipeline-status-public, que devolve o estado dos passos sem log
 * nem erro técnico. O endpoint exige login, então o componente só monta pra
 * quem está logado (quem chama garante isso).
 *
 * O poll só existe enquanto a análise está rodando. Depois que termina, ele
 * para: a página de picks fica aberta por muito tempo e um poll eterno a cada
 * 8s vira ruído no servidor sem nada pra mostrar.
 */

interface Step {
  key: string
  label: string
  status: 'pending' | 'running' | 'done' | 'error'
}
interface Status {
  running: boolean
  finished: boolean
  steps: Step[]
}

const POLL_MS = 8000

function StepIcon({ status }: { status: Step['status'] }) {
  if (status === 'done')    return <CheckCircle2 className="w-3.5 h-3.5 text-accent-ink shrink-0" />
  if (status === 'running') return <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin shrink-0" />
  if (status === 'error')   return <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
  return <CircleDashed className="w-3.5 h-3.5 text-ink-4 shrink-0" />
}

export default function EngineStatus() {
  const [status, setStatus] = useState<Status | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    let timer: number | undefined

    const tick = async () => {
      try {
        const { data } = await api.get('/admin/pipeline-status-public')
        if (!alive) return
        setStatus(data)
        // segue pollando só enquanto houver o que acompanhar
        if (data?.running) timer = window.setTimeout(tick, POLL_MS)
      } catch {
        // sem permissão ou fora do ar: o indicador simplesmente não aparece
        if (alive) setStatus(null)
      }
    }

    tick()
    return () => { alive = false; if (timer) window.clearTimeout(timer) }
  }, [])

  // Nada rodando não vira faixa: o estado normal da tela é a IA parada, e um
  // aviso permanente de "tudo certo" só rouba espaço do conteúdo.
  if (!status?.running) return null

  const done = status.steps.filter(s => s.status === 'done').length
  const total = status.steps.length

  return (
    <div className="mb-4 rounded-lg border border-amber-400/30 bg-amber-400/5 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left"
      >
        <LiveDot tone="amber" />
        <span className="text-xs font-semibold text-amber-300 flex-1 min-w-0">
          A IA está analisando os jogos agora
        </span>
        <span className="font-mono text-[11px] text-amber-400/80 tabular-nums shrink-0">
          {done}/{total}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
            className="overflow-hidden border-t border-amber-400/20"
          >
            <ul className="px-4 py-3 space-y-2">
              {status.steps.map(s => (
                <li key={s.key} className="flex items-center gap-2 text-[11px]">
                  <StepIcon status={s.status} />
                  <span className={s.status === 'pending' ? 'text-ink-4' : 'text-ink-2'}>
                    {s.label}
                  </span>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
