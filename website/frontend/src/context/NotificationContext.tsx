import { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import api from '../services/api'
import { useAuth } from './AuthContext'

const LS_KEY = 'lastSeenPickId'
const POLL_INTERVAL = 30_000

interface NotificationCtx {
  hasNew: boolean
  markSeen: () => void
}

const NotificationContext = createContext<NotificationCtx>({
  hasNew: false,
  markSeen: () => {},
})

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [hasNew, setHasNew] = useState(false)
  const latestIdRef = useRef(0)

  const check = () => {
    const lastSeen = parseInt(localStorage.getItem(LS_KEY) ?? '0', 10)
    api.get('/suggestions/latest-pick')
      .then(r => {
        const id: number = r.data.id ?? 0
        latestIdRef.current = id
        if (id > lastSeen) setHasNew(true)
      })
      .catch(() => {})
  }

  useEffect(() => {
    if (!user) { setHasNew(false); return }
    check()
    const timer = setInterval(check, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [user])

  const markSeen = () => {
    if (latestIdRef.current > 0) localStorage.setItem(LS_KEY, String(latestIdRef.current))
    setHasNew(false)
  }

  return (
    <NotificationContext.Provider value={{ hasNew, markSeen }}>
      {children}
    </NotificationContext.Provider>
  )
}

export const useNotifications = () => useContext(NotificationContext)
