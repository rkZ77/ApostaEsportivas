import { cloneElement, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { popIn } from '../../lib/motion'

const TIP_WIDTH = 240

/*
 * Explicação curta ancorada num gatilho.
 *
 * Renderiza por portal com posição fixa calculada a partir do gatilho, pra não
 * ser cortada por container com overflow-hidden (card de pick, linha de lista).
 * Abre no toque e também no hover/foco, porque a maior parte do público é
 * mobile mas quem usa teclado precisa chegar nela também.
 */
export default function Tooltip({
  text,
  children,
  className,
}: {
  text: React.ReactNode
  /** Gatilho. Precisa aceitar ref e eventos (elemento nativo ou forwardRef). */
  children: React.ReactElement
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const ref = useRef<HTMLSpanElement>(null)
  const id = useId()

  const place = () => {
    const el = ref.current?.firstElementChild ?? ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const left = Math.max(
      8,
      Math.min(r.left + r.width / 2 - TIP_WIDTH / 2, window.innerWidth - TIP_WIDTH - 8),
    )
    setPos({ top: r.top - 8, left })
  }

  const show = () => { place(); setOpen(true) }
  const hide = () => setOpen(false)

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    const onDocClick = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return
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

  const trigger = cloneElement(children, {
    'aria-describedby': open ? id : undefined,
    onClick: (e: React.MouseEvent) => {
      e.stopPropagation()
      children.props.onClick?.(e)
      open ? hide() : show()
    },
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
  })

  return (
    <span ref={ref} className={className ? `inline-flex ${className}` : 'inline-flex'}>
      {trigger}
      {createPortal(
        <AnimatePresence>
          {open && pos && (
            <motion.div
              id={id}
              role="tooltip"
              variants={popIn}
              initial="hidden"
              animate="visible"
              exit="exit"
              onClick={e => e.stopPropagation()}
              style={{
                position: 'fixed',
                top: pos.top,
                left: pos.left,
                width: TIP_WIDTH,
                transform: 'translateY(-100%)',
                transformOrigin: 'bottom center',
              }}
              className="z-50 bg-surface-2 border border-line-strong rounded-lg px-3 py-2 text-[11px] leading-relaxed text-ink-2 shadow-elev"
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
