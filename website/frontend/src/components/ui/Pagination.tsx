import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '../../lib/cn'

/*
 * Paginação. O padrão "Ant / 1 de 7 / Próx" já estava em Resultados, Banca,
 * MeusPicks e Alavancagem, copiado à mão em cada um, com contagem de páginas
 * recalculada de forma ligeiramente diferente em cada cópia.
 *
 * Recebe total de itens, não total de páginas: era aí que as cópias divergiam,
 * porque metade arredondava com Math.ceil e metade comparava offset com total.
 */

export default function Pagination({
  page,
  pageSize,
  total,
  onChange,
  className,
  /** Rótulo do que está sendo paginado, para o texto de contexto. */
  unit = 'resultados',
}: {
  /** Base zero, igual ao offset usado nas chamadas de API. */
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
  className?: string
  unit?: string
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null

  const first = page * pageSize + 1
  const last = Math.min(total, (page + 1) * pageSize)

  return (
    <nav
      aria-label="Paginação"
      className={cn('flex items-center justify-between gap-3 py-4 px-4 border-t border-line/50', className)}
    >
      <span className="text-[11px] text-ink-4 tabular-nums hidden sm:block">
        {first} a {last} de {total} {unit}
      </span>

      <div className="flex items-center gap-1 mx-auto sm:mx-0">
        <button
          type="button"
          disabled={page === 0}
          onClick={() => onChange(page - 1)}
          aria-label="Página anterior"
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 disabled:opacity-30 disabled:pointer-events-none transition-colors duration-1 ease-smooth"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          Ant
        </button>

        <span className="font-mono text-xs text-ink-3 px-3 tabular-nums" aria-current="page">
          {page + 1} / {pages}
        </span>

        <button
          type="button"
          disabled={page + 1 >= pages}
          onClick={() => onChange(page + 1)}
          aria-label="Próxima página"
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 disabled:opacity-30 disabled:pointer-events-none transition-colors duration-1 ease-smooth"
        >
          Próx
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </nav>
  )
}
