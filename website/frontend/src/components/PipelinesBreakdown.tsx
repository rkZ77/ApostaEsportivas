import { Info } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fmtSigned, fmtUnits } from '../utils/format'

/*
 * Quebra por pipeline · aba de Meus Picks.
 *
 * Meus Picks responde "quanto eu ganhei". Não respondia "ganhei COM O QUÊ" ·
 * e é a segunda pergunta que muda decisão: estar no lucro somando tudo e estar
 * no lucro apesar de um pipeline são diagnósticos diferentes, e só o segundo
 * diz o que parar de seguir.
 *
 * COMPONENTE, e não página própria (foi página por um dia, 2026-08-19).
 * Como aba ele lê o `by_pipeline` que já veio no mesmo GET /banca da tela ·
 * a página fazia uma segunda chamada idêntica pra buscar o mesmo payload, e
 * ainda tirava o usuário de contexto por um dado que é leitura da MESMA lista
 * que ele estava olhando.
 *
 * ALAVANCAGEM NÃO ENTRA AQUI. Ela não está em `entries` no backend (a consulta
 * filtra `pick_type != 'alavancagem'`), porque caminho em andamento não é
 * dinheiro: só vira P&L quando encerra. Misturar degrau a degrau com o resto
 * contaria a mesma aposta por duas réguas. A tela dela é /banca/alavancagem, e
 * o rodapé daqui aponta pra lá.
 */

export interface Pipeline {
  key: string
  label: string
  total: number
  greens: number
  reds: number
  pnl: number
  units: number
  staked_units: number
  win_rate: number
  yield: number
}

/** Barra de participação · quanto deste pipeline no volume total de apostas. */
function BarraVolume({ pct }: { pct: number }) {
  return (
    <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden w-full">
      <div
        className="h-full rounded-full bg-ink-4"
        style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
      />
    </div>
  )
}

function CardPipeline({ p, volumeTotal }: { p: Pipeline; volumeTotal: number }) {
  const positivo = p.pnl >= 0
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p className="text-sm font-black text-ink-1">{p.label}</p>
          <p className="text-[11px] text-ink-4 mt-0.5">
            {p.total} {p.total === 1 ? 'aposta' : 'apostas'}, {p.greens}G/{p.reds}R
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className={`font-mono text-lg font-black tabular-nums ${positivo ? 'text-accent-ink' : 'text-red-400'}`}>
            {fmtSigned(p.pnl)}
          </p>
          <p className="font-mono text-[10px] text-ink-4 tabular-nums">
            {fmtUnits(p.units)}
          </p>
        </div>
      </div>

      <BarraVolume pct={volumeTotal > 0 ? (p.total / volumeTotal) * 100 : 0} />

      <div className="grid grid-cols-3 gap-2 mt-3">
        {[
          { l: 'Win rate', v: `${p.win_rate}%` },
          /* Yield é lucro em unidades sobre unidades APOSTADAS · é o que
             compara pipelines de volume diferente entre si. ROI sobre a banca
             faria o pipeline mais frequente parecer sempre o melhor. */
          { l: 'Yield', v: `${p.yield >= 0 ? '+' : ''}${p.yield.toFixed(1)}%` },
          { l: 'Arriscado', v: `${p.staked_units.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}u` },
        ].map(({ l, v }) => (
          <div key={l} className="text-center">
            <p className="font-mono text-sm font-bold text-ink-1 tabular-nums">{v}</p>
            <p className="text-[10px] text-ink-4 mt-0.5">{l}</p>
          </div>
        ))}
      </div>
    </div>
  )
}


/*
 * LUCRO POR PRODUTO, EM BARRAS (2026-09-10, pedido do usuário).
 *
 * A aba já dizia quanto cada produto rendeu, mas em nove cartões de números:
 * para saber quem puxou o mês para cima era preciso ler nove valores e
 * ordená-los de cabeça. A comparação entre categorias é trabalho de barra, não
 * de leitura de tabela.
 *
 * EM UNIDADES, e não em reais. Unidade é a régua que compara produtos entre si
 * e entre meses, porque não muda quando a banca muda de tamanho. O valor em
 * reais continua no cartão de cada produto, que é onde ele responde "quanto
 * entrou no bolso".
 *
 * ZERO NO MEIO, lucro para a direita e prejuízo para a esquerda: o lado da
 * barra já diz o sinal antes de a cor dizer. Isso não é enfeite. Verde e
 * vermelho ficam a uma distância de 6,5 (ΔE) para quem tem deuteranopia, que
 * é a faixa em que a cor sozinha não distingue nada · o lado do zero e o
 * número com sinal ao lado de cada barra são o que faz a leitura funcionar
 * para essa pessoa. Nunca tirar os dois.
 */
function GraficoPorProduto({ pipelines }: { pipelines: Pipeline[] }) {
  const ordenado = [...pipelines].sort((a, b) => b.units - a.units)
  /* A escala sai do maior valor ABSOLUTO dos dois lados, então lucro e
     prejuízo compartilham a mesma régua: uma barra de -2u tem exatamente o
     tamanho de uma de +2u. Escalas separadas por lado fariam um prejuízo
     pequeno parecer do tamanho do maior lucro. */
  const maior = Math.max(...ordenado.map(p => Math.abs(p.units)), 0.1)

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <h3 className="text-sm font-black text-ink-1">Lucro por produto</h3>
        <span className="text-[10px] text-ink-4">em unidades</span>
      </div>
      <p className="text-[11px] text-ink-4 mb-4 leading-relaxed">
        Unidade compara produtos entre si sem depender do tamanho da sua banca.
      </p>

      <ul className="space-y-1.5">
        {ordenado.map(p => {
          const positivo = p.units >= 0
          const largura = (Math.abs(p.units) / maior) * 50
          return (
            <li key={p.key} className="group flex items-center gap-2">
              <span className="w-[66px] sm:w-[88px] shrink-0 text-[11px] text-ink-2 truncate"
                    title={p.label}>
                {p.label}
              </span>

              <div className="relative flex-1 h-5 min-w-0">
                {/* A linha do zero, discreta: é referência, não dado. */}
                <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" aria-hidden="true" />
                <div
                  className={`absolute top-1/2 -translate-y-1/2 h-2.5 ${
                    positivo
                      ? 'left-1/2 rounded-r-[4px] bg-accent'
                      : 'right-1/2 rounded-l-[4px] bg-red-500'}`}
                  style={{ width: `${Math.max(largura, p.units === 0 ? 0 : 1.5)}%` }}
                  aria-hidden="true"
                />
                {/* Um cartão por barra ao passar o dedo/mouse: o detalhe que
                    não cabe na linha, sem tirar ninguém da comparação. */}
                <div className="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-1 z-10
                                opacity-0 group-hover:opacity-100 transition-opacity duration-1
                                whitespace-nowrap rounded-md border border-line-strong bg-surface-2
                                px-2 py-1 text-[10px] text-ink-2 shadow-lg">
                  {p.total} {p.total === 1 ? 'aposta' : 'apostas'}, {p.greens}G/{p.reds}R,
                  {' '}yield {p.yield >= 0 ? '+' : ''}{p.yield.toFixed(1)}%
                </div>
              </div>

              {/* O NUMERO COM SINAL fica sempre visível, em todas as barras: é
                  ele que carrega a polaridade quando a cor não carrega. */}
              <span className={`w-[52px] shrink-0 text-right font-mono text-[11px] font-bold tabular-nums
                                ${positivo ? 'text-accent-ink' : 'text-red-400'}`}>
                {fmtUnits(p.units)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default function PipelinesBreakdown({ pipelines }: { pipelines: Pipeline[] }) {
  const navigate = useNavigate()

  if (pipelines.length === 0) {
    return (
      <div className="card p-12 text-center border-dashed">
        <p className="text-ink-3 text-sm font-semibold mb-2">Nenhuma aposta resolvida ainda</p>
        <p className="text-ink-4 text-xs leading-relaxed max-w-sm mx-auto">
          A quebra por pipeline aparece assim que a primeira aposta que você
          registrou for liquidada.
        </p>
      </div>
    )
  }

  const volumeTotal = pipelines.reduce((a, p) => a + p.total, 0)
  const pnlTotal    = pipelines.reduce((a, p) => a + p.pnl, 0)
  const unidades    = pipelines.reduce((a, p) => a + p.units, 0)
  const noAzul      = pipelines.filter(p => p.pnl > 0).length

  /* MELHOR E PIOR, medidos em UNIDADE.
   *
   * O backend ordena por reais, e nesta tela isso responderia a pergunta
   * errada: reais dependem de quanto foi apostado em cada produto, então o
   * mais frequente tende a liderar por volume e não por acerto. Unidade é a
   * mesma régua para todos.
   *
   * Os dois só aparecem se forem produtos DIFERENTES: com um produto só na
   * lista, "melhor" e "pior" seriam o mesmo cartão escrito duas vezes. */
  const porUnidade = [...pipelines].sort((a, b) => b.units - a.units)
  const melhor = porUnidade[0]
  const pior   = porUnidade.length > 1 ? porUnidade[porUnidade.length - 1] : null

  return (
    <div className="space-y-4">
      {/* Total · o mesmo número da aba Apostas, e pelo mesmo motivo: sai do
          mesmo `entries` no backend, então as duas abas não têm como
          discordar. Sem alavancagem, igual lá. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          {
            l: 'Total no período',
            v: pnlTotal === 0 ? 'R$ 0' : fmtSigned(pnlTotal),
            sub: 'sem alavancagem',
            c: pnlTotal > 0 ? 'text-accent-ink' : pnlTotal < 0 ? 'text-red-400' : 'text-ink-2',
          },
          {
            l: 'Em unidades',
            v: fmtUnits(unidades),
            sub: 'independe do valor da sua unidade',
            c: unidades >= 0 ? 'text-accent-ink' : 'text-red-400',
          },
          {
            l: 'Pipelines no azul',
            v: `${noAzul} de ${pipelines.length}`,
            sub: 'onde o lucro está concentrado',
            c: noAzul * 2 >= pipelines.length ? 'text-accent-ink' : 'text-ink-1',
          },
          {
            l: 'Rende mais',
            v: melhor.label,
            sub: `${fmtUnits(melhor.units)} em ${melhor.total} ${melhor.total === 1 ? 'aposta' : 'apostas'}`,
            c: melhor.units >= 0 ? 'text-accent-ink' : 'text-ink-1',
          },
        ].map(({ l, v, sub, c }) => (
          <div key={l} className="card p-4">
            <div className="text-[10px] text-ink-3 mb-1">{l}</div>
            <div className={`text-xl font-black ${c}`}>{v}</div>
            <div className="text-[10px] text-ink-4 mt-0.5">{sub}</div>
          </div>
        ))}
      </div>

      {/* O QUE ESTA CUSTANDO fica ao lado do que está rendendo · saber onde o
          lucro nasce só muda decisão junto com saber onde ele vaza, e era esse
          o lado que a tela não dizia. Só entra quando o produto de fato perde:
          num mês em que todos fecharam no azul, chamar o último de "custa
          mais" seria inventar um problema. */}
      {pior && pior.units < 0 && (
        <div className="card p-4 border-red-500/30">
          <div className="text-[10px] text-ink-3 mb-1">Custa mais</div>
          <div className="text-xl font-black text-red-400">{pior.label}</div>
          <div className="text-[10px] text-ink-4 mt-0.5">
            {fmtUnits(pior.units)} em {pior.total} {pior.total === 1 ? 'aposta' : 'apostas'},
            {' '}win rate {pior.win_rate}%
          </div>
        </div>
      )}

      <GraficoPorProduto pipelines={pipelines} />

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {pipelines.map(p => (
          <CardPipeline key={p.key} p={p} volumeTotal={volumeTotal} />
        ))}
      </div>

      {/* Alavancagem tem régua própria · o link evita que a ausência dela
          nesta lista pareça dado faltando. */}
      <button
        onClick={() => navigate('/banca/alavancagem')}
        className="card p-4 w-full text-left hover:border-ink-4/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Info className="w-3.5 h-3.5 text-ink-4 shrink-0" />
          <p className="text-xs text-ink-3">
            <strong className="text-ink-2">Alavancagem não entra nesta conta.</strong>{' '}
            Ela é um caminho: o composto em andamento não é dinheiro e só vira
            saldo quando você encerra. Ver a alavancagem separada
          </p>
        </div>
      </button>
    </div>
  )
}
