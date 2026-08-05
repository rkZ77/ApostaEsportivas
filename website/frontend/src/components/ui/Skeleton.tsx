import { cn } from '../../lib/cn'

/**
 * Placeholder de carregamento. Usa surface-2 (não surface-1) de propósito:
 * dentro de um .card, que já é surface-1, um skeleton em surface-1 sumiria.
 */
export default function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn('animate-pulse rounded-md bg-surface-2', className)}
    />
  )
}

/** Linhas de texto falsas. A última sai mais curta, como parágrafo de verdade. */
export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number
  className?: string
}) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn('h-3', i === lines - 1 && lines > 1 && 'w-2/3')}
        />
      ))}
    </div>
  )
}

/** Casca de card em carregamento, no mesmo desenho do .card real. */
export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn('card p-5', className)}>
      <Skeleton className="h-3 w-24 mb-4" />
      <SkeletonText lines={2} />
    </div>
  )
}

/*
 * Card de pick em carregamento, na MESMA anatomia do .pick-card real:
 * cabeçalho, tira de números dividida, times, e rodapé de ações.
 *
 * Existe pra tela não saltar quando o dado chega. Um spinner centralizado
 * ocupa uma caixa de altura arbitrária e, ao virar grade de cards, empurra
 * tudo que está abaixo · o esqueleto já nasce do tamanho certo, então o
 * conteúdo só preenche o que já estava reservado.
 */
export function SkeletonPickCard() {
  return (
    <div className="pick-card">
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-3 w-16" />
        </div>
        <Skeleton className="h-4 w-16" />
      </div>

      <div className="flex items-stretch divide-x divide-line/60 border-b border-line/60">
        {[0, 1, 2].map(i => (
          <div key={i} className="flex-1 px-4 py-3 flex flex-col items-center gap-1.5">
            <Skeleton className="h-2 w-8" />
            <Skeleton className="h-6 w-14" />
          </div>
        ))}
      </div>

      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-5 rounded-full shrink-0" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-5 w-5 rounded-full shrink-0" />
        </div>
        <Skeleton className="h-2.5 w-2/5" />
      </div>

      <div className="px-5 pb-3">
        <SkeletonText lines={2} />
      </div>

      <div className="flex items-center gap-2 px-5 py-3 border-t border-line/60">
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-8 w-8 ml-auto rounded-md" />
      </div>
    </div>
  )
}

/** Grade de picks em carregamento, no mesmo `md:grid-cols-2` da lista real. */
export function SkeletonPickGrid({ cards = 2 }: { cards?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Array.from({ length: cards }).map((_, i) => <SkeletonPickCard key={i} />)}
    </div>
  )
}

/** Lista de linhas em carregamento, no desenho do .panel. */
export function SkeletonRows({
  rows = 5,
  className,
}: {
  rows?: number
  className?: string
}) {
  return (
    <div className={cn('divide-y divide-line/50', className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3">
          <Skeleton className="h-3 w-10 shrink-0" />
          <Skeleton className="h-4 w-4 rounded-full shrink-0" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-10 shrink-0" />
        </div>
      ))}
    </div>
  )
}
