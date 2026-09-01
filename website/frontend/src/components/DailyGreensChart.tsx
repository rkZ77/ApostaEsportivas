import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

interface DayData {
  match_date: string
  total: number
  greens: number
  reds?: number
  push?: number
  half_wins?: number
  half_losses?: number
}

const fmtDate = (s: string) =>
  new Date(s + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })

export default function DailyGreensChart({
  data,
  /** Altura em pixels. Fixa · ver o comentário do viewBox. */
  height = 200,
}: {
  data: DayData[]
  height?: number
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const caixa = useRef<HTMLDivElement>(null)
  const [larguraMedida, setLarguraMedida] = useState(0)

  /*
   * Mesma correção do ProfitChart: viewBox medido, altura fixa.
   *
   * Era `0 0 600 180` com `h-auto`, ou seja, proporção presa em 10:3. Depois
   * que a página passou a ocupar o monitor, 1800px de largura viravam 540px de
   * altura e as barras cresciam junto · o gráfico deixava de ser leitura de
   * relance e virava paisagem para rolar.
   */
  useEffect(() => {
    const el = caixa.current
    if (!el) return
    const medir = () => setLarguraMedida(el.clientWidth)
    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (!data || data.length < 2) return null

  const sorted = [...data]
    .sort((a, b) => a.match_date.localeCompare(b.match_date))
    .slice(-30) // últimos 30 dias

  const maxTotal = Math.max(...sorted.map(d => d.total), 1)

  const W = larguraMedida || 600
  const H = height
  const PL = 28, PR = 8, PT = 12, PB = 28
  const innerW = W - PL - PR
  const innerH = H - PT - PB

  const barW   = Math.max(4, (innerW / sorted.length) * 0.65)
  const gap    = innerW / sorted.length
  const barX   = (i: number) => PL + i * gap + (gap - barW) / 2
  const barH   = (v: number) => (v / maxTotal) * innerH
  const barY   = (v: number) => PT + innerH - barH(v)

  const maxXTicks = Math.max(2, Math.min(Math.floor(innerW / 120), sorted.length))
  const xTicks = Array.from({ length: maxXTicks }, (_, i) =>
    Math.round(i * (sorted.length - 1) / Math.max(maxXTicks - 1, 1))
  )

  const hovered = hoverIdx !== null ? sorted[hoverIdx] : null
  const wr = hovered && hovered.total > 0
    ? Math.round((hovered.greens / hovered.total) * 100) : null

  return (
    <div ref={caixa} className="w-full relative select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        className="block"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* Horizontal grid lines */}
        {[0.25, 0.5, 0.75, 1].map(pct => {
          const y = PT + innerH * (1 - pct)
          const v = Math.round(maxTotal * pct)
          return (
            <g key={pct}>
              <line x1={PL} y1={y} x2={W - PR} y2={y} stroke="#1f1f23" strokeWidth="0.8" />
              <text x={PL - 4} y={y + 3} fill="#52525b" fontSize="8" textAnchor="end" fontFamily="Inter, -apple-system, sans-serif" style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</text>
            </g>
          )
        })}

        {/* Bars */}
        {sorted.map((d, i) => {
          const isHov = hoverIdx === i
          const totalH = barH(d.total)
          const greenH = barH(d.greens)
          const tx = barX(i)

          return (
            <g key={d.match_date}>
              {/* Total bar (background) */}
              <motion.rect
                x={tx}
                width={barW}
                rx="2"
                className={isHov ? 'fill-line-strong' : 'fill-surface-3'}
                initial={{ height: 0, y: PT + innerH }}
                animate={{ height: totalH, y: barY(d.total) }}
                transition={{ duration: 0.4, delay: i * 0.015, ease: [0.16, 1, 0.3, 1] }}
              />
              {/* Greens bar (foreground) */}
              {d.greens > 0 && (
                <motion.rect
                  x={tx}
                  width={barW}
                  rx="2"
                  className={isHov ? 'fill-green-300' : 'fill-green-400'}
                  opacity={isHov ? 1 : 0.85}
                  initial={{ height: 0, y: PT + innerH }}
                  animate={{ height: greenH, y: barY(d.greens) }}
                  transition={{ duration: 0.4, delay: i * 0.015 + 0.1, ease: [0.16, 1, 0.3, 1] }}
                />
              )}
              {/* Hit area */}
              <rect
                x={tx - gap * 0.2} y={PT}
                width={gap * 1.4} height={innerH}
                fill="transparent"
                onMouseEnter={() => setHoverIdx(i)}
              />
            </g>
          )
        })}

        {/* X-axis labels */}
        {xTicks.map((idx, i) => (
          <text
            key={i}
            x={barX(idx) + barW / 2}
            y={H - 6}
            className="fill-ink-4" fontSize="9"
            textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
            fontFamily="Inter, -apple-system, sans-serif"
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {fmtDate(sorted[idx].match_date)}
          </text>
        ))}
      </svg>

      {/* Tooltip */}
      <AnimatePresence>
      {hoverIdx !== null && hovered && (
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.9 }}
          transition={{ duration: 0.12 }}
          className="pointer-events-none absolute top-1 z-10 bg-surface-1 border border-line-strong rounded-md px-3 py-2 text-xs shadow-xl"
          style={{
            left: `${((barX(hoverIdx) + barW / 2) / W) * 100}%`,
            transform: hoverIdx > sorted.length * 0.65 ? 'translateX(-110%)' : 'translateX(8px)',
          }}
        >
          <p className="text-ink-2 font-semibold mb-1">{fmtDate(hovered.match_date)}</p>
          <div className="font-mono flex items-center gap-2">
            <span className="text-green-400 font-black">{hovered.greens} green</span>
            <span className="text-ink-4">,</span>
            <span className="text-ink-2">{hovered.total} picks</span>
            {wr !== null && (
              <>
                <span className="text-ink-4">,</span>
                <span className={`font-bold ${wr >= 60 ? 'text-green-400' : wr >= 45 ? 'text-yellow-400' : 'text-red-400'}`}>{wr}%</span>
              </>
            )}
          </div>
        </motion.div>
      )}
      </AnimatePresence>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 justify-end">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-green-500 inline-block" />
          <span className="text-[10px] text-ink-3">Greens</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-surface-3 inline-block" />
          <span className="text-[10px] text-ink-3">Total picks</span>
        </div>
      </div>
    </div>
  )
}
