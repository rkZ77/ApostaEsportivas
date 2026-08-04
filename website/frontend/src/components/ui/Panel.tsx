import { cn } from '../../lib/cn'

/*
 * Bloco delineado. É o desenho de referência do sistema: o fundo do painel é o
 * mesmo da página e quem define o bloco é a BORDA, não o preenchimento. É isso
 * que dá o ar de terminal em vez de cartão empilhado.
 *
 * Usar Panel para dado (lista, tabela, gráfico, placar) e Card para conteúdo
 * (texto, oferta, chamada).
 */

export default function Panel({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return <div className={cn('panel', className)}>{children}</div>
}

/** Cabeçalho do painel: rótulo em versalete à esquerda, meta discreta à direita. */
export function PanelHead({
  label,
  meta,
  children,
  className,
}: {
  label: React.ReactNode
  /** Contagem, data, unidade. Texto miúdo alinhado à direita. */
  meta?: React.ReactNode
  /** Ação (botão, filtro). Entra depois do meta. */
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('panel-head', className)}>
      <span className="panel-label">{label}</span>
      <div className="flex items-center gap-3 min-w-0">
        {meta != null && <span className="panel-meta">{meta}</span>}
        {children}
      </div>
    </div>
  )
}

/** Linha de painel. Vira botão quando recebe onClick, com estado de hover. */
export function PanelRow({
  children,
  onClick,
  className,
}: {
  children: React.ReactNode
  onClick?: () => void
  className?: string
}) {
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'panel-row w-full text-left hover:bg-surface-1/60 transition-colors duration-1 ease-smooth',
          className,
        )}
      >
        {children}
      </button>
    )
  }
  return <div className={cn('panel-row', className)}>{children}</div>
}

/** Corpo com divisores entre as linhas, no tom certo de linha fina. */
export function PanelList({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return <div className={cn('divide-y divide-line/50', className)}>{children}</div>
}
