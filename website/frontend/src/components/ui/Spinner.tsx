import { cn } from '../../lib/cn'

/**
 * O spinner do sistema. Antes cada tela desenhava o seu: 22 arquivos repetiam
 * a mesma div com border-2 + animate-spin, em 4 tamanhos e 3 cores diferentes.
 */
const SIZE = {
  sm: 'w-4 h-4 border',
  md: 'w-6 h-6 border-2',
  lg: 'w-8 h-8 border-2',
} as const

/*
 * A cor do arco acompanha o contexto: laranja em alavancagem, azul em múltipla,
 * amarelo em VIP. Isso já existia espalhado, mas cada tela escrevia a classe na
 * mão, então o mesmo tipo de pick girava numa cor diferente em cada lugar.
 */
const TONE = {
  accent: 'border-t-accent',
  orange: 'border-t-orange-400',
  blue:   'border-t-blue-400',
  yellow: 'border-t-yellow-400',
  ink:    'border-t-ink-3',
} as const

export default function Spinner({
  size = 'md',
  tone = 'accent',
  className,
  label = 'Carregando',
}: {
  size?: keyof typeof SIZE
  tone?: keyof typeof TONE
  className?: string
  /** Lido por leitor de tela. O giro sozinho não anuncia nada. */
  label?: string
}) {
  return (
    <span
      role="status"
      aria-label={label}
      className={cn(
        'inline-block rounded-full border-line-strong animate-spin',
        SIZE[size],
        TONE[tone],
        className,
      )}
    />
  )
}

/** Spinner centralizado ocupando a altura de uma seção. O caso mais comum. */
export function SpinnerBlock({
  size = 'lg',
  tone,
  className,
}: {
  size?: keyof typeof SIZE
  tone?: keyof typeof TONE
  className?: string
}) {
  return (
    <div className={cn('flex justify-center py-16', className)}>
      <Spinner size={size} tone={tone} />
    </div>
  )
}
