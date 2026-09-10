import { useEffect, useRef, useState } from 'react'
import { fmtSigned } from '../utils/format'

/*
 * OS DIAS QUE FECHARAM NO VERDE E NO VERMELHO.
 *
 * O card ao lado já dizia "8 de 12 dias no positivo", e esse número responde
 * quantos, nunca quais. Um mês com quatro dias vermelhos seguidos e um mês com
 * quatro espalhados dão o mesmo 8 de 12, e são meses diferentes de viver: o
 * primeiro é uma sequência ruim, o segundo é ruído normal. A forma que mostra
 * isso é a barra por dia, na ordem em que aconteceram.
 *
 * ZERO NO MEIO, verde para cima e vermelho para baixo. O lado da linha carrega
 * o sinal sozinho, sem depender da cor: verde e vermelho ficam a uma distância
 * de 6,5 (ΔE) para quem tem deuteranopia, ou seja, quase indistinguíveis. A
 * direção da barra e o valor no topo são o que fazem a leitura funcionar para
 * essa pessoa, e não são enfeite.
 *
 * QUANTOS DIAS CABEM depende da largura, medida, e não de um ponto de corte de
 * celular: este componente vive numa coluna estreita no desktop e na largura
 * inteira no celular, então "é mobile" não descreve o espaço que ele tem. Cada
 * dia precisa de uns 30px para a data caber sem encostar na vizinha; abaixo
 * disso o gráfico mostra menos dias em vez de amassar todos.
 */

interface Dia {
  match_date: string
  profit: number
}

/** Teto de dias mesmo numa tela larga. Além disso deixa de ser "os últimos
 *  dias" e vira histórico, que é o papel da curva de evolução ao lado. */
const MAXIMO = 10
/** Largura mínima por coluna para a data caber com respiro. Em 30px as datas
 *  encostavam umas nas outras no celular, que é justamente onde a tela é mais
 *  apertada e onde ver menos dias vale mais que ver todos. */
const POR_DIA = 38

export default function DiasVerdeVermelho({ dias }: { dias: Dia[] }) {
  const caixa = useRef<HTMLDivElement>(null)
  const [largura, setLargura] = useState(0)

  useEffect(() => {
    const el = caixa.current
    if (!el) return
    const medir = () => setLargura(el.clientWidth)
    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (dias.length === 0) return null

  const cabem = largura > 0 ? Math.max(4, Math.floor(largura / POR_DIA)) : MAXIMO
  const ultimos = dias.slice(-Math.min(MAXIMO, cabem))
  /* A escala sai do maior valor absoluto, então um dia de -R$ 50 tem o mesmo
     tamanho de um de +R$ 50. Escala por lado faria o pior dia de um mês bom
     parecer catastrófico. */
  const maior = Math.max(...ultimos.map(d => Math.abs(d.profit)), 1)
  const verdes = ultimos.filter(d => d.profit > 0).length
  const vermelhos = ultimos.filter(d => d.profit < 0).length
  /* RÓTULO SÓ NO MELHOR E NO PIOR DIA.
   *
   * Um número em cima de cada barra vira uma parede de valores que ninguém lê
   * e que ainda faz "+R$ 120" de dias vizinhos se encostar numa coluna de
   * 38px. Os dois extremos são os únicos que alguém procura de olho, e são
   * eles que ganham o número; o resto se lê pela altura, e o dia inteiro tem o
   * valor no toque. */
  const melhorDia = ultimos.reduce((a, d) => (d.profit > a.profit ? d : a), ultimos[0])
  const piorDia   = ultimos.reduce((a, d) => (d.profit < a.profit ? d : a), ultimos[0])
  const rotulado = (d: Dia) =>
    (d === melhorDia && d.profit > 0) || (d === piorDia && d.profit < 0)

  const diaBR = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <h3 className="text-xs font-semibold text-ink-3">Como foi por dia</h3>
        <span className="text-[10px] text-ink-4">
          últimos {ultimos.length} {ultimos.length === 1 ? 'dia' : 'dias'}
        </span>
      </div>

      <div ref={caixa} className="w-full">
        <div className="flex items-stretch gap-1 h-[132px]" role="img"
             aria-label={`Saldo dos últimos ${ultimos.length} dias: ${verdes} no verde e ${vermelhos} no vermelho`}>
          {ultimos.map(d => {
            const positivo = d.profit > 0
            const negativo = d.profit < 0
            const altura = (Math.abs(d.profit) / maior) * 100
            return (
              <div key={d.match_date} className="group flex-1 min-w-0 flex flex-col"
                   title={`${diaBR(d.match_date)}: ${d.profit === 0 ? 'sem saldo' : fmtSigned(d.profit)}`}>
                {/* Metade de cima: a barra cresce do zero para o alto, então
                    ela se ancora embaixo. */}
                <div className="flex-1 flex flex-col justify-end items-center">
                  {positivo && rotulado(d) && (
                    <span className="font-mono text-[9px] font-bold text-accent-ink tabular-nums mb-0.5
                                     whitespace-nowrap">
                      {fmtSigned(d.profit)}
                    </span>
                  )}
                  {positivo && (
                    <div className="w-full rounded-t-[4px] bg-accent transition-opacity
                                    opacity-90 group-hover:opacity-100"
                         style={{ height: `${Math.max(altura, 3)}%` }} />
                  )}
                </div>

                {/* A linha do zero atravessa o gráfico inteiro: sem ela as
                    barras de baixo pareceriam soltas. */}
                <div className="h-px bg-line-strong w-full shrink-0" />

                <div className="flex-1 flex flex-col items-center">
                  {negativo && (
                    <div className="w-full rounded-b-[4px] bg-red-500 transition-opacity
                                    opacity-90 group-hover:opacity-100"
                         style={{ height: `${Math.max(altura, 3)}%` }} />
                  )}
                  {negativo && rotulado(d) && (
                    <span className="font-mono text-[9px] font-bold text-red-400 tabular-nums mt-0.5
                                     whitespace-nowrap">
                      {fmtSigned(d.profit)}
                    </span>
                  )}
                  {/* Dia sem saldo continua ocupando a coluna dele, com um
                      traço no lugar da barra: pular o dia mudaria a distância
                      entre os outros e faria a sequência mentir. */}
                  {!positivo && !negativo && (
                    <span className="text-[10px] text-ink-4 leading-none mt-1">-</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* As datas, fora da área das barras para não brigarem com os valores. */}
        <div className="flex items-stretch gap-1 mt-1.5">
          {ultimos.map(d => (
            <span key={d.match_date}
                  className="flex-1 min-w-0 text-center font-mono text-[9px] text-ink-4 tabular-nums truncate">
              {diaBR(d.match_date)}
            </span>
          ))}
        </div>
      </div>

      <p className="text-[11px] text-ink-3 mt-3">
        <span className="text-accent-ink font-bold">{verdes}</span>{' '}
        {verdes === 1 ? 'dia no verde' : 'dias no verde'},{' '}
        <span className="text-red-400 font-bold">{vermelhos}</span>{' '}
        {vermelhos === 1 ? 'no vermelho' : 'no vermelho'}
      </p>
    </div>
  )
}
