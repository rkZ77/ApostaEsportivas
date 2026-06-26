import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'

export default function UpdateBanner() {
  const { user } = useAuth()
  const [hasUpdate, setHasUpdate] = useState(false)
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
          setHasUpdate(true)
          setDismissed(false)
        }
      } catch {}
    }

    check()
    const id = setInterval(check, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [user])

  if (!hasUpdate || dismissed) return null

  return (
    <div
      style={{ bottom: 'calc(5rem + env(safe-area-inset-bottom))' }}
      className="fixed right-4 z-50 w-64 bg-zinc-900 border border-zinc-700 rounded-2xl shadow-xl shadow-black/50 p-4"
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <p className="text-sm font-bold text-white leading-tight">Nova versão disponível</p>
          <p className="text-xs text-zinc-400 mt-0.5">Recarregue para ver as novidades</p>
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="w-5 h-5 flex items-center justify-center rounded-full bg-zinc-700 hover:bg-zinc-600 text-zinc-400 text-xs font-black shrink-0 transition-colors"
        >
          ×
        </button>
      </div>
      <button
        onClick={() => window.location.reload()}
        className="w-full py-2 rounded-xl bg-green-600 hover:bg-green-500 text-white text-sm font-bold transition-colors"
      >
        Atualizar
      </button>
    </div>
  )
}
