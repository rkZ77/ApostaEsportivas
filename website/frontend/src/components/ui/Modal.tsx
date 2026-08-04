import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { backdropFade, sheetUp, dialogScale, drawerRight } from '../../lib/motion'

/*
 * Casca de sobreposição do sistema.
 *
 * Oito componentes reconstruíam isso à mão (ApostaModal, FixtureStatsModal,
 * MonthlyCloseModal, SuggestionDetail, LivePicks, NotificationBell e as folhas
 * dentro de Picks/Banca/Fixtures). Nenhum deles fechava no Esc, prendia o foco
 * ou travava o scroll do fundo, então no mobile a página de trás rolava junto
 * e o leitor de tela continuava lendo o conteúdo coberto.
 *
 * Quem chama continua controlando a animação de entrada com AnimatePresence,
 * igual antes: <AnimatePresence>{open && <Modal .../>}</AnimatePresence>.
 */

/** Elementos que podem receber foco dentro do diálogo. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function useDialogBehavior(onClose: () => void, ref: React.RefObject<HTMLDivElement>) {
  // Trava o scroll do fundo. Compensa a barra que some pra página não "pular".
  useEffect(() => {
    const { body } = document
    const prevOverflow = body.style.overflow
    const prevPad = body.style.paddingRight
    const gap = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (gap > 0) body.style.paddingRight = `${gap}px`
    return () => {
      body.style.overflow = prevOverflow
      body.style.paddingRight = prevPad
    }
  }, [])

  // Esc fecha, Tab circula dentro do diálogo, foco volta pra quem abriu.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null

    const first = ref.current?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? ref.current)?.focus({ preventScroll: true })

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab' || !ref.current) return
      const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter(el => el.offsetParent !== null)
      if (items.length === 0) return
      const head = items[0]
      const tail = items[items.length - 1]
      if (e.shiftKey && document.activeElement === head) {
        e.preventDefault()
        tail.focus()
      } else if (!e.shiftKey && document.activeElement === tail) {
        e.preventDefault()
        head.focus()
      }
    }

    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      opener?.focus?.({ preventScroll: true })
    }
  }, [onClose, ref])
}

const WIDTH = {
  xs: 'max-w-xs',
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-2xl',
} as const

export default function Modal({
  onClose,
  children,
  title,
  description,
  width = 'md',
  /** No mobile sobe de baixo como folha; no desktop centraliza. */
  sheetOnMobile = true,
  hideClose,
  className,
}: {
  onClose: () => void
  children: React.ReactNode
  /** Cabeçalho pronto. Omitir quando o conteúdo já traz o seu. */
  title?: React.ReactNode
  description?: React.ReactNode
  width?: keyof typeof WIDTH
  sheetOnMobile?: boolean
  hideClose?: boolean
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descId = useId()
  useDialogBehavior(onClose, ref)

  return createPortal(
    <motion.div
      variants={backdropFade}
      initial="hidden"
      animate="visible"
      exit="exit"
      onClick={onClose}
      className={cn(
        'fixed inset-0 z-50 flex justify-center bg-black/70 backdrop-blur-sm p-4',
        sheetOnMobile ? 'items-end sm:items-center' : 'items-center',
      )}
    >
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        variants={sheetOnMobile ? sheetUp : dialogScale}
        onClick={e => e.stopPropagation()}
        className={cn(
          'w-full bg-surface-1 border border-line-strong rounded-lg overflow-hidden',
          'flex flex-col max-h-[92dvh] focus:outline-none',
          WIDTH[width],
          className,
        )}
      >
        {(title || !hideClose) && (
          <div className="flex items-start gap-3 px-5 py-4 border-b border-line shrink-0">
            <div className="flex-1 min-w-0">
              {title && (
                <h2 id={titleId} className="font-display text-base font-semibold text-ink-1 leading-tight">
                  {title}
                </h2>
              )}
              {description && (
                <p id={descId} className="text-xs text-ink-3 mt-1 leading-relaxed">
                  {description}
                </p>
              )}
            </div>
            {!hideClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Fechar"
                className="text-ink-4 hover:text-ink-1 transition-colors shrink-0 -mr-1 -mt-0.5 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
        <div className="overflow-y-auto overscroll-contain">{children}</div>
      </motion.div>
    </motion.div>,
    document.body,
  )
}

/**
 * Gaveta lateral. Mesmo comportamento do Modal, geometria de painel alto:
 * no desktop desliza da direita, no mobile ocupa a largura toda.
 */
export function Drawer({
  onClose,
  children,
  title,
  description,
  hideClose,
  className,
}: {
  onClose: () => void
  children: React.ReactNode
  title?: React.ReactNode
  description?: React.ReactNode
  hideClose?: boolean
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descId = useId()
  useDialogBehavior(onClose, ref)

  return createPortal(
    <motion.div
      variants={backdropFade}
      initial="hidden"
      animate="visible"
      exit="exit"
      onClick={onClose}
      className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm"
    >
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        variants={drawerRight}
        onClick={e => e.stopPropagation()}
        className={cn(
          'w-full sm:max-w-md h-full bg-surface-1 border-l border-line',
          'flex flex-col focus:outline-none',
          className,
        )}
      >
        {(title || !hideClose) && (
          <div className="flex items-start gap-3 px-5 py-4 border-b border-line shrink-0">
            <div className="flex-1 min-w-0">
              {title && (
                <h2 id={titleId} className="font-display text-base font-semibold text-ink-1 leading-tight">
                  {title}
                </h2>
              )}
              {description && (
                <p id={descId} className="text-xs text-ink-3 mt-1 leading-relaxed">
                  {description}
                </p>
              )}
            </div>
            {!hideClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Fechar"
                className="text-ink-4 hover:text-ink-1 transition-colors shrink-0 -mr-1 -mt-0.5 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
        <div className="flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </motion.div>
    </motion.div>,
    document.body,
  )
}

/** Rodapé fixo de diálogo, para as ações. Fica fora da área que rola. */
export function ModalFooter({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-2 px-5 py-4 border-t border-line shrink-0', className)}>
      {children}
    </div>
  )
}
