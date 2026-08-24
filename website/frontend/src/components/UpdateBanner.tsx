import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'
import { toastUp } from '../lib/motion'

/*
 * Aviso de pacote desatualizado · aba aberta durante um redeploy.
 *
 * O QUE SAIU DAQUI (2026-08-05, pedido do usuário)
 * ------------------------------------------------
 * Este arquivo também mostrava o modal "Novidades no Pick IA", montado a
 * partir de data/changelog.ts. Saiu por dois motivos, e o segundo é o que
 * decidiu:
 *
 * 1. Ele quase nunca aparecia. A condição exigia que `user` mudasse DEPOIS da
 *    montagem inicial (`if (wasInitialMount) return`), ou seja: só no instante
 *    do login. Quem já entrava com sessão restaurada nunca via, e o changelog
 *    precisava ser mantido à mão pra um popup que raramente abria.
 * 2. Aviso não deve interromper. O sino (NotificationBell) é o lugar de
 *    qualquer coisa que o site queira contar, e um modal em cima da tela é o
 *    oposto disso · o usuário abriu o site pra ver picks.
 *
 * Este aviso aqui FICA porque não é notificação: é uma condição de erro. O JS
 * em memória aponta pra chunks que não existem mais no servidor, e sem
 * recarregar a navegação quebra (ver RouteErrorBoundary em App.tsx). Ele
 * também não empilha no topo · é um chip no canto inferior.
 */
export default function UpdateBanner() {
  const { user } = useAuth()
  const [staleBundle, setStaleBundle] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const versionRef = useRef<string | null>(null)

  useEffect(() => {
    if (!user) return

    const check = async () => {
      try {
        const res = await api.get('/version')
        const v: string = res.data?.v
        if (!v) return
        if (versionRef.current === null) {
          versionRef.current = v
        } else if (versionRef.current !== v) {
          setStaleBundle(true)
          setDismissed(false)
        }
      } catch {}
    }

    check()
    const id = setInterval(check, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [user])

  return (
    <AnimatePresence>
      {staleBundle && !dismissed && (
        <motion.div
          key="stale-bundle-chip"
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          style={{ bottom: 'calc(5rem + env(safe-area-inset-bottom))' }}
          className="fixed right-2 sm:right-4 z-50 w-56 sm:w-64 bg-surface-1 border border-line-strong rounded-lg shadow-xl shadow-black/50 p-4"
        >
          <div className="flex items-start justify-between gap-2 mb-3">
            <div>
              <p className="text-sm font-bold text-ink-1 leading-tight">Nova versão disponível</p>
              <p className="text-xs text-ink-2 mt-0.5">Recarregue para ver as novidades</p>
            </div>
            <button
              onClick={() => setDismissed(true)}
              className="w-8 h-8 flex items-center justify-center rounded-full bg-surface-3 hover:bg-surface-3 text-ink-2 text-sm font-black shrink-0 transition-colors"
            >
              ×
            </button>
          </div>
          <motion.button
            whileTap={{ scale: 0.98 }}
            onClick={() => window.location.reload()}
            className="w-full py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-bold transition-colors"
          >
            Atualizar
          </motion.button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
