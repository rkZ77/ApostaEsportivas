import { cn } from '../../lib/cn'
import { getResultStyle, PICK_TYPE_CLS, PICK_TYPE_LABEL } from '../../utils/resultStyle'

/*
 * Tag em texto com borda. Substitui as pílulas coloridas soltas que cada tela
 * desenhava por conta.
 *
 * Na fonte do site: o badge diz palavra, e monoespaçada aqui é pra número.
 * A cor é o único eixo que varia, porque é ela que carrega o significado que
 * o usuário já aprendeu.
 */

const TONE = {
  neutral: 'bg-transparent text-ink-3 border-line-strong',
  green:   'bg-green-500/5 text-green-400 border-green-500/30',
  red:     'bg-red-500/5 text-red-400 border-red-500/30',
  yellow:  'bg-yellow-400/5 text-yellow-400 border-yellow-400/30',
  amber:   'bg-amber-400/5 text-amber-400 border-amber-400/30',
  blue:    'bg-blue-400/5 text-blue-400 border-blue-400/30',
  purple:  'bg-purple-500/5 text-purple-400 border-purple-500/30',
  orange:  'bg-orange-400/5 text-orange-400 border-orange-400/30',
  sky:     'bg-sky-400/5 text-sky-400 border-sky-400/30',
  teal:    'bg-teal-500/5 text-teal-400 border-teal-500/30',
} as const

export type BadgeTone = keyof typeof TONE

export default function Badge({
  tone = 'neutral',
  children,
  className,
  Icon,
}: {
  tone?: BadgeTone
  children: React.ReactNode
  className?: string
  Icon?: React.ComponentType<{ className?: string }>
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-[10px] font-bold tracking-wide',
        'px-1.5 py-0.5 rounded-sm border',
        TONE[tone],
        className,
      )}
    >
      {Icon && <Icon className="w-3 h-3" />}
      {children}
    </span>
  )
}

/** Plano do usuário. Mesmas cores das classes .badge-* legadas. */
export function PlanBadge({ plan, className }: { plan?: string; className?: string }) {
  const map: Record<string, { tone: BadgeTone; label: string }> = {
    vip:   { tone: 'yellow',  label: 'VIP' },
    admin: { tone: 'purple',  label: 'Admin' },
    trial: { tone: 'amber',   label: 'Teste' },
    free:  { tone: 'neutral', label: 'Free' },
  }
  const { tone, label } = map[plan ?? 'free'] ?? map.free
  return <Badge tone={tone} className={className}>{label}</Badge>
}

/**
 * Tipo do pick (VIP, free, múltipla, alavancagem, faltas, defesas).
 * Lê de PICK_TYPE_CLS pra ficar na mesma convenção da borda do card e do
 * badge em canvas do compartilhamento: uma fonte de verdade só.
 */
export function PickTypeBadge({
  type,
  short,
  className,
}: {
  type: string
  /** Rótulo curto pra linha apertada de lista ("Múlt.", "Alav."). */
  short?: boolean
  className?: string
}) {
  const SHORT: Record<string, string> = {
    multipla: 'Múlt.', multiplas: 'Múlt.', alavancagem: 'Alav.',
  }
  const label = short
    ? SHORT[type] ?? PICK_TYPE_LABEL[type] ?? type
    : PICK_TYPE_LABEL[type] ?? type
  return (
    <span
      className={cn(
        'inline-flex items-center text-[10px] font-bold tracking-wide',
        'px-1.5 py-0.5 rounded-sm border shrink-0',
        PICK_TYPE_CLS[type] ?? 'text-ink-3 border-line-strong',
        className,
      )}
    >
      {label}
    </span>
  )
}

/**
 * Resultado do pick (GREEN, RED, PUSH, ½ WIN, ½ LOSS).
 * Nunca usa o campo `emoji` do RESULT_STYLE: o sistema não usa emoji, o
 * significado vem da cor e do rótulo.
 */
export function ResultBadge({
  result,
  className,
}: {
  result?: string | null
  className?: string
}) {
  const rs = getResultStyle(result)
  if (!rs) {
    return (
      <span className={cn('text-[10px] font-bold tracking-wide text-ink-4 shrink-0', className)}>
        {result || 'Pendente'}
      </span>
    )
  }
  return (
    <span
      className={cn(
        'inline-flex items-center text-[10px] font-bold tracking-wide',
        'px-1.5 py-0.5 rounded-sm border shrink-0',
        rs.bg, rs.border, rs.text,
        className,
      )}
    >
      {rs.label}
    </span>
  )
}

/** Ponto pulsante de "ao vivo". Serve de indicador de IA processando também. */
export function LiveDot({
  tone = 'green',
  className,
}: {
  tone?: 'green' | 'amber' | 'red'
  className?: string
}) {
  const color = { green: 'bg-accent', amber: 'bg-amber-400', red: 'bg-red-400' }[tone]
  return (
    <span className={cn('relative inline-flex w-2 h-2 shrink-0', className)}>
      <span className={cn('absolute inset-0 rounded-full opacity-60 animate-ping', color)} />
      <span className={cn('relative inline-flex w-2 h-2 rounded-full', color)} />
    </span>
  )
}
