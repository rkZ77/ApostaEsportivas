import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
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
 *
 * O hover só é ligado em quem realmente tem cursor. No celular o navegador
 * dispara `mouseenter` sintético ANTES do `click` do mesmo toque: o mouseenter
 * abria a dica e o clique, achando que ela já estava aberta, fechava de volta.
 * O resultado era a dica piscando e sumindo · lida como "não funciona", que
 * foi exatamente a queixa. Em toque, só o clique manda.
 *
 * O DESLOCAMENTO PARA CIMA VIVE NUM WRAPPER, NÃO NO ELEMENTO ANIMADO.
 *
 * A versão anterior punha `transform: translateY(-100%)` no `style` do próprio
 * motion.div. Só que framer-motion ESCREVE a propriedade `transform` inteira
 * para animar a escala do `popIn`, e no primeiro quadro já apagava o
 * translate: a dica nascia colada no topo do gatilho e cobria o que estava
 * explicando, em vez de ficar acima dele. Medido em 15/08/2026: gatilho em
 * y=651, dica renderizada em y=649 com 101px de altura, quando deveria começar
 * em y=542. Quanto mais embaixo o gatilho, mais a dica saía da tela.
 *
 * Aqui o wrapper posiciona (transform que ninguém anima) e o filho anima. E o
 * lado é decidido MEDINDO a dica: sem espaço acima, ela abre para baixo, em vez
 * de vazar pelo topo da janela.
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
  const [ancora, setAncora] = useState<{ top: number; bottom: number; left: number } | null>(null)
  const [lado, setLado] = useState<'acima' | 'abaixo'>('acima')
  const [altura, setAltura] = useState(0)
  const [temCursor, setTemCursor] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const id = useId()

  useEffect(() => {
    const mq = window.matchMedia('(hover: hover) and (pointer: fine)')
    const ler = () => setTemCursor(mq.matches)
    ler()
    mq.addEventListener('change', ler)
    return () => mq.removeEventListener('change', ler)
  }, [])

  const place = () => {
    const el = ref.current?.firstElementChild ?? ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const left = Math.max(
      8,
      Math.min(r.left + r.width / 2 - TIP_WIDTH / 2, window.innerWidth - TIP_WIDTH - 8),
    )
    setAncora({ top: r.top, bottom: r.bottom, left })
    setLado('acima')
  }

  /* Mede a dica já renderizada e decide o lado · a altura depende do texto, e
     estes vão de uma linha a cinco. Roda em useLayoutEffect, antes da pintura,
     então o reposicionamento não pisca. */
  useLayoutEffect(() => {
    if (!open || !ancora || !tipRef.current) return
    const h = tipRef.current.offsetHeight
    if (h !== altura) setAltura(h)
    setLado(ancora.top - 8 - h < 8 ? 'abaixo' : 'acima')
  }, [open, ancora, altura, text])

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
    // Foco continua sempre ligado: é por ele que se chega aqui pelo teclado,
    // em qualquer aparelho.
    onFocus: show,
    onBlur: hide,
    ...(temCursor ? { onMouseEnter: show, onMouseLeave: hide } : null),
  })

  return (
    <span ref={ref} className={className ? `inline-flex ${className}` : 'inline-flex'}>
      {trigger}
      {createPortal(
        <AnimatePresence>
          {open && ancora && (
            <motion.div
              ref={tipRef}
              id={id}
              role="tooltip"
              variants={popIn}
              initial="hidden"
              animate="visible"
              exit="exit"
              onClick={e => e.stopPropagation()}
              style={{
                position: 'fixed',
                // O deslocamento vai no `top`, com a altura medida, e NÃO num
                // translateY: framer-motion reescreve a propriedade `transform`
                // inteira pra animar a escala do popIn, e apagava o translate
                // já no primeiro quadro.
                top: lado === 'acima' ? ancora.top - 8 - altura : ancora.bottom + 8,
                left: ancora.left,
                width: TIP_WIDTH,
                transformOrigin: lado === 'acima' ? 'bottom center' : 'top center',
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
