import { useEffect, useRef } from 'react'
import { useInView, useMotionValue, useSpring } from 'framer-motion'

/** Numero que sobe ate o valor final quando entra na tela · usado nas stats sociais (win rate, picks, ROI) */
export default function NumberTicker({
  value,
  decimals = 0,
  suffix = '',
  prefix = '',
  className,
  formatter,
}: {
  value: number
  decimals?: number
  suffix?: string
  prefix?: string
  className?: string
  /** Formatação custom (ex: fmtBRL p/ "R$ 1.234,56") · sobrepõe prefix/suffix/decimals */
  formatter?: (v: number) => string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const motionValue = useMotionValue(0)
  const springValue = useSpring(motionValue, { damping: 30, stiffness: 90 })
  const inView = useInView(ref, { once: true, margin: '0px 0px -60px 0px' })

  useEffect(() => {
    if (inView) motionValue.set(value)
  }, [inView, value, motionValue])

  useEffect(() => {
    return springValue.on('change', v => {
      if (ref.current) ref.current.textContent = formatter ? formatter(v) : `${prefix}${v.toFixed(decimals)}${suffix}`
    })
  }, [springValue, decimals, prefix, suffix, formatter])

  return <span ref={ref} className={className}>{formatter ? formatter(0) : `${prefix}0${suffix}`}</span>
}
