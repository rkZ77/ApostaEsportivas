import { motion } from 'framer-motion'
import { NumberTicker, Skeleton } from '../components/ui'
import { winRate as calcWinRate, fmtUnits, STAKE_LABEL_PADRAO } from '../utils/format'
import { fadeInUp, staggerContainer } from '../lib/motion'

/*
 * Faixa de indicadores da Home.
 *
 * Todos saem de /public/results, o mesmo endpoint que alimenta a página de
 * Resultados. Nenhum número aqui é digitado à mão: se a IA parar de publicar, a
 * faixa cai junto, e é assim que tem que ser.
 *
 * Não existe card de "usuários ativos" porque não existe essa métrica no
 * backend, e inventar um contador seria a prova social fabricada que já foi
 * removida da home em julho.
 *
 * OS QUATRO TILES SÃO OS DE SEMPRE, com uma troca só: "Ligas cobertas" saiu e
 * o lucro em unidades entrou no lugar. Quem acompanha tipster lê resultado em
 * unidade, e a contagem de ligas já é dita logo abaixo pela seção Leagues, com
 * nome e escudo, em vez de um número solto.
 *
 * Lucro TOTAL e ROI não são o mesmo número, então convivem: um é quanto rendeu,
 * o outro é quanto rendeu por unidade arriscada. O que seria redundante é ROI
 * ao lado de uma MÉDIA por pick (`roi` é a média × 100) · por isso a quebra de
 * VIP e free fica na linha de apoio, não em tiles próprios.
 */

export interface PublicSummary {
  total: number
  greens: number
  reds: number
  /** Lucro em unidades · já pesado pelo plano de stake_plan.py (ver fmtUnits). */
  profit: number
  roi: number
  /** Ligas distintas com pick resolvido · vem do mesmo SELECT do resumo. */
  leagues_count?: number
  /** Quebra por pipeline · mesmo SELECT do resumo, sem consulta extra. */
  vip_profit?: number
  vip_total?: number
  free_profit?: number
  free_total?: number
}

/** Média de unidades por pick · null quando o pipeline ainda não tem resolvido. */
function media(profit?: number, total?: number): number | null {
  if (!total || total <= 0) return null
  return Number(profit ?? 0) / total
}

export default function StatsBand({
  summary,
  /** summary.leagues_count da mesma resposta · nunca by_league.length. */
  leaguesCount,
  /** `stake_label` da resposta · plano de stake montado em stake_plan.py. */
  stakeLabel,
  loaded,
}: {
  summary: PublicSummary | null
  leaguesCount: number
  stakeLabel?: string
  loaded: boolean
}) {
  if (!loaded) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[92px]" />
        ))}
      </div>
    )
  }

  if (!summary || summary.total === 0) return null

  const wr = calcWinRate(summary.greens, summary.total) ?? 0
  const lucro = Number(summary.profit ?? 0)
  const mediaVip  = media(summary.vip_profit, summary.vip_total)
  const mediaFree = media(summary.free_profit, summary.free_total)

  const tom = (v: number) => (v >= 0 ? 'text-accent' : 'text-red-400')
  const plano = stakeLabel ?? STAKE_LABEL_PADRAO

  const roi = Number(summary.roi ?? 0)

  /* Ladrilho é número e rótulo, e mais nada.
     Nem subtítulo (empilhava texto miúdo que ninguém lê) nem ícone de ajuda
     colado no número (polui justo o que o ladrilho existe pra mostrar). O que
     precisa ser dito sobre o conjunto vai na linha de apoio, uma vez só. */
  const TILES = [
    {
      label: 'Picks publicadas',
      value: <NumberTicker value={summary.total} />,
      tone: 'text-ink-1',
    },
    {
      label: 'Assertividade',
      value: <NumberTicker value={wr} suffix="%" />,
      tone: wr >= 55 ? 'text-accent' : 'text-ink-1',
    },
    {
      label: 'ROI acumulado',
      value: (
        <NumberTicker
          value={roi}
          decimals={1}
          formatter={v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
        />
      ),
      tone: tom(roi),
    },
    {
      label: 'Lucro da IA',
      value: <NumberTicker value={lucro} formatter={v => fmtUnits(v, 1)} />,
      tone: tom(lucro),
    },
  ]

  // Quebra por produto na linha de apoio: é a pergunta de quem está decidindo
  // entre o free e o VIP, mas não vale um tile · média por pick é o ROI em
  // outra escala, e ficaria ao lado dele.
  const medias = [
    mediaVip !== null ? `VIP ${fmtUnits(mediaVip, 2)}` : null,
    mediaFree !== null ? `free ${fmtUnits(mediaFree, 2)}` : null,
  ].filter(Boolean).join(' · ')

  return (
    <div className="space-y-3">
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '0px 0px -60px 0px' }}
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
      >
        {TILES.map(({ label, value, tone }) => (
          <motion.div key={label} variants={fadeInUp} className="stat-tile text-left">
            <div className={`font-mono text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
            <div className="stat-label !mt-1.5">{label}</div>
          </motion.div>
        ))}
      </motion.div>
      {/* Linha de apoio: o plano de stake e a média por produto, juntos e uma
          vez só. A premissa precisa estar visível em algum lugar · a Banca
          sugere stake variável, e sem ela o visitante compara o lucro daqui
          com o dele e conclui que a conta do site não fecha. */}
      <p className="text-[10px] text-ink-4 leading-relaxed">
        Plano fixo de stake: {plano}.
        {leaguesCount > 0 && ` Cobertura: ${leaguesCount} ligas.`}
        {medias && ` Média por pick: ${medias}.`}
      </p>
    </div>
  )
}
