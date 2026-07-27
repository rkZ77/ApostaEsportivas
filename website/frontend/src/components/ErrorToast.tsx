import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
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
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] bg-red-600 text-white text-sm font-semibold px-5 py-3 rounded-xl shadow-lg max-w-[90vw] text-center"
        >
          {msg}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
