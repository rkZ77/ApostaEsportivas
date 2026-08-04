import { motion } from 'framer-motion'
import { NumberTicker, Skeleton } from '../components/ui'
import { winRate as calcWinRate } from '../utils/format'
import { fadeInUp, staggerContainer } from '../lib/motion'

/*
 * Faixa de indicadores da Home.
 *
 * Todos os quatro saem de /public/results, o mesmo endpoint que alimenta a
 * página de Resultados. Nenhum número aqui é digitado à mão: se a IA parar de
 * publicar, a faixa cai junto, e é assim que tem que ser.
 *
 * Não existe card de "usuários ativos" porque não existe essa métrica no
 * backend, e inventar um contador seria a prova social fabricada que já foi
 * removida da home em julho.
 */

export interface PublicSummary {
  total: number
  greens: number
  reds: number
  profit: number
  roi: number
}

export default function StatsBand({
  summary,
  leaguesCount,
  loaded,
}: {
  summary: PublicSummary | null
  /** by_league.length da mesma resposta. */
  leaguesCount: number
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
      hint: `${summary.greens} greens`,
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
      tone: roi >= 0 ? 'text-accent' : 'text-red-400',
      hint: 'sobre o total apostado',
    },
    {
      label: 'Ligas cobertas',
      value: <NumberTicker value={leaguesCount} />,
      tone: 'text-ink-1',
      hint: 'temporadas em andamento',
    },
  ]

  return (
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
  )
}
