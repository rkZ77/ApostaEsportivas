import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { subscribeError } from '../services/errorToast'
import { toastUp } from '../lib/motion'

export default function ErrorToast() {
  const [msg, setMsg] = useState<string | null>(null)
  const [codigo, setCodigo] = useState<string | undefined>()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => subscribeError((m, c) => {
    setMsg(m)
    setCodigo(c)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setMsg(null), 4000)
  }), [])

  return (
    <AnimatePresence>
      {msg && (
        <motion.div
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          /* MESMO CARTAO DOS OUTROS AVISOS (10/09/2026).
            *
            * Este era o unico em bloco vermelho solido, e ficava em `bottom-6`
            * -- ou seja, por cima do banner de cookies. Erro continua sendo o
            * mais urgente da pilha e por isso fica embaixo, mais perto do
            * dedo; o vermelho passa pela borda e pelo icone, que e' como o
            * resto do site marca urgencia. */
          className="w-full max-w-md pointer-events-auto"
        >
          <div role="alert" className="w-full bg-surface-1 border border-red-500/40 rounded-lg
                          shadow-2xl px-4 py-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-red-500/10 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-4 h-4 text-red-400" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink-1 leading-snug">{msg}</p>
              {/* O codigo so' aparece quando o servidor mandou um. E' o que
                  liga o que a pessoa viu a' linha de log: pedir "manda o
                  codigo do aviso" resolve em segundos o que antes era
                  procurar por horario. */}
              {codigo && (
                <p className="text-[11px] text-ink-4 font-mono mt-1">Código {codigo}</p>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
