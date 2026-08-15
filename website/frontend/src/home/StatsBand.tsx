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
 * A FAIXA FALA EM UNIDADE, NÃO EM PORCENTAGEM. Quem acompanha tipster lê lucro
 * em unidade; ROI em % é a mesma informação num idioma que o público não usa.
 * Literalmente a mesma: como toda stake do histórico vale 1u, `roi` é
 * `média_de_unidades × 100`. Por isso o tile de ROI saiu daqui em vez de somar
 * aos novos: seriam dois tiles vizinhos com o mesmo dado em roupa diferente,
 * que é pior do que não ter o segundo. O ROI continua em /resultados e
 * /performance, onde o leitor já está comparando com outras fontes.
 *
 * A quebra VIP/free NÃO é redundante com o ROI: aquele é do bolo inteiro (seis
 * pipelines), estes são por produto, que é a pergunta de quem está decidindo
 * entre o plano free e o VIP na mesma tela.
 *
 * "Ligas cobertas" também saiu: a seção Leagues fica logo abaixo, mostrando as
 * ligas com nome e escudo em vez de um número solto.
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

  const TILES = [
    {
      label: 'Lucro da IA',
      value: <NumberTicker value={lucro} formatter={v => fmtUnits(v, 1)} />,
      tone: tom(lucro),
      hint: `em ${summary.total} picks · ${plano}`,
    },
    {
      label: 'Assertividade',
      value: <NumberTicker value={wr} suffix="%" />,
      tone: wr >= 55 ? 'text-accent' : 'text-ink-1',
      // A cobertura de ligas perdeu o tile próprio para o lucro em unidades,
      // mas não o lugar: ela qualifica a assertividade (57% em 12 ligas diz
      // mais do que 57% sozinho) e continua saindo de `summary.leagues_count`,
      // nunca do tamanho de `by_league` · esse era o número que obrigava a rota
      // a montar a quebra por liga inteira só para ser contado.
      hint: leaguesCount > 0
        ? `${summary.greens} greens · ${leaguesCount} ligas`
        : `${summary.greens} greens`,
    },
    // Pipeline sem pick resolvido não vira tile de "+0,00u": some.
    ...(mediaVip !== null ? [{
      label: 'Média por pick VIP',
      value: <NumberTicker value={mediaVip} formatter={v => fmtUnits(v, 2)} />,
      tone: tom(mediaVip),
      hint: `${summary.vip_total} picks VIP`,
    }] : []),
    ...(mediaFree !== null ? [{
      label: 'Média por pick free',
      value: <NumberTicker value={mediaFree} formatter={v => fmtUnits(v, 2)} />,
      tone: tom(mediaFree),
      hint: `${summary.free_total} picks free`,
    }] : []),
  ]

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
      {/* A premissa fica embaixo dos números, não escondida num tooltip: a Banca
          sugere stake variável (1u a 10u), e sem esta linha o visitante compara
          o lucro daqui com o dele e conclui que a conta do site não fecha.
          O texto vem do backend (stake_plan.py) para não envelhecer sozinho. */}
      <p className="text-[10px] text-ink-4">
        Plano fixo de stake: {plano}. Sem stake variável, sem martingale.
      </p>
    </div>
  )
}
