import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '../../lib/cn'

/*
 * FAIXA QUE ROLA DE LADO, COM SETAS (16/10/2026, pedido do usuário: "não
 * consigo ir pro lado ali em cima pra trocar de liga").
 *
 * No celular o dedo arrasta e pronto. No computador, sem barra de rolagem
 * (escondida, de propósito) e com a roda do mouse rolando a página, não havia
 * como chegar no que estava fora da tela. As setas aparecem só com ponteiro
 * fino (mouse) e só do lado em que ainda tem coisa escondida; a borda daquele
 * lado ganha um degradê, pra se ver que a faixa continua.
 */
export default function FaixaRolavel({ children, className, rotulo, foco }: {
  children: ReactNode
  /** Classes da faixa em si (gap, margens negativas do celular...). */
  className?: string
  /** Nome pra leitor de tela ("Ligas", "Número do ranking"). */
  rotulo: string
  /** Muda quando o item escolhido muda: a faixa centraliza o aria-pressed. */
  foco?: unknown
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [podeVoltar, setPodeVoltar] = useState(false)
  const [podeAvancar, setPodeAvancar] = useState(false)

  const medir = useCallback(() => {
    const el = ref.current
    if (!el) return
    setPodeVoltar(el.scrollLeft > 4)
    setPodeAvancar(el.scrollLeft + el.clientWidth < el.scrollWidth - 4)
  }, [])

  useEffect(() => {
    medir()
    const el = ref.current
    if (!el) return
    const obs = new ResizeObserver(medir)
    obs.observe(el)
    return () => obs.disconnect()
  }, [medir, children])

  // O escolhido sempre à vista, mesmo quando é o 15º da faixa. Só rola a
  // faixa: scrollIntoView rolaria a página inteira junto.
  useEffect(() => {
    const el = ref.current
    const item = el?.querySelector<HTMLElement>('[aria-pressed="true"]')
    if (!el || !item) return
    const alvo = item.offsetLeft - (el.clientWidth - item.offsetWidth) / 2
    el.scrollTo({ left: Math.max(0, alvo), behavior: 'smooth' })
  }, [foco])

  const rolar = (lado: 1 | -1) => {
    const el = ref.current
    if (el) el.scrollBy({ left: lado * el.clientWidth * 0.8, behavior: 'smooth' })
  }

  return (
    <div className="relative" role="group" aria-label={rotulo}>
      <div ref={ref} onScroll={medir}
        // `relative`: o offsetLeft dos itens passa a ser medido a partir da faixa.
        className={cn('relative flex overflow-x-auto scrollbar-none overscroll-x-contain', className)}>
        {children}
      </div>
      {([[-1, podeVoltar], [1, podeAvancar]] as const).map(([lado, visivel]) => visivel && (
        <div key={lado} className={cn(
          // Mouse E tela larga: celular e tablet arrastam com o dedo.
          'pointer-events-none absolute inset-y-0 hidden sm:[@media(pointer:fine)]:flex items-center w-16',
          lado < 0 ? 'left-0 justify-start bg-gradient-to-r' : 'right-0 justify-end bg-gradient-to-l',
          'from-surface-0 via-surface-0/80 to-transparent')}>
          <button type="button" onClick={() => rolar(lado)}
            aria-label={lado < 0 ? 'Ver anteriores' : 'Ver mais'}
            className="pointer-events-auto w-9 h-9 rounded-full border border-line-strong bg-surface-2 text-ink-1 text-lg leading-none flex items-center justify-center shadow hover:bg-surface-3 transition-colors">
            {lado < 0 ? '‹' : '›'}
          </button>
        </div>
      ))}
    </div>
  )
}
