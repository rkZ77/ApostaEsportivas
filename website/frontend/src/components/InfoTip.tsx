import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Info } from 'lucide-react'
import { popIn } from '../lib/motion'

const TIP_WIDTH = 240

/**
 * Ícone de informação que abre uma explicação curta ao toque.
 * Renderiza via portal com posição fixa calculada a partir do botão, pra não
 * ser cortado por containers com overflow-hidden (cards de picks, listas).
 */
export default function InfoTip({ text, className = '' }: { text: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      let left = r.left + r.width / 2 - TIP_WIDTH / 2
      left = Math.max(8, Math.min(left, window.innerWidth - TIP_WIDTH - 8))
      setPos({ top: r.top - 8, left })
    }
    setOpen(o => !o)
  }

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    const onDocClick = (e: MouseEvent) => {
      if (btnRef.current && btnRef.current.contains(e.target as Node)) return
      setOpen(false)
    }
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    document.addEventListener('click', onDocClick)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
      document.removeEventListener('click', onDocClick)
    }
  }, [open])

  return (
    <span className={`inline-flex ${className}`}>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        aria-label="O que significa"
        className="text-ink-4 hover:text-ink-2 transition-colors shrink-0"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      {createPortal(
        <AnimatePresence>
          {open && pos && (
            <motion.div
              variants={popIn}
              initial="hidden"
              animate="visible"
              exit="exit"
              onClick={e => e.stopPropagation()}
              style={{ position: 'fixed', top: pos.top, left: pos.left, width: TIP_WIDTH, transform: 'translateY(-100%)', transformOrigin: 'bottom center' }}
              className="z-50 bg-surface-2 border border-line-strong rounded-lg px-3 py-2 text-[11px] leading-relaxed text-ink-2 shadow-xl"
            >
              {text}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </span>
  )
}
