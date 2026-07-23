import { cn } from '../../lib/cn'

/** Fita de dados rolando infinitamente · usada como ticker ao vivo (hero, nav) */
export default function Marquee({
  items,
  className,
  reverse = false,
}: {
  items: React.ReactNode[]
  className?: string
  reverse?: boolean
}) {
  return (
    <div className={cn('relative flex overflow-hidden gap-8 scrollbar-none [mask-image:linear-gradient(90deg,transparent,black_8%,black_92%,transparent)]', className)}>
      <div className={cn('flex shrink-0 items-center gap-8 animate-marquee', reverse && '[animation-direction:reverse]')}>
        {items.map((item, i) => <div key={`a-${i}`} className="shrink-0">{item}</div>)}
      </div>
      <div className={cn('flex shrink-0 items-center gap-8 animate-marquee', reverse && '[animation-direction:reverse]')} aria-hidden="true">
        {items.map((item, i) => <div key={`b-${i}`} className="shrink-0">{item}</div>)}
      </div>
    </div>
  )
}
