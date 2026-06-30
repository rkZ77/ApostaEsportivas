import { useEffect, useRef, useState } from 'react'
import { subscribeError } from '../services/errorToast'

export default function ErrorToast() {
  const [msg, setMsg] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => subscribeError(m => {
    setMsg(m)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setMsg(null), 4000)
  }), [])

  if (!msg) return null

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] bg-red-600 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg max-w-[90vw] text-center">
      {msg}
    </div>
  )
}
