import { m as motion } from 'framer-motion'
import { Flag, Target, TrendingDown } from 'lucide-react'
import { fmtBRL, fmtSigned, fmtUnits } from '../../utils/format'
import { Tooltip } from '../ui'

/*
 * O CAMINHO, escrito uma vez só (2026-09-07).
 *
 * A escada e a lista de caminhos encerrados existiam em DUAS versões: a boa,
 * em /banca/alavancagem, e uma versão pobre dentro da aba Alavancagem de
 * /picks -- a escada virava uma fileira de "R$30 › R$37" em fonte 10, e os
 * caminhos anteriores ficavam num <details> de uma linha por caminho.
 *
 * A aba de /picks é onde a pessoa está quando o caminho importa (é lá que ela
 * segue o degrau do dia), então era justamente lá que a leitura estava pior.
 * Aqui ficam os dois componentes e os tipos; as duas telas passam a mostrar a
 * mesma coisa.
 */

export interface AlavStep {
  pick_id: number
  result: 'GREEN' | 'RED'
  odd: number
  date: string | null
  match: string
  before: number
  after: number
}

export interface CaminhoEncerrado {
  id: number
  initial: number
  final: number
  realized: number
  units: number
  greens: number
  end_reason: 'manual' | 'red' | 'meta'
  started_at: string | null
  ended_at: string | null
  /** Os degraus do caminho · só o caminho da IA traz (20/10/2026). */
  steps?: AlavStep[]
}

const curta = (iso: string | null) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '')

/*
 * O HISTÓRICO DOS CAMINHOS, EM GRÁFICO (20/10/2026, pedido do usuário: "mostra
 * melhor os caminhos que já deram certo, gráfico").
 *
 * Era uma lista de linhas dentro de um <details>. Três peças agora:
 *   · o placar dos caminhos fechados (quantos, quantos na meta, o resultado);
 *   · uma barra por caminho, em ordem de data, pra cima no lucro e pra baixo
 *     na entrada perdida · é o formato do produto: muitos reds pequenos e
 *     poucas metas grandes, e só o gráfico mostra que as metas pagam os reds;
 *   · os que bateram a meta, cada um com a mini-escada do bolo.
 * Verde e vermelho aqui são estado (meta/red), sempre com o rótulo junto.
 */
export function HistoricoDeCaminhos({ history, quem = 'ia' }: {
  history: CaminhoEncerrado[]
  quem?: 'ia' | 'voce'
}) {
  if (!history.length) return null
  const cronologico = [...history].reverse()
  const total = history.reduce((s, c) => s + c.realized, 0)
  const unidades = history.reduce((s, c) => s + c.units, 0)
  const naMeta = history.filter(c => c.end_reason === 'meta')
  /* O ZERO NA PROPORÇÃO, não no meio: o RED custa só a entrada e a meta paga
     ~10x, então com o zero no meio metade do gráfico ficava vazia. */
  const maxGanho = Math.max(0, ...history.map(c => c.realized))
  const maxPerda = Math.max(0, ...history.map(c => -c.realized))
  const escala = (maxGanho + maxPerda) || 1
  const zeroPct = (maxGanho / escala) * 100
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        {[
          ['Resultado', `${total >= 0 ? '+' : '−'}R$${Math.round(Math.abs(total)).toLocaleString('pt-BR')}`, fmtUnits(unidades, 1), total >= 0 ? 'text-accent-ink' : 'text-red-400'],
          ['Caminhos', String(history.length), 'fechados', 'text-ink-1'],
          ['Na meta', String(naMeta.length), `de ${history.length}`, 'text-accent-ink'],
        ].map(([rotulo, valor, sub, cor]) => (
          <div key={rotulo} className="rounded-md border border-line bg-surface-1 px-2 py-2.5 text-center min-w-0">
            <div className={`font-mono text-sm sm:text-lg font-black tabular-nums break-all leading-tight ${cor}`}>{valor}</div>
            <div className="text-[10px] text-ink-3 font-semibold">{rotulo}</div>
            <div className="text-[10px] text-ink-4 tabular-nums">{sub}</div>
          </div>
        ))}
      </div>

      <div>
        <div className="flex items-baseline justify-between mb-2">
          <p className="text-[11px] text-ink-3 font-semibold">Resultado de cada caminho</p>
          <p className="flex items-center gap-3 text-[10px] text-ink-4">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-accent" />meta</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500/70" />red</span>
          </p>
        </div>
        {/* Zero no meio: metade de cima pro lucro, de baixo pra entrada perdida.
            Escala pelo maior |valor| dos dois lados, pra comparar os tamanhos. */}
        <div className="relative h-32 flex items-stretch gap-[2px]">
          <div className="absolute inset-x-0 border-t border-line-strong pointer-events-none" style={{ top: `${zeroPct}%` }} />
          {cronologico.map(c => {
            const pct = (Math.abs(c.realized) / escala) * 100
            const sobe = c.realized >= 0
            return (
              <Tooltip key={c.id} className="flex-1 min-w-0 h-full" text={
                <div className="space-y-0.5 text-[11px]">
                  <div className="font-bold text-ink-1">{MOTIVO[c.end_reason]?.label ?? 'Encerrado'}</div>
                  <div className="text-ink-3">{dataBR(c.started_at)} a {dataBR(c.ended_at)}</div>
                  <div className="text-ink-2">{c.greens} {c.greens === 1 ? 'green' : 'greens'}, entrada {fmtBRL(c.initial)}</div>
                  <div className={`font-mono font-black ${sobe ? 'text-accent-ink' : 'text-red-400'}`}>{sobe ? '+' : '−'}{fmtBRL(c.realized)}</div>
                </div>
              }>
                <div className="relative w-full h-full" aria-label={`${curta(c.ended_at)}: ${sobe ? '+' : '-'}${fmtBRL(c.realized)}`}>
                  <motion.div
                    initial={{ height: 0 }} animate={{ height: `${Math.max(2, pct)}%` }}
                    transition={{ type: 'spring', stiffness: 220, damping: 26 }}
                    style={sobe ? { bottom: `${100 - zeroPct}%` } : { top: `${zeroPct}%` }}
                    className={`absolute inset-x-0 ${sobe ? 'rounded-t bg-accent' : 'rounded-b bg-red-500/70'}`}
                  />
                </div>
              </Tooltip>
            )
          })}
        </div>
        <div className="flex justify-between text-[10px] text-ink-4 mt-1">
          <span>{curta(cronologico[0]?.ended_at ?? null)}</span>
          <span>{curta(cronologico[cronologico.length - 1]?.ended_at ?? null)}</span>
        </div>
      </div>

      {naMeta.length > 0 && (
        <div>
          <p className="text-[11px] text-ink-3 font-semibold mb-2">
            {quem === 'ia' ? 'Os caminhos da IA que bateram a meta' : 'Os seus caminhos que bateram a meta'}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {naMeta.map(c => (
              <div key={c.id} className="rounded-md border border-accent/25 bg-accent/[0.04] p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[11px] text-ink-3">{curta(c.started_at) === curta(c.ended_at) ? curta(c.ended_at) : `${curta(c.started_at)} a ${curta(c.ended_at)}`}, {c.greens} greens</p>
                    <p className="text-xs text-ink-2 mt-0.5">
                      <span className="whitespace-nowrap">{fmtBRL(c.initial)}</span> virou <b className="text-ink-1 whitespace-nowrap">{fmtBRL(c.final)}</b>
                    </p>
                  </div>
                  <div className="text-right shrink-0 font-mono">
                    <div className="text-sm font-black text-accent-ink tabular-nums">+{fmtBRL(c.realized)}</div>
                    <div className="text-[10px] text-ink-4 tabular-nums">×{(c.final / (c.initial || 1)).toFixed(1)}</div>
                  </div>
                </div>
                {!!c.steps?.length && (
                  <>
                    <div className="mt-2 flex items-end gap-[3px] h-10">
                      {[c.initial, ...c.steps.map(s => s.after)].map((v, i, arr) => (
                        <div key={i} title={i ? c.steps![i - 1].match : 'Entrada'}
                          className={`flex-1 rounded-t ${i ? 'bg-accent/80' : 'bg-ink-4/50'}`}
                          style={{ height: `${Math.max(6, (v / Math.max(...arr)) * 100)}%` }} />
                      ))}
                    </div>
                    <p className="mt-1.5 text-[10px] text-ink-4 leading-snug line-clamp-2">
                      {c.steps.map(s => s.match).join(' · ')}
                    </p>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export const MOTIVO: Record<string, { label: string; cor: string; Icone: typeof Flag }> = {
  manual: { label: 'Encerrado por você', cor: 'text-accent-ink', Icone: Flag },
  meta:   { label: 'Bateu a meta',       cor: 'text-accent-ink', Icone: Target },
  red:    { label: 'Caiu num RED',       cor: 'text-red-400',    Icone: TrendingDown },
}

export const dataBR = (iso: string | null) =>
  iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '-'

/*
 * A ESCADA · o gráfico que só a alavancagem tem.
 *
 * Curva de linha no tempo é o gráfico errado aqui. O caminho não anda por dia,
 * anda por DEGRAU: cada green reaposta o bolo inteiro, então o eixo natural é
 * a ordem dos greens, não a data. E o formato importa mais que o número · o
 * salto entre o quarto e o quinto degrau é o argumento inteiro do produto, e
 * ele só fica visível quando as barras crescem lado a lado.
 *
 * Escala pelo maior valor da série (nunca pela entrada): com o bolo composto,
 * escalar pela entrada achataria tudo depois do terceiro green.
 */
export function Escada({ entrada, steps, altura = 'h-40' }: {
  entrada: number
  steps: AlavStep[]
  /** A aba de /picks mostra a escada como contexto do pick, e ali ela é mais baixa. */
  altura?: string
}) {
  const degraus = [
    { rotulo: 'Entrada', valor: entrada, result: null as null | 'GREEN' | 'RED', match: '' },
    ...steps.map((s, i) => ({
      rotulo: s.result === 'GREEN' ? `${i + 1}º green` : 'RED',
      valor: s.result === 'GREEN' ? s.after : s.before,
      result: s.result,
      match: s.match,
    })),
  ]
  const maior = Math.max(...degraus.map(d => d.valor), entrada)

  /* Largura de leitura, e nao a largura da tela: com quatro degraus num
     monitor de 1440 as barras viravam blocos de 300px cada, e o formato da
     escada -- que e' o assunto do grafico -- se perdia em barras chapadas. */
  return (
    <div className={`flex items-end gap-1.5 max-w-xl ${altura}`}>
      {degraus.map((d, i) => {
        const alturaPct = maior > 0 ? (d.valor / maior) * 100 : 0
        const cor = d.result === 'RED' ? 'bg-red-500/70'
                  : d.result === 'GREEN' ? 'bg-orange-400'
                  : 'bg-ink-4/50'
        return (
          /* O NUMERO E O ROTULO FICAM FORA DA ESCALA (07/09).
             Eles eram irmaos da barra no mesmo flex-col, entao comiam ~26px da
             altura e a barra de 100% acabava do mesmo tamanho da de 74%: a
             escada crescia e o grafico nao mostrava. Agora so' a faixa do meio
             (flex-1) e' a area do grafico, e a porcentagem vale sobre ela. */
          <div key={i} className="flex-1 flex flex-col items-center min-w-0 h-full">
            <span className="font-mono text-[10px] text-ink-3 mb-1 tabular-nums whitespace-nowrap">
              {d.result === 'RED' ? '0' : Math.round(d.valor)}
            </span>
            <div className="flex-1 w-full flex items-end">
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: `${Math.max(3, alturaPct)}%` }}
                transition={{ delay: i * 0.06, type: 'spring', stiffness: 220, damping: 26 }}
                className={`w-full rounded-t ${cor}`}
                title={d.match || d.rotulo}
              />
            </div>
            <span className="text-[10px] text-ink-4 mt-1 truncate w-full text-center">
              {d.rotulo}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/*
 * Progresso até o fechamento automático.
 *
 * Segmentos discretos e não barra contínua: a meta é contada em GREENS, um
 * número inteiro e pequeno, e uma barra lisa sugeriria progresso fracionado
 * ("estou em 62% do caminho") que não existe · ou o green veio, ou não veio.
 */
export function ProgressoMeta({ feitos, meta }: { feitos: number; meta: number }) {
  return (
    <div className="flex gap-1.5">
      {Array.from({ length: meta }, (_, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, scaleY: 0.4 }}
          animate={{ opacity: 1, scaleY: 1 }}
          transition={{ delay: i * 0.05 }}
          className={`h-2 flex-1 rounded-full ${i < feitos ? 'bg-orange-400' : 'bg-surface-2'}`}
        />
      ))}
    </div>
  )
}

/*
 * O CAMINHO DA IA (20/10/2026, pedido do usuário: "mostra o caminho da IA se
 * não peguei o meu caminho").
 *
 * Sem caminho próprio, a aba mostrava um card vazio esperando um valor de
 * entrada · e o produto, que é a escada, ficava invisível justamente pra quem
 * ainda está decidindo entrar. Aqui é o caminho que a IA fez com os picks
 * publicados, na mesma regra do placar (fecha na meta, RED custa a entrada),
 * em reais sobre a entrada da pessoa (ou R$50 de exemplo).
 */
export function CaminhoDaIA({ c, exemplo }: {
  c: { entrada: number; meta: number; steps: AlavStep[]; passos: number; saldo: number; history: CaminhoEncerrado[] }
  /** Sem entrada própria, o valor é exemplo e o texto diz isso. */
  exemplo: boolean
}) {
  const lucro = c.saldo - c.entrada
  return (
    <div className="rounded-lg border border-orange-500/20 bg-orange-500/[0.04] p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold text-orange-400">Caminho da IA</p>
          <p className="text-[11px] text-ink-3 mt-0.5 leading-snug">
            O caminho que a IA está fazendo com os picks publicados
            {exemplo ? ', com uma entrada de exemplo de ' : ', com a sua entrada de '}
            <span className="whitespace-nowrap">{fmtBRL(c.entrada)}</span>.
          </p>
        </div>
        <div className="font-mono text-right shrink-0">
          <div className="text-xl font-black text-orange-400 tabular-nums">{fmtBRL(c.saldo)}</div>
          <div className={`text-[11px] tabular-nums ${lucro > 0 ? 'text-accent-ink' : 'text-ink-4'}`}>
            {c.passos ? `${fmtSigned(lucro)} em jogo` : 'recém-começado'}
          </div>
        </div>
      </div>
      <div>
        <div className="flex items-baseline justify-between text-[11px] mb-1.5">
          <span className="text-ink-3">Degraus até a meta</span>
          <span className="font-mono text-ink-2"><b className="text-orange-400">{c.passos}</b> de {c.meta}</span>
        </div>
        <ProgressoMeta feitos={c.passos} meta={c.meta} />
      </div>
      {c.steps.length > 0 && <Escada entrada={c.entrada} steps={c.steps} altura="h-28" />}
      {c.history.length > 0 && (
        <div className="pt-3 border-t border-orange-500/15">
          <HistoricoDeCaminhos history={c.history} quem="ia" />
        </div>
      )}
    </div>
  )
}

export function LinhaCaminho({ c, quem = 'voce' }: { c: CaminhoEncerrado; quem?: 'voce' | 'ia' }) {
  const m = MOTIVO[c.end_reason] ?? MOTIVO.manual
  const { Icone } = m
  /* "Encerrado por você" não cabe no caminho da IA: ela só fecha na meta ou no RED. */
  const rotulo = quem === 'ia' && c.end_reason === 'manual' ? 'Encerrado' : m.label
  return (
    <div className="flex items-center gap-3 py-3 border-b border-line last:border-0">
      <Icone className={`w-4 h-4 shrink-0 ${m.cor}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-1 font-semibold truncate">{rotulo}</p>
        <p className="text-[11px] text-ink-4">
          {dataBR(c.ended_at)}, entrou com {fmtBRL(c.initial)}, {c.greens}{' '}
          {c.greens === 1 ? 'green' : 'greens'} no caminho
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className={`font-mono text-sm font-black tabular-nums ${c.realized >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
          {fmtSigned(c.realized)}
        </p>
        <p className="font-mono text-[10px] text-ink-4 tabular-nums">
          {fmtUnits(c.units, 2)}
        </p>
      </div>
    </div>
  )
}
