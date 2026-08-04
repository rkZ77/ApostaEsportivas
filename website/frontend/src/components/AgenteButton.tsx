import { useState, useRef, useEffect, useCallback, lazy, Suspense } from 'react'
import { Spinner } from './ui'
import { useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Bot } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

// react-markdown (usado no painel) é pesado -- carrega só quando o usuário
// abre o chat, pra não engordar o bundle inicial de toda página.
const AgentePanel = lazy(() => import('./AgentePanel'))

const POS_KEY = 'agente_button_pos'
const DRAG_THRESHOLD = 6

interface Pos { x: number; y: number }

function PanelFallback() {
  return (
    <div
      style={{ bottom: 'calc(1.25rem + env(safe-area-inset-bottom))' }}
      className="fixed right-4 z-50 w-[calc(100vw-2rem)] max-w-sm h-[min(72vh,560px)] bg-surface-0 border border-line rounded-lg shadow-2xl shadow-black/60 flex items-center justify-center"
    >
      <Spinner />
    </div>
  )
}

/** Atalho flutuante pro Agente IA (substituiu o botão de WhatsApp) · abre um
 * chat compacto no canto em vez de navegar pra página /agente. Suporte humano
 * via WhatsApp continua acessível no menu do perfil e no Footer. */
export default function AgenteButton() {
  const location = useLocation()
  const { user } = useAuth()
  const [dismissed, setDismissed] = useState(false)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<Pos | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragState = useRef<{ startX: number; startY: number; origX: number; origY: number; moved: boolean } | null>(null)
  const wasDraggedRef = useRef(false)

  const clamp = useCallback((x: number, y: number): Pos => {
    const el = containerRef.current
    const w = el?.offsetWidth ?? 56
    const h = el?.offsetHeight ?? 120
    const maxX = Math.max(8, window.innerWidth - w - 8)
    const maxY = Math.max(8, window.innerHeight - h - 8)
    return { x: Math.min(Math.max(8, x), maxX), y: Math.min(Math.max(8, y), maxY) }
  }, [])

  // Restaura a última posição salva (e reajusta se a tela mudou de tamanho)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(POS_KEY)
      if (saved) setPos(clamp(JSON.parse(saved).x, JSON.parse(saved).y))
    } catch { /* ignora */ }
  }, [clamp])

  useEffect(() => {
    const onResize = () => setPos(p => (p ? clamp(p.x, p.y) : p))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [clamp])

  const onPointerDown = (e: React.PointerEvent) => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    dragState.current = { startX: e.clientX, startY: e.clientY, origX: rect.left, origY: rect.top, moved: false }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const ds = dragState.current
    if (!ds) return
    const dx = e.clientX - ds.startX
    const dy = e.clientY - ds.startY
    if (!ds.moved && Math.hypot(dx, dy) > DRAG_THRESHOLD) ds.moved = true
    if (ds.moved) setPos(clamp(ds.origX + dx, ds.origY + dy))
  }

  const onPointerUp = () => {
    const ds = dragState.current
    if (!ds) return
    wasDraggedRef.current = ds.moved
    dragState.current = null
    if (ds.moved) {
      setPos(curr => {
        if (curr) { try { localStorage.setItem(POS_KEY, JSON.stringify(curr)) } catch { /* ignora */ } }
        return curr
      })
    }
  }

  // Um arraste real não deve disparar o clique (abrir chat / fechar) do elemento solto
  const toggleOpen = () => {
    if (wasDraggedRef.current) {
      wasDraggedRef.current = false
      return
    }
    setOpen(o => !o)
  }

  // Só aparece pra quem já tem conta (visitante sem login não vê o atalho) e
  // some dentro da página /agente cheia -- nao faz sentido flutuar o mesmo chat por cima dela
  if (!user || location.pathname.startsWith('/agente')) return null

  const style: React.CSSProperties = pos
    ? { left: pos.x, top: pos.y }
    : { bottom: 'calc(1.25rem + env(safe-area-inset-bottom))' }

  return (
    <>
      <AnimatePresence>
        {open && (
          <Suspense fallback={<PanelFallback />}>
            <AgentePanel onClose={() => setOpen(false)} />
          </Suspense>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {!dismissed && !open && (
          <motion.div
            style={style}
            initial={{ opacity: 0, scale: 0.7 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.7, transition: { duration: 0.15 } }}
            transition={{ type: 'spring', stiffness: 400, damping: 26, delay: 0.3 }}
            className={`fixed ${pos ? '' : 'right-4'} z-50`}
          >
            <div
              ref={containerRef}
              className="flex flex-col items-end gap-1.5 touch-none select-none cursor-grab active:cursor-grabbing"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            >
              {/* X separado acima do botão */}
              <button
                onClick={e => { e.stopPropagation(); if (wasDraggedRef.current) { wasDraggedRef.current = false; return }; setDismissed(true) }}
                aria-label="Fechar atalho do Agente IA"
                className="w-9 h-9 flex items-center justify-center rounded-full bg-surface-2 border border-line-strong hover:bg-surface-3 text-ink-2 text-base font-black transition-colors shadow"
              >
                ×
              </button>

              <button
                onClick={toggleOpen}
                draggable={false}
                onDragStart={e => e.preventDefault()}
                aria-label="Conversar com o Agente IA"
                className="flex items-center gap-2 bg-green-500 hover:bg-green-400 active:bg-green-600 text-black font-bold shadow-lg shadow-black/40 transition-all hover:scale-105 active:scale-95 rounded-full px-3 py-3 sm:px-4 sm:py-3"
              >
                <Bot className="w-6 h-6 shrink-0" />
                <span className="hidden sm:inline text-sm">Agente IA</span>
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
