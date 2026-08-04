import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/cn'
import Button, { type ButtonProps } from './Button'

/*
 * Estado vazio. Antes existiam ~34 versões soltas disso, cada uma com um
 * padding, um tamanho de texto e um tom diferente, e boa parte era só um
 * <p> cinza no meio do nada sem dizer o que fazer em seguida.
 *
 * A regra aqui: sempre dizer o que está vazio, por quê, e qual é o próximo
 * passo quando existir um.
 */

export default function EmptyState({
  Icon,
  title,
  description,
  action,
  secondary,
  className,
  compact,
}: {
  Icon?: LucideIcon
  title: React.ReactNode
  description?: React.ReactNode
  /** Ação principal. Recebe as props do Button. */
  action?: ButtonProps
  /** Ação secundária, em link discreto. */
  secondary?: ButtonProps
  className?: string
  /** Menos respiro. Para dentro de painel ou aba, não para página inteira. */
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center text-center px-5',
        compact ? 'py-10' : 'py-16',
        className,
      )}
    >
      {Icon && (
        <div className="w-11 h-11 rounded-lg border border-line flex items-center justify-center mb-4">
          <Icon className="w-5 h-5 text-ink-4" />
        </div>
      )}
      <p className="text-sm font-semibold text-ink-2">{title}</p>
      {description != null && (
        <p className="text-xs text-ink-3 mt-1.5 max-w-sm leading-relaxed">{description}</p>
      )}
      {(action || secondary) && (
        <div className="flex flex-wrap items-center justify-center gap-3 mt-5">
          {action && <Button size="sm" {...action} />}
          {secondary && <Button size="sm" variant="link" {...secondary} />}
        </div>
      )}
    </div>
  )
}

/**
 * Estado de erro de carregamento. Mesma casca do vazio, mas com tom de falha
 * e ação de tentar de novo, porque "não carregou" e "não existe" são coisas
 * diferentes e o usuário precisa saber qual das duas aconteceu.
 */
export function ErrorState({
  title = 'Não foi possível carregar agora',
  description = 'Pode ser instabilidade momentânea. Tente novamente em instantes.',
  onRetry,
  className,
  compact,
}: {
  title?: React.ReactNode
  description?: React.ReactNode
  onRetry?: () => void
  className?: string
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center text-center px-5',
        compact ? 'py-10' : 'py-16',
        className,
      )}
    >
      <p className="text-sm font-semibold text-ink-2">{title}</p>
      <p className="text-xs text-ink-3 mt-1.5 max-w-sm leading-relaxed">{description}</p>
      {onRetry && (
        <Button size="sm" variant="ghost" onClick={onRetry} className="mt-5">
          Tentar de novo
        </Button>
      )}
    </div>
  )
}
