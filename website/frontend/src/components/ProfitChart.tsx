interface DayData {
  match_date: string
  profit: number
}

export default function ProfitChart({ data }: { data: DayData[] }) {
  if (!data || data.length < 2) return null

  const sorted = [...data].sort((a, b) => a.match_date.localeCompare(b.match_date))
  let cum = 0
  const points = sorted.map(d => { cum += Number(d.profit); return cum })

  const W = 600, H = 140
  const PL = 8, PR = 8, PT = 20, PB = 20
  const innerW = W - PL - PR
  const innerH = H - PT - PB

  const minV = Math.min(0, ...points)
  const maxV = Math.max(0, ...points)
  const range = maxV - minV || 1

  const px = (i: number) => PL + (i / (points.length - 1)) * innerW
  const py = (v: number) => PT + (1 - (v - minV) / range) * innerH

  const linePath = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ')
  const zeroY    = py(0)
  const fillPath = `${linePath} L${px(points.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${PL},${zeroY.toFixed(1)} Z`

  const last    = points[points.length - 1]
  const isGreen = last >= 0
  const color   = isGreen ? '#22c55e' : '#ef4444'
  const fill    = isGreen ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'

  // Datas início e fim
  const fmtDate = (s: string) => new Date(s).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
  const dateStart = fmtDate(sorted[0].match_date)
  const dateEnd   = fmtDate(sorted[sorted.length - 1].match_date)

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="none">
        {/* zero line */}
        <line x1={PL} y1={zeroY} x2={W - PR} y2={zeroY} stroke="#3f3f46" strokeWidth="1" strokeDasharray="4,4" />

        {/* fill */}
        <path d={fillPath} fill={fill} />

        {/* line */}
        <path d={linePath} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />

        {/* last dot */}
        <circle cx={px(points.length - 1)} cy={py(last)} r="4" fill={color} />

        {/* last value */}
        <text
          x={Math.min(px(points.length - 1) + 6, W - PR - 2)}
          y={py(last) + 4}
          fill={color} fontSize="11" fontWeight="bold" textAnchor="start"
        >
          {last >= 0 ? '+' : ''}{last.toFixed(1)}u
        </text>

        {/* date labels */}
        <text x={PL} y={H - 4} fill="#52525b" fontSize="10" textAnchor="start">{dateStart}</text>
        <text x={W - PR} y={H - 4} fill="#52525b" fontSize="10" textAnchor="end">{dateEnd}</text>
      </svg>
    </div>
  )
}
