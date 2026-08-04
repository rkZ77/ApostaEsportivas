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
