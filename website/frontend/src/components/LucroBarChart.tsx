import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { fmtUnits } from '../utils/format'

/*
 * Lucro em unidades por categoria, em barras.
 *
 * Duas orientações porque são duas perguntas diferentes:
 *
 *   vertical   · MÊS A MÊS. O eixo é tempo, e barra separada por mês é o certo
 *                em vez de linha: meses são baldes fechados, e uma linha ligando
 *                um ao outro sugeriria continuidade que não existe (o lucro não
 *                "passa" de abril para maio, cada mês fecha o seu).
 *   horizontal · POR LIGA. Comparação entre categorias, com nome comprido. De
 *                lado, o rótulo cabe inteiro e a ordenação por tamanho da barra
 *                fica óbvia · em pé, "Brasileirão Série B" viraria "Brasil…"
 *                rodado a 45 graus.
 *
 * Barra abaixo de zero é vermelha e cresce para o outro lado a partir da linha
 * do zero, que só aparece quando existe prejuízo · num conjunto todo positivo o
 * zero é a própria base e desenhá-lo seria ruído.
 */

export interface BarraLucro {
  label: string
  value: number
  /** Linha miúda opcional (contagem de picks, aproveitamento). */
  meta?: string
}

const VERDE = '#22c55e'
const VERMELHO = '#f87171'

export default function LucroBarChart({
  data,
  orientation = 'vertical',
  height = 200,
}: {
  data: BarraLucro[]
  orientation?: 'vertical' | 'horizontal'
  height?: number
}) {
  const caixa = useRef<HTMLDivElement>(null)
  const [largura, setLargura] = useState(0)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = caixa.current
    if (!el) return
    const medir = () => setLargura(el.clientWidth)
    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (!data || data.length === 0) return null

  const valores = data.map(d => Number(d.value ?? 0))
  const maxV = Math.max(0, ...valores)
  const minV = Math.min(0, ...valores)
  const span = maxV - minV || 1

  /* ── Horizontal: uma linha por categoria, HTML puro ────────────────────
     Barra horizontal com rótulo ao lado é layout de lista, não de gráfico ·
     em SVG daria trabalho pra alinhar texto de largura variável e quebraria
     no mobile. */
  if (orientation === 'horizontal') {
    return (
      <div className="space-y-2">
        {data.map((d, i) => {
          const v = Number(d.value ?? 0)
          const pct = (Math.abs(v) / Math.max(Math.abs(maxV), Math.abs(minV), 1)) * 100
          const positivo = v >= 0
          return (
            <div key={d.label} className="flex items-center gap-2.5">
              <span className="text-[11px] text-ink-3 w-28 sm:w-36 shrink-0 truncate" title={d.label}>
                {d.label}
              </span>
              <div className="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden min-w-[40px]">
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: positivo ? VERDE : VERMELHO }}
                  initial={{ width: 0 }}
                  whileInView={{ width: `${Math.max(2, pct)}%` }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.5, delay: i * 0.03, ease: [0.16, 1, 0.3, 1] }}
                />
              </div>
              <span
                className="font-mono text-[11px] font-bold tabular-nums w-16 text-right shrink-0"
                style={{ color: positivo ? VERDE : VERMELHO }}
              >
                {fmtUnits(v, 1)}
              </span>
            </div>
          )
        })}
      </div>
    )
  }

  /* ── Vertical: SVG, mesma mecânica dos outros gráficos do projeto ────── */
  const W = largura || 600
  const H = height
  const PL = 34, PR = 8, PT = 12, PB = 30
  const innerW = W - PL - PR
  const innerH = H - PT - PB

  const passo = innerW / data.length
  const barW = Math.max(6, passo * 0.6)
  const x = (i: number) => PL + i * passo + (passo - barW) / 2
  const y = (v: number) => PT + innerH - ((v - minV) / span) * innerH
  const yZero = y(0)

  const ticks = [0, 0.25, 0.5, 0.75, 1].map(p => minV + span * p)

  /* RALEIA O RÓTULO QUANDO ELE NÃO CABE.
     Cada rótulo é uma data ("31/08") e pede ~30px pra ser lido. Com 14 barras
     em 280px de celular eles se sobrepõem e viram um borrão contínuo, que é
     pior que rótulo nenhum: some a informação E fica sujo. Aqui um a cada N
     aparece, e o último é sempre um deles · a barra mais recente é a que o
     leitor procura primeiro. As barras continuam todas desenhadas; quem quiser
     a data de uma delas passa o mouse (ou toca) e lê no rodapé. */
  const LARGURA_DO_ROTULO = 30
  const passoRotulo = Math.max(1, Math.ceil(LARGURA_DO_ROTULO / Math.max(passo, 1)))
  const mostraRotulo = (i: number) =>
    passoRotulo === 1 || (data.length - 1 - i) % passoRotulo === 0

  return (
    <div ref={caixa} className="w-full select-none">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="block"
           onMouseLeave={() => setHover(null)}>
        {ticks.map((v, i) => (
          <g key={i}>
            {/* Token, e nao hexadecimal: o #1f1f23 daqui era quase invisivel no
                tema escuro e virava uma grade preta forte sobre o branco,
                atravessando o grafico inteiro. Cor de linha e' decisao do tema
                desde 23/08, e grade de grafico nao e' excecao. */}
            <line x1={PL} y1={y(v)} x2={W - PR} y2={y(v)}
                  className="stroke-line" strokeWidth="0.8" />
            <text x={PL - 5} y={y(v) + 3} className="fill-ink-4" fontSize="8" textAnchor="end"
                  fontFamily="Inter, -apple-system, sans-serif"
                  style={{ fontVariantNumeric: 'tabular-nums' }}>
              {v.toFixed(0)}u
            </text>
          </g>
        ))}

        {/* Zero só quando há prejuízo · sem barra negativa ele é a própria base. */}
        {minV < 0 && (
          <line x1={PL} y1={yZero} x2={W - PR} y2={yZero}
                className="stroke-line-strong" strokeWidth="1" />
        )}

        {data.map((d, i) => {
          const v = Number(d.value ?? 0)
          const alvo = y(v)
          const topo = Math.min(alvo, yZero)
          const alt = Math.max(2, Math.abs(yZero - alvo))
          const positivo = v >= 0
          return (
            <g key={d.label}>
              <motion.rect
                x={x(i)} width={barW} rx="2"
                fill={positivo ? VERDE : VERMELHO}
                opacity={hover === null || hover === i ? 0.9 : 0.45}
                initial={{ height: 0, y: yZero }}
                whileInView={{ height: alt, y: topo }}
                viewport={{ once: true }}
                transition={{ duration: 0.45, delay: i * 0.04, ease: [0.16, 1, 0.3, 1] }}
              />
              <rect x={PL + i * passo} y={PT} width={passo} height={innerH}
                    fill="transparent" onMouseEnter={() => setHover(i)} />
            </g>
          )
        })}

        {data.map((d, i) => mostraRotulo(i) && (
          <text key={d.label} x={x(i) + barW / 2} y={H - 10} className="fill-ink-4" fontSize="8"
                textAnchor="middle" fontFamily="Inter, -apple-system, sans-serif">
            {d.label}
          </text>
        ))}
      </svg>

      {hover !== null && (
        <p className="text-[10px] text-ink-4 mt-1">
          {data[hover].label}, <span className="font-mono font-bold tabular-nums"
            style={{ color: Number(data[hover].value) >= 0 ? VERDE : VERMELHO }}>
            {fmtUnits(Number(data[hover].value), 1)}
          </span>
          {data[hover].meta && `, ${data[hover].meta}`}
        </p>
      )}
    </div>
  )
}
