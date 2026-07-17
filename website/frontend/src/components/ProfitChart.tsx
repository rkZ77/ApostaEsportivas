import { useState } from 'react'

interface DayData {
  match_date: string
  profit: number
}

function niceStep(range: number): number {
  if (range <= 0) return 1
  const rough = range / 4
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  for (const mult of [1, 2, 2.5, 5, 10]) {
    if (rough <= mult * mag) return mult * mag
  }
  return mag * 10
}

export default function ProfitChart({ data, unit = 'u' }: { data: DayData[]; unit?: string }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (!data || data.length < 2) return null

  const sorted = [...data].sort((a, b) => a.match_date.localeCompare(b.match_date))
  let cum = 0
  const points = sorted.map(d => { cum += Number(d.profit); return cum })
  const dates  = sorted.map(d => d.match_date)

  const W = 600, H = 200
  const PL = 56, PR = 16, PT = 16, PB = 28
  const innerW = W - PL - PR
  const innerH = H - PT - PB

  const minV  = Math.min(0, ...points)
  const maxV  = Math.max(0, ...points)
  const range = maxV - minV || 1

  const step  = niceStep(range)
  const yMin  = Math.floor(minV / step) * step
  const yMax  = Math.ceil(maxV / step) * step
  const yRange = yMax - yMin || 1

  const px = (i: number) => PL + (i / Math.max(points.length - 1, 1)) * innerW
  const py = (v: number) => PT + (1 - (v - yMin) / yRange) * innerH

  // Y-axis ticks
  const yTicks: number[] = []
  for (let v = yMin; v <= yMax + step * 0.01; v += step) {
    yTicks.push(parseFloat(v.toFixed(10)))
  }

  // X-axis ticks · máximo 6 labels espaçadas uniformemente
  const maxXTicks = Math.min(6, points.length)
  const xTicks = Array.from({ length: maxXTicks }, (_, i) =>
    Math.round(i * (points.length - 1) / (maxXTicks - 1))
  )

  const fmtDate = (s: string) =>
    new Date(s + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })

  const fmtVal = (v: number) => {
    const sign = v >= 0 ? '+' : '-'
    const abs = Math.abs(v)
    if (unit === 'R$') return `${sign}R$${abs.toFixed(2)}`
    return `${v >= 0 ? '+' : ''}${v.toFixed(1)}${unit}`
  }

  const fmtY = (v: number) => {
    const sign = v >= 0 ? '+' : '-'
    const abs = Math.abs(v)
    if (unit === 'R$') return `${sign}${abs >= 1000 ? `${(abs/1000).toFixed(1)}k` : abs.toFixed(0)}`
    return `${v >= 0 ? '+' : ''}${v.toFixed(1)}`
  }

  const linePath = points
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${px(i).toFixed(1)},${py(v).toFixed(1)}`)
    .join(' ')

  const zeroY    = Math.min(Math.max(py(0), PT), PT + innerH)
  const fillPath = `${linePath} L${px(points.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${PL},${zeroY.toFixed(1)} Z`

  const last     = points[points.length - 1]
  const isGreen  = last >= 0
  const color    = isGreen ? '#22c55e' : '#ef4444'
  const fillClr  = isGreen ? 'rgba(34,197,94,0.09)' : 'rgba(239,68,68,0.09)'

  const hv = hoverIdx !== null ? points[hoverIdx] : null

  return (
    <div className="w-full relative select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        preserveAspectRatio="xMidYMid meet"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* Y-axis grid + labels */}
        {yTicks.map((v, i) => {
          const yPos = py(v)
          if (yPos < PT - 2 || yPos > PT + innerH + 2) return null
          const isZero = Math.abs(v) < step * 0.01
          return (
            <g key={i}>
              <line
                x1={PL} y1={yPos} x2={W - PR} y2={yPos}
                stroke={isZero ? '#3f3f46' : '#1f1f23'}
                strokeWidth={isZero ? 1 : 0.8}
                strokeDasharray={isZero ? '4,4' : 'none'}
              />
              <text x={PL - 6} y={yPos + 3.5} fill="#52525b" fontSize="9" textAnchor="end" fontFamily="monospace">
                {fmtY(v)}
              </text>
            </g>
          )
        })}

        {/* fill area */}
        <path d={fillPath} fill={fillClr} />

        {/* line */}
        <path d={linePath} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* hover hit areas */}
        {points.map((v, i) => (
          <rect
            key={i}
            x={px(i) - innerW / points.length / 2}
            y={PT}
            width={innerW / points.length}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(i)}
          />
        ))}

        {/* hover vertical line + dot */}
        {hoverIdx !== null && hv !== null && (
          <>
            <line
              x1={px(hoverIdx)} y1={PT}
              x2={px(hoverIdx)} y2={PT + innerH}
              stroke="#52525b" strokeWidth="1" strokeDasharray="3,3"
            />
            <circle cx={px(hoverIdx)} cy={py(hv)} r="4" fill={hv >= 0 ? '#22c55e' : '#ef4444'} />
          </>
        )}

        {/* last dot (always) */}
        {hoverIdx === null && (
          <circle cx={px(points.length - 1)} cy={py(last)} r="3.5" fill={color} />
        )}

        {/* X-axis date labels */}
        {xTicks.map((idx, i) => (
          <text
            key={i}
            x={px(idx)}
            y={H - 6}
            fill="#52525b" fontSize="9"
            textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
            fontFamily="monospace"
          >
            {fmtDate(dates[idx])}
          </text>
        ))}
      </svg>

      {/* Tooltip floating */}
      {hoverIdx !== null && hv !== null && (
        <div
          className="pointer-events-none absolute top-2 text-xs font-black px-2 py-1 rounded-lg border"
          style={{
            left: `${(px(hoverIdx) / W) * 100}%`,
            transform: hoverIdx > points.length * 0.7 ? 'translateX(-110%)' : 'translateX(8px)',
            background: '#111',
            borderColor: hv >= 0 ? '#22c55e40' : '#ef444440',
            color: hv >= 0 ? '#22c55e' : '#ef4444',
          }}
        >
          {fmtDate(dates[hoverIdx])} · {fmtVal(hv)}
        </div>
      )}
    </div>
  )
}
