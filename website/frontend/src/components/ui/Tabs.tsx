import { cn } from '../../lib/cn'

/*
 * Barra de abas. Carrega a semântica de estado (cor + sublinhado) das classes
 * .tab/.tab-active e adiciona o que faltava em toda cópia manual: papel ARIA,
 * navegação por seta e o scroll horizontal com máscara no mobile, onde 4 abas
 * não cabem na largura da tela.
 */

export interface TabItem<T extends string> {
  key: T
  label: React.ReactNode
  /** Contagem à direita do rótulo. */
  count?: number
  /** Ponto de novidade. */
  dot?: boolean
  disabled?: boolean
}

export default function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
  /** Aba de página (mais respiro) ou de modal (mais apertada). */
  density = 'page',
}: {
  items: TabItem<T>[]
  value: T
  onChange: (key: T) => void
  className?: string
  density?: 'page' | 'compact'
}) {
  const pad = density === 'page' ? 'px-5 py-3 text-sm' : 'px-3 py-2 text-xs'

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const usable = items.filter(i => !i.disabled)
    const at = usable.findIndex(i => i.key === value)
    const step = e.key === 'ArrowRight' ? 1 : -1
    const next = usable[(at + step + usable.length) % usable.length]
    if (next) onChange(next.key)
  }

  return (
    <div
      role="tablist"
      onKeyDown={onKeyDown}
      className={cn(
        'flex border-b border-line overflow-x-auto scrollbar-none',
        '[mask-image:linear-gradient(90deg,black_calc(100%-24px),transparent)] sm:[mask-image:none]',
        className,
      )}
    >
      {items.map(({ key, label, count, dot, disabled }) => (
        <button
          key={key}
          role="tab"
          type="button"
          aria-selected={value === key}
          disabled={disabled}
          onClick={() => onChange(key)}
          tabIndex={value === key ? 0 : -1}
          className={cn(
            'tab relative flex items-center gap-1.5 font-semibold shrink-0',
            pad,
            value === key && 'tab-active',
            disabled && 'opacity-40 pointer-events-none',
          )}
        >
          {label}
          {count != null && (
            <span className="font-mono text-[10px] text-ink-4 tabular-nums">{count}</span>
          )}
          {dot && <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />}
        </button>
      ))}
    </div>
  )
}

/** Filtro em pílula. O outro padrão de seleção do site, para recortes de lista. */
export function PillGroup<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: Array<{ value: T; label: React.ReactNode }>
  value: T
  onChange: (v: T) => void
  className?: string
}) {
  return (
    <div className={cn('flex gap-2 flex-wrap', className)}>
      {options.map(o => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn('pill', value === o.value && 'pill-active')}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
