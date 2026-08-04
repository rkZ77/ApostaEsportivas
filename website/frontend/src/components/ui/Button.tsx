import { forwardRef } from 'react'
import { Link } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/cn'
import Spinner from './Spinner'

/*
 * Botão do sistema.
 *
 * Variante e tamanho são eixos separados de propósito. As classes antigas
 * (.btn-primary, .btn-ghost, .btn-subtle) misturavam os dois: primary vinha
 * com px-6 py-3 e ghost com px-4 py-2, então trocar de variante mudava a
 * altura do botão e duas ações lado a lado nunca alinhavam.
 */

const VARIANT = {
  /** Ação principal da tela. Uma por vista. */
  primary: 'bg-accent hover:bg-accent-hover active:bg-accent-press text-black font-bold',
  /** Ação secundária. Delineada, sem preenchimento, como o resto do sistema. */
  ghost: 'border border-line-strong hover:border-ink-4 text-ink-2 hover:text-ink-1 font-medium',
  /** Ação terciária dentro de superfície já elevada (modal, painel). */
  subtle: 'bg-surface-2 hover:bg-surface-3 text-ink-2 hover:text-ink-1 font-medium',
  /** Destrutiva. Só borda: preenchimento vermelho grita alto demais aqui. */
  danger: 'border border-red-500/40 hover:border-red-500/70 hover:bg-red-500/10 text-red-400 font-semibold',
  /** VIP. Mesma convenção de cor do badge-vip. */
  vip: 'bg-yellow-400/10 border border-yellow-400/30 hover:bg-yellow-400/20 text-yellow-400 font-bold',
  /** Parece link, comporta como botão. */
  link: 'text-ink-2 hover:text-ink-1 font-medium underline-offset-4 hover:underline',
} as const

/*
 * min-h existe por causa de dedo, não de estética.
 *
 * `sm` dava 28px de altura, e o público do site é majoritariamente mobile:
 * botão de ação abaixo de ~36px erra o toque com frequência. `md` e `lg`
 * ficam em 44px, que é o alvo recomendado pra ação principal.
 */
const SIZE = {
  sm: 'text-xs px-3 py-2 gap-1.5 rounded-md min-h-[36px]',
  md: 'text-sm px-4 py-2.5 gap-2 rounded-md min-h-[44px]',
  lg: 'text-sm px-7 py-3.5 gap-2 rounded-md min-h-[48px]',
} as const

const ICON_SIZE = { sm: 'w-3.5 h-3.5', md: 'w-4 h-4', lg: 'w-4 h-4' } as const

export interface ButtonProps {
  variant?: keyof typeof VARIANT
  size?: keyof typeof SIZE
  /** Ocupa a largura toda do container. */
  block?: boolean
  /** Troca o conteúdo por spinner e trava o clique. */
  loading?: boolean
  disabled?: boolean
  Icon?: LucideIcon
  /** Ícone à direita, para "avançar", "abrir", "ver mais". */
  IconRight?: LucideIcon
  children?: React.ReactNode
  className?: string
  /** Rota interna. Renderiza <Link>. */
  to?: string
  /** URL externa. Renderiza <a> com rel de segurança. */
  href?: string
  type?: 'button' | 'submit' | 'reset'
  onClick?: (e: React.MouseEvent) => void
  'aria-label'?: string
  title?: string
}

const Button = forwardRef<HTMLElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    block,
    loading,
    disabled,
    Icon,
    IconRight,
    children,
    className,
    to,
    href,
    type = 'button',
    onClick,
    ...rest
  },
  ref,
) {
  const isOff = disabled || loading

  const classes = cn(
    'inline-flex items-center justify-center whitespace-nowrap transition-colors duration-1 ease-smooth',
    VARIANT[variant],
    SIZE[size],
    block && 'w-full',
    isOff && 'opacity-40 pointer-events-none',
    className,
  )

  const inner = (
    <>
      {loading
        ? <Spinner size="sm" className="border-current border-t-transparent" />
        : Icon && <Icon className={cn(ICON_SIZE[size], 'shrink-0')} />}
      {children}
      {IconRight && !loading && <IconRight className={cn(ICON_SIZE[size], 'shrink-0')} />}
    </>
  )

  // Link desabilitado continua navegável por teclado se só apagarmos o ponteiro,
  // então aqui ele vira <span> de verdade em vez de âncora morta.
  if (isOff && (to || href)) {
    return <span className={classes} aria-disabled="true" {...rest}>{inner}</span>
  }

  if (to) {
    return (
      <Link ref={ref as React.Ref<HTMLAnchorElement>} to={to} onClick={onClick} className={classes} {...rest}>
        {inner}
      </Link>
    )
  }

  if (href) {
    return (
      <a
        ref={ref as React.Ref<HTMLAnchorElement>}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        onClick={onClick}
        className={classes}
        {...rest}
      >
        {inner}
      </a>
    )
  }

  return (
    <button
      ref={ref as React.Ref<HTMLButtonElement>}
      type={type}
      disabled={isOff}
      onClick={onClick}
      className={classes}
      {...rest}
    >
      {inner}
    </button>
  )
})

export default Button

/** Botão só de ícone. Exige aria-label porque não sobra texto pra anunciar. */
export function IconButton({
  Icon,
  label,
  size = 'md',
  variant = 'ghost',
  className,
  onClick,
  disabled,
}: {
  Icon: LucideIcon
  label: string
  size?: keyof typeof SIZE
  variant?: keyof typeof VARIANT
  className?: string
  onClick?: (e: React.MouseEvent) => void
  disabled?: boolean
}) {
  const pad = { sm: 'p-1.5', md: 'p-2', lg: 'p-2.5' }[size]
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'inline-flex items-center justify-center rounded-md transition-colors duration-1 ease-smooth',
        VARIANT[variant],
        pad,
        disabled && 'opacity-40 pointer-events-none',
        className,
      )}
    >
      <Icon className={ICON_SIZE[size]} />
    </button>
  )
}
