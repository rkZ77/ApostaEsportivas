import { useEffect, useRef, useState } from 'react'
import { fmtUnits } from '../utils/format'

/*
 * Lucro acumulado em unidades, uma linha por pipeline.
 *
 * Responde "qual produto está puxando o resultado", que nenhuma tela do site
 * respondia: os números existiam somados (o placar geral) ou espalhados por
 * pick, nunca por produto ao longo do tempo.
 *
 * ACUMULADO, não diário. Lucro por dia é serrilhado e vira ruído com seis
 * séries em cima; a curva acumulada mostra a única coisa que importa aqui, que
 * é a inclinação · linha subindo é produto pagando, linha de lado é produto
 * empatando, linha descendo é produto custando dinheiro.
 *
 * Escala em unidades, mesmo plano de stake do resto do site
 * (backend/stake_plan.py), então as linhas são comparáveis entre si.
 *
 * SVG na mão, como os outros gráficos do projeto (DailyGreensChart,
 * ProfitChart): não há biblioteca de gráfico nas dependências, e trazer uma
 * para um gráfico custaria mais que escrevê-lo.
 */

interface Ponto {
  match_date: string
  source: string
  profit: number
}

/* Uma cor por pipeline. VIP fica com o verde da marca por ser o carro-chefe;
   o resto se distingue por matiz, nunca só por luminosidade (duas linhas de
   verdes diferentes viram a mesma linha para quem não distingue tons).

   São os mesmos tokens semânticos do resto do site, e não hexadecimais: no
   tema claro os tons pastéis de antes viravam risco quase branco sobre branco.
   Entram por `style` e não por atributo de apresentação porque `var()` só é
   garantido em propriedade CSS · atributo `stroke=` com var() não resolve em
   todos os navegadores. */
const COR: Record<string, string> = {
  vip:         'rgb(var(--c-green-400))',
  free:        'rgb(var(--c-sky-400))',
  multiplas:   'rgb(var(--c-purple-400))',
  alavancagem: 'rgb(var(--c-amber-400))',
  faltas:      'rgb(var(--c-rose-400))',
  goleiros:    'rgb(var(--c-teal-400))',
  /* Mesmo âmbar do selo de Player Stats em utils/resultStyle · a cor é como o
     produto é reconhecido, e ela tem que ser a mesma em toda tela. */
  player_stats:'rgb(var(--c-amber-400))',
  boost:       'rgb(var(--c-sky-400))',
}
const NOME: Record<string, string> = {
  vip: 'VIP', free: 'Free', multiplas: 'Múltiplas',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
  player_stats: 'Jogadores', boost: 'Pick Boost',
}

const fmtDia = (s: string) =>
  new Date(s + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })

export default function PipelineProfitChart({
  data,
  height = 240,
}: {
  data: Ponto[]
  height?: number
}) {
  const caixa = useRef<HTMLDivElement>(null)
  const [larguraMedida, setLarguraMedida] = useState(0)
  const [oculto, setOculto] = useState<Set<string>>(new Set())
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  // viewBox medido com altura fixa · mesma correção do DailyGreensChart: com
  // proporção presa, 1800px de largura viravam um gráfico de rolar a página.
  useEffect(() => {
    const el = caixa.current
    if (!el) return
    const medir = () => setLarguraMedida(el.clientWidth)
    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (!data || data.length === 0) return null

  // Eixo X: todos os dias com pick, em ordem. Cada série anda sobre a MESMA
  // grade — sem isso, um pipeline que publicou em menos dias apareceria com a
  // curva esticada e pareceria ter subido mais rápido que os outros.
  const dias = Array.from(new Set(data.map(p => p.match_date))).sort()
  if (dias.length < 2) return null

  const fontes = Array.from(new Set(data.map(p => p.source)))
    .filter(f => f in COR)
    .sort((a, b) => Object.keys(COR).indexOf(a) - Object.keys(COR).indexOf(b))

  const porFonte: Record<string, number[]> = {}
  for (const fonte of fontes) {
    const porDia = new Map(
      data.filter(p => p.source === fonte).map(p => [p.match_date, Number(p.profit ?? 0)]),
    )
    let acc = 0
    porFonte[fonte] = dias.map(d => {
      acc += porDia.get(d) ?? 0
      return Math.round(acc * 100) / 100
    })
  }

  const visiveis = fontes.filter(f => !oculto.has(f))
  const valores = visiveis.flatMap(f => porFonte[f])
  const maxV = Math.max(0, ...valores)
  const minV = Math.min(0, ...valores)
  const span = maxV - minV || 1

  const W = larguraMedida || 600
  const H = height
  const PL = 36, PR = 10, PT = 12, PB = 26
  const innerW = W - PL - PR
  const innerH = H - PT - PB

  const x = (i: number) => PL + (dias.length === 1 ? innerW / 2 : (i / (dias.length - 1)) * innerW)
  const y = (v: number) => PT + innerH - ((v - minV) / span) * innerH

  const linha = (serie: number[]) => serie.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')

  const ticksY = [0, 0.25, 0.5, 0.75, 1].map(p => minV + span * p)
  const maxXTicks = Math.max(2, Math.min(Math.floor(innerW / 110), dias.length))
  const ticksX = Array.from({ length: maxXTicks }, (_, i) =>
    Math.round((i * (dias.length - 1)) / Math.max(maxXTicks - 1, 1)))

  const alternar = (f: string) => {
    setOculto(prev => {
      const novo = new Set(prev)
      // Não deixa esconder a última visível: um gráfico sem série nenhuma é uma
      // caixa vazia sem explicação.
      if (novo.has(f)) novo.delete(f)
      else if (visiveis.length > 1) novo.add(f)
      return novo
    })
  }

  return (
    <div ref={caixa} className="w-full select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        className="block"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {ticksY.map((v, i) => {
          const py = y(v)
          const ehZero = Math.abs(v) < 0.001 || (minV < 0 && i === 0 && false)
          return (
            <g key={i}>
              <line
                x1={PL} y1={py} x2={W - PR} y2={py}
                className={ehZero ? 'stroke-line-strong' : 'stroke-line'}
                strokeWidth={ehZero ? 1 : 0.8}
              />
              <text
                x={PL - 5} y={py + 3} className="fill-ink-4" fontSize="8" textAnchor="end"
                fontFamily="Inter, -apple-system, sans-serif"
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {v.toFixed(0)}u
              </text>
            </g>
          )
        })}

        {/* Zero destacado quando a escala cruza o zero: é a linha que separa
            produto que paga de produto que custa. */}
        {minV < 0 && maxV > 0 && (
          <line x1={PL} y1={y(0)} x2={W - PR} y2={y(0)} className="stroke-ink-4" strokeWidth="1" strokeDasharray="3 3" />
        )}

        {ticksX.map(i => (
          <text
            key={i} x={x(i)} y={H - 8} className="fill-ink-4" fontSize="8" textAnchor="middle"
            fontFamily="Inter, -apple-system, sans-serif"
          >
            {fmtDia(dias[i])}
          </text>
        ))}

        {hoverIdx !== null && (
          <line x1={x(hoverIdx)} y1={PT} x2={x(hoverIdx)} y2={PT + innerH} className="stroke-line-strong" strokeWidth="1" />
        )}

        {visiveis.map(f => (
          <path
            key={f}
            d={linha(porFonte[f])}
            fill="none"
            style={{ stroke: COR[f] }}
            strokeWidth="1.8"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {hoverIdx !== null && visiveis.map(f => (
          <circle key={f} cx={x(hoverIdx)} cy={y(porFonte[f][hoverIdx])} r="3" style={{ fill: COR[f] }} />
        ))}

        {/* Faixas de captura do mouse · uma por dia, largura toda do gráfico */}
        {dias.map((d, i) => (
          <rect
            key={d}
            x={x(i) - innerW / dias.length / 2} y={PT}
            width={innerW / dias.length} height={innerH}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(i)}
          />
        ))}
      </svg>

      {/* Legenda clicável: com seis linhas juntas, isolar uma é a única forma de
          ler a que interessa. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-2">
        {fontes.map(f => {
          const off = oculto.has(f)
          const total = porFonte[f][porFonte[f].length - 1]
          return (
            <button
              key={f}
              onClick={() => alternar(f)}
              className={`flex items-center gap-1.5 text-[10px] transition-opacity ${off ? 'opacity-35' : ''}`}
            >
              <span className="w-2.5 h-0.5 rounded-full shrink-0" style={{ background: COR[f] }} />
              <span className="text-ink-3">{NOME[f]}</span>
              <span
                className="font-mono font-bold tabular-nums"
                style={{ color: total >= 0 ? COR[f] : 'rgb(var(--c-red-400))' }}
              >
                {fmtUnits(total, 1)}
              </span>
            </button>
          )
        })}
      </div>

      {hoverIdx !== null && (
        <p className="text-[10px] text-ink-4 mt-1.5">
          {fmtDia(dias[hoverIdx])} ·{' '}
          {visiveis.map(f => `${NOME[f]} ${fmtUnits(porFonte[f][hoverIdx], 1)}`).join(' · ')}
        </p>
      )}
    </div>
  )
}
