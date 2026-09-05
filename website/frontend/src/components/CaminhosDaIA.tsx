import { useEffect, useState } from 'react'
import api from '../services/api'
import LucroBarChart from './LucroBarChart'
import { fmtUnits } from '../utils/format'

interface CaminhoDaIA {
  encerrou_em: string
  passos: number
  motivo: 'meta' | 'red'
  unidades: number
}

interface HistoricoDaIA {
  meta: number
  fechados: number
  na_meta: number
  no_red: number
  unidades: number
  melhor_sequencia: number
  passos_em_aberto: number
  caminhos: CaminhoDaIA[]
}

/*
 * COMO A IA FOI NOS CAMINHOS · o histórico que a aba não tinha.
 *
 * A aba só sabia falar do caminho de QUEM JÁ CONFIGUROU. Quem nunca pegou um
 * via uma tela vazia com um convite e nada mais; quem já tinha um não tinha
 * com o que comparar. E a amostra pessoal nunca vai responder "isso costuma
 * dar certo?": um caminho de seis passos leva ~28 dias, então em três meses
 * cabem uns poucos.
 *
 * O QUE ESTE BLOCO PRECISA MOSTRAR é a forma do produto, e ela é
 * contraintuitiva: a maioria dos caminhos MORRE. O que sustenta a conta é que
 * morrer custa 1u e chegar ao fim paga dez. Um número só ("+42,9u") esconde
 * isso e vende bem demais; a lista inteira, com os vermelhos todos visíveis,
 * conta a verdade e ainda assim é um bom argumento.
 *
 * Por isso o gráfico é de barras por caminho e não uma curva acumulada: a
 * curva acumulada é a fotografia mais bonita e a menos honesta que existe
 * aqui.
 */
export default function CaminhosDaIA({ compacto = false }: { compacto?: boolean }) {
  const [ia, setIa] = useState<HistoricoDaIA | null>(null)

  useEffect(() => {
    api.get('/public/alavancagem/caminhos')
      .then(r => setIa(r.data))
      .catch(() => setIa(null))
  }, [])

  if (!ia || ia.fechados === 0) return null

  const naMeta = ia.caminhos.filter(c => c.motivo === 'meta')
  const pagamentos = naMeta.map(c => c.unidades).sort((a, b) => a - b)
  const barras = ia.caminhos
    .slice()
    .reverse()
    .map(c => ({
      label: `${c.encerrou_em.slice(8, 10)}/${c.encerrou_em.slice(5, 7)}`,
      value: c.unidades,
      meta: c.motivo === 'meta' ? `${c.passos} greens` : `RED no ${c.passos}º`,
    }))

  /* Ate' onde os caminhos chegaram.
   *
   * O total e a lista respondem "quanto rendeu" e "quando"; nenhum dos dois
   * responde a pergunta que decide se vale pegar o produto: ONDE ele costuma
   * morrer. Se a maioria cai no 1o passo, e' um produto; se a maioria chega ao
   * 4o e morre perto do fim, e' outro completamente diferente, com o mesmo
   * lucro no rodape. Sai dos dados que a rota ja' manda (passos + motivo). */
  const porPasso = Array.from({ length: ia.meta }, (_, i) => {
    const passo = i + 1
    const mortos = ia.caminhos.filter(c => c.motivo === 'red' && c.passos === passo).length
    const fechou = passo === ia.meta ? naMeta.length : 0
    return { passo, mortos, fechou }
  })
  const maxPasso = Math.max(1, ...porPasso.map(p => p.mortos + p.fechou))

  const arriscado   = ia.fechados                      // 1u de entrada por caminho
  const roi         = arriscado > 0 ? (ia.unidades / arriscado) * 100 : 0
  const taxaFecha   = ia.fechados > 0 ? (ia.na_meta / ia.fechados) * 100 : 0
  const passoMedio  = ia.fechados > 0
    ? ia.caminhos.reduce((a, c) => a + c.passos, 0) / ia.fechados
    : 0
  const maiorPagamento = pagamentos.length > 0 ? pagamentos[pagamentos.length - 1] : 0

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-xs text-ink-3 font-semibold">Como a IA foi nos caminhos</p>
          <p className="text-[11px] text-ink-4 mt-0.5">
            todos os caminhos encerrados desde o primeiro pick de alavancagem
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className={`font-mono text-lg font-black tabular-nums ${ia.unidades >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
            {fmtUnits(ia.unidades, 1)}
          </p>
          <p className="text-[10px] text-ink-4">em {ia.fechados} caminhos</p>
        </div>
      </div>

      {/* A frase que o gráfico sozinho não diz. Sem ela, quem bate o olho no
          total lê "produto que só ganha" · que é o oposto do que aconteceu. */}
      <p className="text-[11px] text-ink-3 leading-relaxed mb-4">
        {ia.no_red} {ia.no_red === 1 ? 'caminho morreu' : 'caminhos morreram'} no
        meio e {ia.no_red === 1 ? 'custou' : 'custaram'} a entrada, 1u cada.
        {naMeta.length > 0 && (
          <> {ia.na_meta} {ia.na_meta === 1 ? 'chegou' : 'chegaram'} aos {ia.meta} greens
          e {ia.na_meta === 1 ? 'pagou' : 'pagaram'} de {fmtUnits(pagamentos[0], 1)} a{' '}
          {fmtUnits(pagamentos[pagamentos.length - 1], 1)}. É assim que o produto
          funciona: perder é o caso comum, e o que fecha paga por vários que não
          fecharam.</>
        )}
      </p>

      {/* INDICADORES DO PRODUTO. O bloco tinha um numero so' (o total), e ele
          nao responde nada sozinho: 1u por caminho e' a entrada, entao o que
          diz se o produto paga e' o retorno sobre o arriscado, e o que diz como
          ele se comporta e' a taxa de caminhos que fecham. */}
      {!compacto && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-4">
          <div className="stat-tile">
            <div className={`stat-value text-lg ${roi >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
              {roi >= 0 ? '+' : ''}{roi.toFixed(0)}%
            </div>
            <div className="stat-label">Retorno sobre o arriscado</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value text-lg">{taxaFecha.toFixed(0)}%</div>
            <div className="stat-label">Caminhos que fecharam</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value text-lg">{passoMedio.toFixed(1)}</div>
            <div className="stat-label">Passos por caminho</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value text-lg text-accent-ink">{fmtUnits(maiorPagamento, 1)}</div>
            <div className="stat-label">Maior pagamento</div>
          </div>
        </div>
      )}

      {!compacto && (
        <>
          <p className="text-[11px] font-semibold text-ink-3 mb-2">Lucro por caminho encerrado, unidades</p>
          <LucroBarChart data={barras} height={170} />
        </>
      )}

      {/* ONDE O CAMINHO MORRE. Uma barra por passo, com a fatia verde do passo
          final: e' a forma do produto num desenho so'. */}
      {!compacto && ia.fechados > 0 && (
        <div className="mt-6">
          <p className="text-[11px] font-semibold text-ink-3 mb-2">Até que passo cada caminho foi</p>
          <div className="space-y-1.5">
            {porPasso.map(p => {
              const total = p.mortos + p.fechou
              return (
                <div key={p.passo} className="flex items-center gap-2.5">
                  <span className="text-[10px] text-ink-4 w-12 shrink-0 tabular-nums">{p.passo}º passo</span>
                  <div className="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden flex min-w-[40px]">
                    {p.mortos > 0 && (
                      <div className="h-full bg-red-400/80" style={{ width: `${(p.mortos / maxPasso) * 100}%` }} />
                    )}
                    {p.fechou > 0 && (
                      <div className="h-full bg-green-500" style={{ width: `${(p.fechou / maxPasso) * 100}%` }} />
                    )}
                  </div>
                  <span className="font-mono text-[10px] text-ink-3 w-20 text-right shrink-0 tabular-nums">
                    {total === 0 ? '--' : p.fechou > 0 ? `${p.fechou} fechou` : `${p.mortos} morreu`}
                  </span>
                </div>
              )
            })}
          </div>
          <p className="text-[10px] text-ink-4 mt-2">
            Vermelho é caminho que morreu naquele passo; verde é caminho que
            chegou aos {ia.meta} e pagou.
          </p>
        </div>
      )}

      {ia.passos_em_aberto > 0 && (
        <p className="text-[11px] text-ink-4 mt-4">
          Há um caminho em andamento, no {ia.passos_em_aberto}º passo. Ele não
          entra em nenhuma soma acima enquanto não encerrar.
        </p>
      )}
    </div>
  )
}
