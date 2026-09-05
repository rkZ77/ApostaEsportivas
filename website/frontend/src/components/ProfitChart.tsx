import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

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

export default function ProfitChart({
  data,
  unit = 'u',
  /** Altura em pixels. Fixa de propósito · ver o comentário do viewBox. */
  height = 220,
}: {
  data: DayData[]
  unit?: string
  height?: number
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const caixa = useRef<HTMLDivElement>(null)
  const [larguraMedida, setLarguraMedida] = useState(0)
  const tipRef = useRef<HTMLDivElement>(null)
  const [tipW, setTipW] = useState(0)

  /*
   * O viewBox acompanha a largura real, e a altura é fixa.
   *
   * Era `viewBox="0 0 600 200"` com `h-auto`: a proporção ficava presa em 3:1
   * e a altura crescia junto com a largura. Numa faixa de 1800px o gráfico
   * virava um paredão de 600px de altura, mais alto que a tela do celular ·
   * apareceu assim que as páginas passaram a ocupar o monitor inteiro.
   *
   * Medindo, cada unidade do viewBox vale um pixel de tela: nada é escalado,
   * então o texto dos eixos sai no tamanho declarado em vez de esticar junto
   * com a largura, e a linha mantém a espessura em qualquer monitor.
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

  useLayoutEffect(() => {
    if (tipRef.current) setTipW(tipRef.current.offsetWidth)
  }, [hoverIdx])

  if (!data || data.length < 2) return null

  const sorted = [...data].sort((a, b) => a.match_date.localeCompare(b.match_date))
  let cum = 0
  const points = sorted.map(d => { cum += Number(d.profit); return cum })
  const dates  = sorted.map(d => d.match_date)

  // Antes da primeira medida, 600 mantém o desenho válido no render inicial.
  const W = larguraMedida || 600
  const H = height
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

  /*
   * Rótulos do eixo X · um a cada ~110px, não seis fixos.
   *
   * Com a largura travada em 600 dava para chutar um número; agora que o
   * gráfico ocupa a tela, seis datas em 1700px deixavam quase 300px de vazio
   * entre uma e outra. O piso de 2 é obrigatório: a conta abaixo divide por
   * (maxXTicks - 1).
   */
  const maxXTicks = Math.max(2, Math.min(Math.floor(innerW / 110), points.length))
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
  /* Tokens e não hexadecimais · o mesmo verde de #22c55e sobre papel branco
     dá 2,3:1 e a linha some. Vão por `style` porque `var()` em atributo de
     apresentação (stroke=, fill=) não resolve em todo navegador. */
  const color    = isGreen ? 'rgb(var(--c-green-400))' : 'rgb(var(--c-red-400))'
  const fillClr  = isGreen ? 'rgb(var(--c-green-400) / 0.09)' : 'rgb(var(--c-red-400) / 0.09)'

  const hv = hoverIdx !== null ? points[hoverIdx] : null

  /*
   * Tooltip em px, preso dentro da caixa. O `transform` inline que invertia o
   * balao nos ultimos dias nunca valeu: o framer-motion anima `scale` e
   * reescreve o transform do elemento, entao o balao ia sempre pra direita e
   * o `overflow-hidden` do painel cortava.
   */
  const tipLeft = (i: number) => {
    const w = tipW || 140
    return Math.round(Math.max(0, Math.min(px(i) - w / 2, W - w)))
  }

  return (
    <div ref={caixa} className="w-full relative select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        className="block"
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
                className={isZero ? 'stroke-line-strong' : 'stroke-line'}
                strokeWidth={isZero ? 1 : 0.8}
                strokeDasharray={isZero ? '4,4' : 'none'}
              />
              <text x={PL - 6} y={yPos + 3.5} className="fill-ink-4" fontSize="9" textAnchor="end" fontFamily="Inter, -apple-system, sans-serif" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {fmtY(v)}
              </text>
            </g>
          )
        })}

        {/* fill area */}
        <motion.path
          d={fillPath} style={{ fill: fillClr }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6, delay: 0.4 }}
        />

        {/* line */}
        <motion.path
          d={linePath} fill="none" style={{ stroke: color }} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
          initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        />

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
          <motion.circle
            cx={px(points.length - 1)} cy={py(last)} r="3.5" style={{ fill: color }}
            initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 0.9, type: 'spring', stiffness: 400, damping: 15 }}
          />
        )}

        {/* X-axis date labels */}
        {xTicks.map((idx, i) => (
          <text
            key={i}
            x={px(idx)}
            y={H - 6}
            fill="#52525b" fontSize="9"
            textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
            fontFamily="Inter, -apple-system, sans-serif"
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {fmtDate(dates[idx])}
          </text>
        ))}
      </svg>

      {/* Tooltip floating */}
      <AnimatePresence>
      {hoverIdx !== null && hv !== null && (
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.9 }}
          transition={{ duration: 0.12 }}
          ref={tipRef}
          className="pointer-events-none absolute top-2 text-xs font-black px-2 py-1 rounded-lg border whitespace-nowrap"
          style={{
            left: tipLeft(hoverIdx),
            background: 'rgb(var(--surface-1))',
            borderColor: hv >= 0 ? 'rgb(var(--c-green-400) / 0.25)' : 'rgb(var(--c-red-400) / 0.25)',
            color: hv >= 0 ? 'rgb(var(--c-green-400))' : 'rgb(var(--c-red-400))',
          }}
        >
          {fmtDate(dates[hoverIdx])}, {fmtVal(hv)}
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  )
}
