import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'

export default function UpdateBanner() {
  const { user } = useAuth()
  const [hasUpdate, setHasUpdate] = useState(false)
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
        }
      } catch {}
    }

    check()
    const id = setInterval(check, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [user])

  if (!hasUpdate) return null

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-between gap-4 px-5 py-4 bg-zinc-900 border-t border-zinc-700 shadow-xl">
      <div>
        <p className="text-sm font-bold text-white">Nova versao disponivel</p>
        <p className="text-xs text-zinc-400">Recarregue para ver as novidades</p>
      </div>
      <button
        onClick={() => window.location.reload()}
        className="shrink-0 text-sm font-bold px-4 py-2 rounded-lg bg-green-600 text-white hover:bg-green-500 transition-colors"
      >
        Atualizar
      </button>
    </div>
  )
}
