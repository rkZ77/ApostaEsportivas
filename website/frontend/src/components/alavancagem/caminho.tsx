import { motion } from 'framer-motion'
import { Flag, Target, TrendingDown } from 'lucide-react'
import { fmtBRL, fmtSigned, fmtUnits } from '../../utils/format'

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
            <span className="text-[9px] text-ink-4 mt-1 truncate w-full text-center">
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

export function LinhaCaminho({ c }: { c: CaminhoEncerrado }) {
  const m = MOTIVO[c.end_reason] ?? MOTIVO.manual
  const { Icone } = m
  return (
    <div className="flex items-center gap-3 py-3 border-b border-line last:border-0">
      <Icone className={`w-4 h-4 shrink-0 ${m.cor}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-1 font-semibold truncate">{m.label}</p>
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
