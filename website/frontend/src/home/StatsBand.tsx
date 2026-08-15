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
  /** Lucro em unidades · stake fixa de 1u por pick (ver fmtUnits). */
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

  const TILES = [
    {
      label: 'Picks publicadas',
      value: <NumberTicker value={summary.total} />,
      tone: 'text-ink-1',
      hint: 'no histórico auditável',
    },
    {
      label: 'Assertividade',
      value: <NumberTicker value={wr} suffix="%" />,
      tone: wr >= 55 ? 'text-accent' : 'text-ink-1',
      // A cobertura de ligas perdeu o tile próprio para o lucro, mas não o
      // lugar: ela qualifica a assertividade (67% em 6 ligas diz mais do que
      // 67% sozinho) e continua saindo de `summary.leagues_count`, nunca do
      // tamanho de `by_league` · esse era o número que obrigava a rota a montar
      // a quebra por liga inteira só para ser contado.
      hint: leaguesCount > 0
        ? `${summary.greens} greens · ${leaguesCount} ligas`
        : `${summary.greens} greens`,
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
      hint: 'sobre o total apostado',
    },
    {
      label: 'Lucro da IA',
      value: <NumberTicker value={lucro} formatter={v => fmtUnits(v, 1)} />,
      tone: tom(lucro),
      hint: plano,
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
        {TILES.map(({ label, value, tone, hint }) => (
          <motion.div key={label} variants={fadeInUp} className="stat-tile text-left">
            <div className={`font-mono text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
            <div className="stat-label !mt-1.5">{label}</div>
            <div className="text-[10px] text-ink-4 mt-0.5">{hint}</div>
          </motion.div>
        ))}
      </motion.div>
      {/* Linha de apoio: média por produto. Some inteira quando nenhum dos dois
          pipelines tem pick resolvido. */}
      {medias && (
        <p className="text-[10px] text-ink-4">
          Média por pick · {medias}
        </p>
      )}
    </div>
  )
}
