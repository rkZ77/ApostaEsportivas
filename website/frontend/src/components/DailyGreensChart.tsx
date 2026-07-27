import { useState } from 'react'
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

export default function DailyGreensChart({ data }: { data: DayData[] }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (!data || data.length < 2) return null

  const sorted = [...data]
    .sort((a, b) => a.match_date.localeCompare(b.match_date))
    .slice(-30) // últimos 30 dias

  const maxTotal = Math.max(...sorted.map(d => d.total), 1)

  const W = 600, H = 180
  const PL = 28, PR = 8, PT = 12, PB = 28
  const innerW = W - PL - PR
  const innerH = H - PT - PB

  const barW   = Math.max(4, (innerW / sorted.length) * 0.65)
  const gap    = innerW / sorted.length
  const barX   = (i: number) => PL + i * gap + (gap - barW) / 2
  const barH   = (v: number) => (v / maxTotal) * innerH
  const barY   = (v: number) => PT + innerH - barH(v)

  const maxXTicks = Math.min(7, sorted.length)
  const xTicks = Array.from({ length: maxXTicks }, (_, i) =>
    Math.round(i * (sorted.length - 1) / Math.max(maxXTicks - 1, 1))
  )

  const hovered = hoverIdx !== null ? sorted[hoverIdx] : null
  const wr = hovered && hovered.total > 0
    ? Math.round((hovered.greens / hovered.total) * 100) : null

  return (
    <div className="w-full relative select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        preserveAspectRatio="xMidYMid meet"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* Horizontal grid lines */}
        {[0.25, 0.5, 0.75, 1].map(pct => {
          const y = PT + innerH * (1 - pct)
          const v = Math.round(maxTotal * pct)
          return (
            <g key={pct}>
              <line x1={PL} y1={y} x2={W - PR} y2={y} stroke="#1f1f23" strokeWidth="0.8" />
              <text x={PL - 4} y={y + 3} fill="#52525b" fontSize="8" textAnchor="end" fontFamily="'JetBrains Mono', monospace">{v}</text>
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
                fill={isHov ? '#3f3f46' : '#27272a'}
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
                  fill={isHov ? '#4ade80' : '#22c55e'}
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
            fill="#52525b" fontSize="9"
            textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
            fontFamily="'JetBrains Mono', monospace"
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
          className="pointer-events-none absolute top-1 z-10 bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2 text-xs shadow-xl"
          style={{
            left: `${((barX(hoverIdx) + barW / 2) / W) * 100}%`,
            transform: hoverIdx > sorted.length * 0.65 ? 'translateX(-110%)' : 'translateX(8px)',
          }}
        >
          <p className="text-zinc-400 font-semibold mb-1">{fmtDate(hovered.match_date)}</p>
          <div className="font-mono flex items-center gap-2">
            <span className="text-green-400 font-black">{hovered.greens} green</span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-300">{hovered.total} picks</span>
            {wr !== null && (
              <>
                <span className="text-zinc-600">·</span>
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
          <span className="text-[10px] text-zinc-500">Greens</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-zinc-700 inline-block" />
          <span className="text-[10px] text-zinc-500">Total picks</span>
        </div>
      </div>
    </div>
  )
}
