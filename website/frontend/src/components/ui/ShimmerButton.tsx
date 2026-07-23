import { Link } from 'react-router-dom'
import { cn } from '../../lib/cn'

/** CTA primario com brilho passando · uso moderado, so no botao principal do hero */
export default function ShimmerButton({
  to,
  children,
  className,
}: {
  to: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <Link
      to={to}
      className={cn(
        'group relative inline-flex items-center justify-center overflow-hidden rounded-md bg-green-500 px-7 py-3.5 text-sm font-bold text-black transition-colors hover:bg-green-400',
        className
      )}
    >
      <span
        className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 ease-out group-hover:translate-x-full"
        aria-hidden="true"
      />
      <span className="relative">{children}</span>
    </Link>
  )
}
