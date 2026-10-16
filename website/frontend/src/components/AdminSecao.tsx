import { useEffect, useRef, useState } from 'react'
import { ArrowDownRight } from 'lucide-react'

/*
 * As peças que organizam o /admin.
 *
 * SEM ABRE-E-FECHA (09/10/2026, pedido do usuário). Até aqui cada painel era
 * um acordeão, com "Abrir tudo / Fechar tudo" e o estado lembrado no
 * navegador. Na prática, quem opera passava mais tempo abrindo painel do que
 * lendo. Agora:
 *
 * Secao      um bloco sempre aberto. O título é a PERGUNTA que ele responde,
 *            em português de quem opera; o nome técnico vai pequeno ao lado.
 *            O CONTEÚDO só monta quando o bloco chega perto da tela -- o que
 *            antes o "fechado" garantia (painel que ninguém olhou não faz
 *            requisição) continua valendo, sem o clique.
 *
 * GuiaDaAba  uma linha no topo da aba: para que ela serve e um índice que
 *            leva direto a cada bloco.
 */

/*
 * Ação pequena do admin: "ver log", "por quê", "limpar filtro".
 * Ação tem cara de botão: borda e fundo que acende.
 */
export const BOTAO_PEQUENO =
  'inline-flex items-center justify-center gap-1 text-[11px] font-semibold px-2.5 py-1 min-h-[28px] ' +
  'rounded-md border border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4 hover:bg-surface-2 ' +
  'transition-colors touch-manipulation disabled:opacity-40 disabled:pointer-events-none'

const EVENTO_IR = 'admin:ir-para-secao'

/** Leva até uma seção (índice do guia, botão "Editar" de outra seção) e
 *  garante que o conteúdo dela já montou antes de rolar. O nome ficou o de
 *  quando ela abria o acordeão, porque é chamado de vários lugares. */
export function abrirSecao(id: string) {
  window.dispatchEvent(new CustomEvent(EVENTO_IR, { detail: id }))
  window.setTimeout(() => {
    document.getElementById(`secao-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 60)
}

interface SecaoProps {
  id: string
  /** A pergunta que o painel responde, em português simples. */
  titulo: string
  /** Uma frase: o que tem aqui dentro e quando olhar. */
  oQueE: string
  /** Nome técnico do painel, para quem procura pelo nome antigo. */
  tecnico?: string
  /** Monta o conteúdo já de cara, sem esperar o bloco chegar perto da tela.
   *  (Era "aberta por padrão" no tempo do acordeão.) */
  abertaPorPadrao?: boolean
  children: React.ReactNode
}

export function Secao({ id, titulo, oQueE, tecnico, abertaPorPadrao = false, children }: SecaoProps) {
  const [montado, setMontado] = useState(abertaPorPadrao)
  const ref = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (montado) return
    const ir = (e: Event) => { if ((e as CustomEvent).detail === id) setMontado(true) }
    window.addEventListener(EVENTO_IR, ir)
    let obs: IntersectionObserver | null = null
    if (typeof IntersectionObserver === 'undefined') {
      setMontado(true)
    } else if (ref.current) {
      obs = new IntersectionObserver(
        entradas => { if (entradas.some(e => e.isIntersecting)) setMontado(true) },
        { rootMargin: '600px 0px' })
      obs.observe(ref.current)
    }
    return () => {
      window.removeEventListener(EVENTO_IR, ir)
      obs?.disconnect()
    }
  }, [id, montado])

  return (
    <section id={`secao-${id}`} ref={ref} className="mb-6 scroll-mt-4">
      <header className="mb-2 px-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <h2 className="text-sm font-bold text-ink-1">{titulo}</h2>
          {tecnico && <span className="text-[10px] text-ink-4 font-mono">{tecnico}</span>}
        </div>
        <p className="text-[11px] text-ink-3 mt-0.5 leading-relaxed">{oQueE}</p>
      </header>
      {montado
        ? children
        : <div className="h-24 rounded-lg border border-line bg-surface-1/40 animate-pulse" aria-hidden />}
    </section>
  )
}

interface GuiaProps {
  aba: string
  /** Uma ou duas frases: para que a aba existe. */
  paraQue: string
  /** Situações concretas em que vale abrir a aba. */
  quando?: string[]
  secoes?: { id: string; titulo: string }[]
}

export function GuiaDaAba({ paraQue, quando = [], secoes = [] }: GuiaProps) {
  return (
    <div className="mb-5 px-1">
      <p className="text-[12px] text-ink-2 leading-relaxed">
        {paraQue}
        {quando.length > 0 && (
          <span className="text-ink-4"> Use quando: {quando.join('; ')}.</span>
        )}
      </p>
      {secoes.length > 1 && (
        <nav className="mt-2.5 flex flex-wrap gap-1.5" aria-label="Ir para">
          {secoes.map(s => (
            <button key={s.id} type="button" onClick={() => abrirSecao(s.id)}
              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-line text-ink-2 hover:text-ink-1 hover:border-line-strong hover:bg-surface-2 transition-colors touch-manipulation">
              <ArrowDownRight className="w-3 h-3 text-ink-4" aria-hidden />
              {s.titulo}
            </button>
          ))}
        </nav>
      )}
    </div>
  )
}
