import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '../../lib/cn'

/*
 * Paginação. O padrão "Ant / 1 de 7 / Próx" já estava em Resultados, Banca,
 * MeusPicks e Alavancagem, copiado à mão em cada um, com contagem de páginas
 * recalculada de forma ligeiramente diferente em cada cópia.
 *
 * Recebe total de itens, não total de páginas: era aí que as cópias divergiam,
 * porque metade arredondava com Math.ceil e metade comparava offset com total.
 *
 * DOIS DESENHOS, UM POR TELA (2026-10-06).
 *
 *   celular     "‹ Anterior · 3 de 12 · Próxima ›", botões largos e altos.
 *               Os antigos tinham 28px de altura e a palavra "Ant", que é
 *               alvo de toque pequeno e rótulo que ninguém lê como "anterior".
 *   computador  os números das páginas, com reticências quando são muitas
 *               (1 … 4 5 6 … 30). Com 30 páginas, chegar na última pelo
 *               "Próx" eram 29 cliques.
 *
 * `disabled` existe pra quem pagina pelo servidor: durante o carregamento o
 * clique seguinte pediria a página errada.
 */

type Item = number | 'gap'

/** Páginas a mostrar (base zero), com no máximo uma reticência de cada lado. */
function janela(page: number, pages: number): Item[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i)
  const ini = Math.max(1, Math.min(page - 1, pages - 5))
  const fim = Math.min(pages - 2, Math.max(page + 1, 4))
  const meio = Array.from({ length: fim - ini + 1 }, (_, i) => ini + i)
  return [
    0,
    ...(ini > 1 ? ['gap' as const] : []),
    ...meio,
    ...(fim < pages - 2 ? ['gap' as const] : []),
    pages - 1,
  ]
}

const BASE = 'inline-flex items-center justify-center rounded-md border text-xs font-semibold tabular-nums ' +
  'transition-colors duration-1 ease-smooth touch-manipulation disabled:opacity-30 disabled:pointer-events-none'
const NEUTRO = 'border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 hover:bg-surface-2'

export default function Pagination({
  page,
  pageSize,
  total,
  onChange,
  className,
  disabled = false,
  /** Rótulo do que está sendo paginado, para o texto de contexto. */
  unit = 'resultados',
}: {
  /** Base zero, igual ao offset usado nas chamadas de API. */
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
  className?: string
  disabled?: boolean
  unit?: string
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null

  const atual = Math.min(Math.max(0, page), pages - 1)
  const first = atual * pageSize + 1
  const last = Math.min(total, (atual + 1) * pageSize)
  const ir = (p: number) => { if (!disabled && p !== atual && p >= 0 && p < pages) onChange(p) }

  return (
    <nav
      aria-label="Paginação"
      className={cn('py-3 px-4 border-t border-line/50', className)}
    >
      {/* Celular */}
      <div className="flex items-center gap-2 sm:hidden">
        <button type="button" disabled={disabled || atual === 0} onClick={() => ir(atual - 1)}
          aria-label="Página anterior" className={cn(BASE, NEUTRO, 'flex-1 gap-1 min-h-[44px] px-3')}>
          <ChevronLeft className="w-4 h-4" /> Anterior
        </button>
        <span className="text-xs text-ink-3 tabular-nums px-2 text-center shrink-0" aria-current="page">
          <span className="text-ink-1 font-semibold">{atual + 1}</span> de {pages}
        </span>
        <button type="button" disabled={disabled || atual + 1 >= pages} onClick={() => ir(atual + 1)}
          aria-label="Próxima página" className={cn(BASE, NEUTRO, 'flex-1 gap-1 min-h-[44px] px-3')}>
          Próxima <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Computador */}
      <div className="hidden sm:flex items-center justify-between gap-3">
        <span className="text-[11px] text-ink-4 tabular-nums">
          {first}–{last} de {total.toLocaleString('pt-BR')} {unit}
        </span>
        <div className="flex items-center gap-1">
          <button type="button" disabled={disabled || atual === 0} onClick={() => ir(atual - 1)}
            aria-label="Página anterior" className={cn(BASE, NEUTRO, 'h-8 w-8')}>
            <ChevronLeft className="w-4 h-4" />
          </button>
          {janela(atual, pages).map((it, i) => it === 'gap' ? (
            <span key={`gap-${i}`} className="w-6 text-center text-xs text-ink-4" aria-hidden>…</span>
          ) : (
            <button key={it} type="button" disabled={disabled} onClick={() => ir(it)}
              aria-label={`Página ${it + 1}`}
              aria-current={it === atual ? 'page' : undefined}
              className={cn(BASE, 'h-8 min-w-8 px-2',
                it === atual
                  ? 'border-accent/50 bg-accent/10 text-accent-ink pointer-events-none'
                  : NEUTRO)}>
              {it + 1}
            </button>
          ))}
          <button type="button" disabled={disabled || atual + 1 >= pages} onClick={() => ir(atual + 1)}
            aria-label="Próxima página" className={cn(BASE, NEUTRO, 'h-8 w-8')}>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </nav>
  )
}
