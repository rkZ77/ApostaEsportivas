import { useEffect, useState } from 'react'
import { Bell, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { usePushNotification } from '../hooks/usePushNotification'

const LS_KEY = 'pickia_push_dismissed'

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
    if (localStorage.getItem(LS_KEY)) return
    // pequeno delay para não aparecer junto com o modal de fechamento mensal
    const t = setTimeout(() => setVisible(true), 1500)
    return () => clearTimeout(t)
  }, [user, push.supported, push.permission, push.subscribed, push.vapidKey])

  // fecha automaticamente se o usuário ativar pelo Profile enquanto o banner está aberto
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
    localStorage.setItem(LS_KEY, '1')
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div className="fixed bottom-20 left-0 right-0 z-[9990] flex justify-center px-4 pointer-events-none">
      <div className="pointer-events-auto w-full max-w-sm bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl px-4 py-4 flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-green-500/10 flex items-center justify-center shrink-0">
          <Bell className="w-4 h-4 text-green-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-black text-white leading-snug">Ativar notificacoes</p>
          <p className="text-xs text-zinc-500 truncate">Aviso quando os picks do dia saírem</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={handleActivate}
            disabled={activating}
            className="px-3 py-1.5 rounded-lg bg-green-500 hover:bg-green-400 text-black text-xs font-black transition-colors disabled:opacity-50"
          >
            {activating ? '...' : 'Ativar'}
          </button>
          <button onClick={dismiss} className="w-7 h-7 flex items-center justify-center text-zinc-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
