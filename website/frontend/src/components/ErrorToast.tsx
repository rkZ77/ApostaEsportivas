import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { subscribeError } from '../services/errorToast'
import { toastUp } from '../lib/motion'

export default function ErrorToast() {
  const [msg, setMsg] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => subscribeError(m => {
    setMsg(m)
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
            <p className="flex-1 text-sm font-semibold text-ink-1 leading-snug">{msg}</p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
