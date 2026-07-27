import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Sparkles } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'
import { CHANGELOG } from '../data/changelog'
import { backdropFade, dialogScale, toastUp } from '../lib/motion'

const SEEN_KEY = 'pickia_changelog_seen'
const latestEntry = CHANGELOG[CHANGELOG.length - 1]

export default function UpdateBanner() {
  const { user } = useAuth()
  const [showNotes, setShowNotes]   = useState(false)
  const [staleBundle, setStaleBundle] = useState(false)
  const [dismissed, setDismissed]   = useState(false)
  const versionRef = useRef<string | null>(null)
  const isInitialMount = useRef(true)

  // Novidade curada que esse usuário ainda não viu · mostra no momento do login,
  // não numa sessão só restaurada ao abrir o app (senão só reaparecia limpando localStorage).
  useEffect(() => {
    const wasInitialMount = isInitialMount.current
    isInitialMount.current = false
    if (!user || !latestEntry) return
    if (wasInitialMount) return
    if (localStorage.getItem('pickia_just_registered')) return
    if (localStorage.getItem(SEEN_KEY) !== latestEntry.id) setShowNotes(true)
  }, [user])

  // Aba já aberta durante um redeploy · pacote JS ficou desatualizado, pede reload.
  // Só entra em jogo se não tiver novidade curada esperando (essa já força reload).
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

  const markSeen = () => {
    if (latestEntry) localStorage.setItem(SEEN_KEY, latestEntry.id)
    setShowNotes(false)
  }

  return (
    <AnimatePresence>
      {showNotes && latestEntry && (
        <motion.div
          key="changelog-backdrop"
          variants={backdropFade}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4"
        >
          <motion.div
            variants={dialogScale}
            className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 max-w-sm w-full overflow-y-auto max-h-[92dvh]"
          >
            <div className="w-11 h-11 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mb-4">
              <Sparkles className="w-5 h-5 text-green-400" />
            </div>
            <h3 className="text-white font-black text-lg mb-1">Novidades no Pick IA</h3>
            <p className="text-zinc-500 text-xs mb-4">Atualizado em {latestEntry.date}</p>
            <ul className="space-y-2.5 mb-5">
              {latestEntry.items.map((item, i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm text-zinc-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-500 mt-1.5 shrink-0" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
            <motion.button whileTap={{ scale: 0.98 }} onClick={markSeen} className="btn-primary w-full py-2.5 text-sm">
              Entendi
            </motion.button>
          </motion.div>
        </motion.div>
      )}

      {!showNotes && staleBundle && !dismissed && (
        <motion.div
          key="stale-bundle-chip"
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          style={{ bottom: 'calc(5rem + env(safe-area-inset-bottom))' }}
          className="fixed right-2 sm:right-4 z-50 w-56 sm:w-64 bg-zinc-900 border border-zinc-700 rounded-2xl shadow-xl shadow-black/50 p-4"
        >
          <div className="flex items-start justify-between gap-2 mb-3">
            <div>
              <p className="text-sm font-bold text-white leading-tight">Nova versão disponível</p>
              <p className="text-xs text-zinc-400 mt-0.5">Recarregue para ver as novidades</p>
            </div>
            <button
              onClick={() => setDismissed(true)}
              className="w-8 h-8 flex items-center justify-center rounded-full bg-zinc-700 hover:bg-zinc-600 text-zinc-400 text-sm font-black shrink-0 transition-colors"
            >
              ×
            </button>
          </div>
          <motion.button
            whileTap={{ scale: 0.98 }}
            onClick={() => window.location.reload()}
            className="w-full py-2 rounded-xl bg-green-600 hover:bg-green-500 text-white text-sm font-bold transition-colors"
          >
            Atualizar
          </motion.button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
