import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Bell, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { usePushNotification } from '../hooks/usePushNotification'
import { toastUp } from '../lib/motion'

const LS_KEY = 'pickia_push_dismissed_at'
const RESNOOZE_DAYS = 14

function isSnoozed(): boolean {
  const raw = localStorage.getItem(LS_KEY)
  if (!raw) return false
  const dismissedAt = Number(raw)
  if (!dismissedAt) return false
  const elapsedDays = (Date.now() - dismissedAt) / (1000 * 60 * 60 * 24)
  return elapsedDays < RESNOOZE_DAYS
}

export default function PushPromptBanner() {
  const { user } = useAuth()
  const push = usePushNotification()
  const [visible, setVisible] = useState(false)
  const [activating, setActivating] = useState(false)

  useEffect(() => {
    if (!user) return
    if (!push.supported) return
    if (push.permission === 'denied') return
    if (push.subscribed) return
    if (!push.vapidKey) return
    // Convite reaparece a cada RESNOOZE_DAYS se ainda nao ativou -- antes sumia
    // pra sempre no primeiro "fechar", perdendo qualquer segunda chance de
    // reduzir a friccao de precisar abrir o app todo dia pra ver os picks.
    if (isSnoozed()) return
    const t = setTimeout(() => setVisible(true), 1500)
    return () => clearTimeout(t)
  }, [user, push.supported, push.permission, push.subscribed, push.vapidKey])

  useEffect(() => {
    if (push.subscribed) setVisible(false)
  }, [push.subscribed])

  const handleActivate = async () => {
    setActivating(true)
    await push.subscribe()
    setActivating(false)
    dismiss()
  }

  const dismiss = () => {
    localStorage.setItem(LS_KEY, String(Date.now()))
    setVisible(false)
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed bottom-40 left-0 right-0 z-[9990] flex justify-center px-4 pointer-events-none"
        >
          <div className="pointer-events-auto w-full max-w-sm bg-surface-1 border border-line-strong rounded-lg shadow-2xl px-4 py-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-green-500/10 flex items-center justify-center shrink-0">
              <Bell className="w-4 h-4 text-green-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-black text-ink-1 leading-snug">Ativar notificações</p>
              <p className="text-xs text-ink-3 truncate">Aviso quando os picks do dia saírem</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleActivate}
                disabled={activating}
                className="px-3 py-1.5 rounded-lg bg-green-500 hover:bg-green-400 text-black text-xs font-black transition-colors disabled:opacity-50"
              >
                {activating ? '...' : 'Ativar'}
              </motion.button>
              <button onClick={dismiss} className="w-7 h-7 flex items-center justify-center text-ink-3 hover:text-ink-1 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
