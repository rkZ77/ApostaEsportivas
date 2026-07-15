import { useEffect, useState } from 'react'
import { Trophy, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { COPA_ENDED } from '../utils/format'

const LS_KEY = 'pickia_postcopa_dismissed'

export default function PostCopaBanner() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!user) return
    if (!COPA_ENDED) return
    if (localStorage.getItem(LS_KEY)) return
    const t = setTimeout(() => setVisible(true), 1500)
    return () => clearTimeout(t)
  }, [user])

  const dismiss = () => {
    localStorage.setItem(LS_KEY, '1')
    setVisible(false)
  }

  const goToPicks = () => {
    setVisible(false)
    navigate('/picks')
  }

  if (!visible) return null

  return (
    <div className="fixed bottom-20 left-0 right-0 z-[9988] flex justify-center px-4 pointer-events-none">
      <div className="pointer-events-auto w-full max-w-sm bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl px-4 py-4 flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-yellow-400/10 flex items-center justify-center shrink-0">
          <Trophy className="w-4 h-4 text-yellow-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-black text-white leading-snug">A Copa acabou, os picks não</p>
          <p className="text-xs text-zinc-500 truncate">Brasileirão e Premier League seguem todo dia</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={goToPicks}
            className="px-3 py-1.5 rounded-lg bg-green-500 hover:bg-green-400 text-black text-xs font-black transition-colors"
          >
            Ver picks
          </button>
          <button onClick={dismiss} className="w-7 h-7 flex items-center justify-center text-zinc-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
