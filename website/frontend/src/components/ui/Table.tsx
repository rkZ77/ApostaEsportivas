import { cn } from '../../lib/cn'

/*
 * Tabela. Números em mono e tabular pra coluna alinhar, cabeçalho em versalete,
 * e o container rolando por conta própria: sem o overflow-x-auto aqui, uma
 * tabela larga empurrava a página inteira no mobile e o body ganhava scroll
 * horizontal.
 */

export interface Column<T> {
  key: string
  header: React.ReactNode
  /** Célula. Recebe a linha inteira. */
  cell: (row: T) => React.ReactNode
  align?: 'left' | 'right' | 'center'
  /** Esconde abaixo de sm. Para coluna acessória em tela estreita. */
  hideOnMobile?: boolean
  className?: string
}

export default function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  className,
  minWidth = 460,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T, i: number) => string
  onRowClick?: (row: T) => void
  className?: string
  /** Abaixo disso a tabela rola em vez de espremer. */
  minWidth?: number
}) {
  const alignCls = { left: 'text-left', right: 'text-right', center: 'text-center' }

  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full text-sm" style={{ minWidth }}>
        <thead>
          <tr className="border-b border-line">
            {columns.map(c => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  'label-micro font-medium px-3 sm:px-5 py-3 normal-case tracking-wide',
                  alignCls[c.align ?? 'left'],
                  c.hideOnMobile && 'hidden sm:table-cell',
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(
                'border-b border-line/50 transition-colors duration-1 ease-smooth',
                onRowClick && 'hover:bg-surface-1/60 cursor-pointer',
              )}
            >
              {columns.map(c => (
                <td
                  key={c.key}
                  className={cn(
                    'px-3 sm:px-5 py-3 text-ink-2',
                    alignCls[c.align ?? 'left'],
                    c.hideOnMobile && 'hidden sm:table-cell',
                    c.className,
                  )}
                >
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
