import { motion } from 'framer-motion'
import { cn } from '../../lib/cn'
import { fadeInUp } from '../../lib/motion'

/*
 * Bloco preenchido, para conteúdo (texto, oferta, chamada). Para DADO use
 * Panel, que é delineado. A distinção não é decorativa: numa faixa .section-alt
 * (surface-1/60) um Card cheio some no fundo, e o Panel continua legível.
 */

export default function Card({
  children,
  className,
  elevated,
  interactive,
  onClick,
  /** Anima na entrada quando o pai tem staggerContainer. */
  animate,
}: {
  children: React.ReactNode
  className?: string
  /** surface-2 em vez de surface-1. Para card dentro de card. */
  elevated?: boolean
  /** Levanta no hover. Só quando o card inteiro for clicável. */
  interactive?: boolean
  onClick?: () => void
  animate?: boolean
}) {
  const classes = cn(
    elevated ? 'card-elevated' : 'card',
    interactive && 'cursor-pointer transition-colors duration-1 ease-smooth hover:border-line-strong',
    className,
  )

  if (animate) {
    return (
      <motion.div
        variants={fadeInUp}
        whileHover={interactive ? { y: -3 } : undefined}
        onClick={onClick}
        className={classes}
      >
        {children}
      </motion.div>
    )
  }

  return <div onClick={onClick} className={classes}>{children}</div>
}

/**
 * Ladrilho de número: valor em mono grande, rótulo miúdo em versalete embaixo.
 * É a unidade de leitura de indicador em todo o site.
 */
export function StatTile({
  label,
  value,
  tone = 'default',
  hint,
  className,
}: {
  label: React.ReactNode
  value: React.ReactNode
  tone?: 'default' | 'green' | 'red' | 'muted'
  /** Linha extra miúda embaixo do rótulo (variação, período). */
  hint?: React.ReactNode
  className?: string
}) {
  const color = {
    default: 'text-ink-1',
    green: 'text-green-400',
    red: 'text-red-400',
    muted: 'text-ink-2',
  }[tone]

  return (
    <div className={cn('stat-tile', className)}>
      <div className={cn('stat-value', color)}>{value}</div>
      <div className="stat-label">{label}</div>
      {hint != null && <div className="text-[10px] text-ink-4 mt-0.5">{hint}</div>}
    </div>
  )
}

/** Cabeçalho de seção: título + subtítulo, centralizado, no ritmo do sistema. */
export function SectionHead({
  title,
  sub,
  eyebrow,
  className,
}: {
  title: React.ReactNode
  sub?: React.ReactNode
  /** Rótulo miúdo acima do título. */
  eyebrow?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('section-head', className)}>
      {eyebrow != null && <div className="label-micro mb-3">{eyebrow}</div>}
      <h2 className="section-title">{title}</h2>
      {sub != null && <p className="section-sub">{sub}</p>}
    </div>
  )
}
