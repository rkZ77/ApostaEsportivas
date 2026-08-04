import { useId } from 'react'
import { ChevronDown, Search, type LucideIcon } from 'lucide-react'
import { cn } from '../../lib/cn'

/*
 * Campos de formulário. Sempre com <label> ligado por id: metade dos inputs do
 * site se apoiava só no placeholder, que some assim que o usuário digita e não
 * é lido como rótulo por leitor de tela.
 *
 * O erro entra por aria-describedby, não só em vermelho, pra ser anunciado.
 */

function FieldShell({
  id,
  label,
  hint,
  error,
  required,
  className,
  children,
}: {
  id: string
  label?: React.ReactNode
  hint?: React.ReactNode
  error?: string | null
  required?: boolean
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('w-full', className)}>
      {label != null && (
        <label htmlFor={id} className="block text-xs font-semibold text-ink-2 mb-1.5">
          {label}
          {required && <span className="text-ink-4 font-normal"> (obrigatório)</span>}
        </label>
      )}
      {children}
      {error
        ? <p id={`${id}-msg`} role="alert" className="text-[11px] text-red-400 mt-1.5">{error}</p>
        : hint != null && <p id={`${id}-msg`} className="text-[11px] text-ink-4 mt-1.5">{hint}</p>}
    </div>
  )
}

export function Input({
  label,
  hint,
  error,
  Icon,
  className,
  inputClassName,
  required,
  ...props
}: {
  label?: React.ReactNode
  hint?: React.ReactNode
  error?: string | null
  Icon?: LucideIcon
  className?: string
  inputClassName?: string
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId()
  const id = props.id ?? auto

  return (
    <FieldShell id={id} label={label} hint={hint} error={error} required={required} className={className}>
      <div className="relative">
        {Icon && (
          <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-4 pointer-events-none" />
        )}
        <input
          {...props}
          id={id}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? `${id}-msg` : undefined}
          className={cn(
            'input',
            Icon && 'pl-9',
            error && 'border-red-500/60 focus:border-red-500 focus:ring-red-500/30',
            inputClassName,
          )}
        />
      </div>
    </FieldShell>
  )
}

/** Busca. Input com lupa, tipo search pra ganhar o botão de limpar do browser. */
export function SearchInput({
  value,
  onChange,
  placeholder = 'Buscar',
  className,
  label,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  /** Some da tela mas continua sendo lido. Busca raramente mostra rótulo. */
  label?: string
}) {
  const id = useId()
  return (
    <div className={cn('relative', className)}>
      <label htmlFor={id} className="sr-only">{label ?? placeholder}</label>
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-4 pointer-events-none" />
      <input
        id={id}
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="input pl-9 py-2.5 text-sm"
      />
    </div>
  )
}

export function Select({
  label,
  hint,
  error,
  options,
  className,
  required,
  ...props
}: {
  label?: React.ReactNode
  hint?: React.ReactNode
  error?: string | null
  options: Array<{ value: string; label: string; disabled?: boolean }>
  className?: string
} & React.SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId()
  const id = props.id ?? auto

  return (
    <FieldShell id={id} label={label} hint={hint} error={error} required={required} className={className}>
      <div className="relative">
        <select
          {...props}
          id={id}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? `${id}-msg` : undefined}
          className={cn(
            'input appearance-none pr-9 cursor-pointer',
            error && 'border-red-500/60 focus:border-red-500 focus:ring-red-500/30',
          )}
        >
          {options.map(o => (
            <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
          ))}
        </select>
        <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-4 pointer-events-none" />
      </div>
    </FieldShell>
  )
}

export function Textarea({
  label,
  hint,
  error,
  className,
  required,
  ...props
}: {
  label?: React.ReactNode
  hint?: React.ReactNode
  error?: string | null
  className?: string
} & React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId()
  const id = props.id ?? auto

  return (
    <FieldShell id={id} label={label} hint={hint} error={error} required={required} className={className}>
      <textarea
        {...props}
        id={id}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${id}-msg` : undefined}
        className={cn(
          'input resize-y min-h-[96px]',
          error && 'border-red-500/60 focus:border-red-500 focus:ring-red-500/30',
        )}
      />
    </FieldShell>
  )
}
