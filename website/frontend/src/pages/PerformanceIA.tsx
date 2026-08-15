import { useEffect, useState } from 'react'
import { Activity, TrendingUp } from 'lucide-react'
import api from '../services/api'
import PageShell from '../components/PageShell'
import {
  Badge, Button, EmptyState, Panel, PanelHead, PickTypeBadge, ResultBadge,
  SpinnerBlock, StatTile, Table, type Column,
} from '../components/ui'
import DailyGreensChart from '../components/DailyGreensChart'
import ActivityHeatmap from '../components/ActivityHeatmap'
import { winRate as calcWinRate, fmtUnits, STAKE_LABEL_PADRAO } from '../utils/format'

/*
 * Performance da IA.
 *
 * Página pública dedicada a "a IA é boa?". Resultados já mostra o placar bruto;
 * aqui o foco é a qualidade da decisão, que é outra pergunta.
 *
 * O bloco central é o CLV (closing line value): compara a odd em que o pick
 * saiu com a odd de fechamento do mesmo mercado. É o indicador que sobrevive à
 * variância, porque não depende do jogo ter dado certo, só de termos entrado
 * num preço melhor que o que o mercado fechou.
 */

interface Summary {
  total: number; greens: number; reds: number; push: number
  /** Lucro em unidades · stake fixa de 1u por pick (ver fmtUnits). */
  profit: number; stake_total: number; roi: number
  vip_profit?: number; vip_total?: number
  free_profit?: number; free_total?: number
}
interface DayResult { match_date: string; total: number; greens: number; reds: number; profit: number }
interface LeagueResult {
  league_id: number | null; league_name: string
  total: number; greens: number; reds: number
}
interface ResultsData {
  /** Legenda do plano de stake · vem pronta do backend (stake_plan.py). */
  stake_label?: string
  summary: Summary
  by_day: DayResult[]
  by_league: LeagueResult[]
}

interface ClvRow {
  pick_type: string
  match_date: string
  home_team: string
  away_team: string
  market: string
  line: string
  odd: number
  closing_odd: number
  clv: number | null
  result: string | null
}
interface ClvData {
  available: boolean
  reason?: string
  summary: { total: number; beat_closing: number; beat_pct: number; avg_clv: number; days: number } | null
  recent: ClvRow[]
}

function ClvSection({ data, loading }: { data: ClvData | null; loading: boolean }) {
  if (loading) return <SpinnerBlock />

  if (!data?.available || !data.summary) {
    return (
      <EmptyState
        Icon={Activity}
        title="Ainda sem dados de fechamento"
        description={
          'O valor de fechamento é capturado perto do apito de cada jogo. Assim que houver '
          + 'histórico suficiente, a comparação aparece aqui.'
        }
        compact
      />
    )
  }

  const s = data.summary
  const positivo = s.avg_clv > 0

  const cols: Column<ClvRow>[] = [
    {
      key: 'jogo',
      header: 'Jogo',
      cell: r => (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <PickTypeBadge type={r.pick_type} short />
            <span className="text-xs text-ink-1 truncate">{r.home_team} x {r.away_team}</span>
          </div>
          <p className="text-[10px] text-ink-4 truncate mt-0.5">{r.market} {r.line}</p>
        </div>
      ),
    },
    {
      key: 'odd', header: 'Entrada', align: 'right', hideOnMobile: true,
      cell: r => <span className="font-mono text-xs tabular-nums">{r.odd.toFixed(2)}</span>,
    },
    {
      key: 'close', header: 'Fechamento', align: 'right', hideOnMobile: true,
      cell: r => <span className="font-mono text-xs text-ink-3 tabular-nums">{r.closing_odd.toFixed(2)}</span>,
    },
    {
      key: 'clv', header: 'CLV', align: 'right',
      cell: r => (
        <span className={`font-mono text-xs font-bold tabular-nums ${(r.clv ?? 0) > 0 ? 'text-accent' : 'text-ink-3'}`}>
          {r.clv == null ? '·' : `${r.clv > 0 ? '+' : ''}${r.clv.toFixed(1)}%`}
        </span>
      ),
    },
    {
      key: 'result', header: 'Resultado', align: 'right',
      cell: r => <ResultBadge result={r.result} />,
    },
  ]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatTile
          label="CLV médio"
          value={`${positivo ? '+' : ''}${s.avg_clv.toFixed(2)}%`}
          tone={positivo ? 'green' : 'red'}
          info="Diferença média entre a odd em que o pick saiu e a odd com que o mercado fechou. Positivo significa que a odd caiu depois da publicação · o mercado se moveu na direção da leitura da IA."
        />
        <StatTile
          label="Bateu o fechamento"
          value={`${s.beat_pct}%`}
          tone={s.beat_pct >= 50 ? 'green' : 'muted'}
          info={`Em ${s.beat_closing} de ${s.total} picks comparados, a odd publicada era melhor que a de fechamento. Acima de 50% indica que a análise chega antes do mercado.`}
        />
        <StatTile
          label="Picks comparados"
          value={String(s.total)}
          info={`Picks dos últimos ${s.days} dias com odd de fechamento capturada. Só entram os mercados em que dá para comparar a mesma linha nos dois momentos.`}
          className="col-span-2 sm:col-span-1"
        />
      </div>

      <div className="bg-surface-0 border border-line rounded-lg p-4">
        <p className="text-xs text-ink-2 leading-relaxed">
          <span className="text-ink-1 font-semibold">Como ler:</span>{' '}
          CLV positivo significa que a odd caiu depois que o pick saiu, ou seja, o mercado
          se moveu na direção da nossa leitura. É o sinal mais honesto de que a análise
          encontrou valor, porque independe do resultado do jogo.
        </p>
      </div>

      <Panel>
        <PanelHead label="Comparação pick a pick" meta={`${data.recent.length} mais recentes`} />
        <Table
          columns={cols}
          rows={data.recent}
          rowKey={(r, i) => `${r.match_date}-${i}`}
          minWidth={520}
        />
      </Panel>
    </div>
  )
}

export default function PerformanceIA() {
  const [results, setResults] = useState<ResultsData | null>(null)
  const [clv, setClv] = useState<ClvData | null>(null)
  const [loading, setLoading] = useState(true)
  const [clvLoading, setClvLoading] = useState(true)

  useEffect(() => {
    api.get('/public/results', { params: { recent_limit: 1 } })
      .then(r => setResults(r.data))
      .catch(() => setResults(null))
      .finally(() => setLoading(false))

    api.get('/public/market-movement', { params: { days: 60 } })
      .then(r => setClv(r.data))
      .catch(() => setClv(null))
      .finally(() => setClvLoading(false))
  }, [])

  const s = results?.summary
  const byDay = results?.by_day ?? []
  const byLeague = results?.by_league ?? []
  const wr = calcWinRate(s?.greens ?? 0, s?.total ?? 0) ?? 0
  const roi = Number(s?.roi ?? 0)
  const lucro = Number(s?.profit ?? 0)
  const stakeLabel = results?.stake_label ?? STAKE_LABEL_PADRAO

  return (
    <PageShell
      title="Performance da IA"
      description="Assertividade, ROI e valor de fechamento dos picks gerados pela IA. Histórico público e auditável."
      canonical="https://pickia.com.br/performance"
      width="full"
      bar={{
        back: true,
        title: 'Performance da IA',
        sub: 'Como a IA vem decidindo, não só quanto ela acertou',
        actions: <Button to="/resultados" variant="ghost" size="sm">Ver histórico bruto</Button>,
      }}
      mainClassName="space-y-10"
    >
      {loading ? (
        <SpinnerBlock />
      ) : !s || s.total === 0 ? (
        <EmptyState
          Icon={TrendingUp}
          title="Ainda não há picks suficientes"
          description="Assim que a IA publicar e resolver os primeiros picks, os indicadores aparecem aqui."
          action={{ children: 'Ver picks de hoje', to: '/picks' }}
        />
      ) : (
        <>
          <section>
            {/* Os quatro indicadores originais seguem na ordem em que sempre
                estiveram · o lucro em unidades entra como quinto, no fim, sem
                reorganizar o resto. */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              <StatTile label="Assertividade" value={`${wr}%`} tone={wr >= 55 ? 'green' : 'default'}
                info={`${s.greens} greens em ${s.total} picks resolvidos. Sozinha não diz se deu lucro: acerto alto em odd baixa rende menos que acerto médio em odd alta.`} />
              <StatTile label="Picks resolvidos" value={String(s.total)}
                info="Picks que já tiveram o resultado conferido contra a estatística oficial da partida. Pendentes ficam de fora de todos os indicadores desta página." />
              <StatTile
                label="ROI acumulado"
                value={`${roi >= 0 ? '+' : ''}${roi.toFixed(1)}%`}
                tone={roi >= 0 ? 'green' : 'red'}
                info="Retorno sobre tudo que foi arriscado. Enquanto o lucro diz quanto rendeu, o ROI diz quanto rendeu por unidade apostada · é o que permite comparar períodos de volume diferente."
              />
              <StatTile label="Ligas cobertas" value={String(byLeague.length)}
                info="Campeonatos com pelo menos um pick publicado e resolvido. Cobertura ampla é sinal de que o modelo não depende de um único torneio." />
              <StatTile
                label="Lucro da IA"
                value={fmtUnits(lucro, 1)}
                tone={lucro >= 0 ? 'green' : 'red'}
                info={`Resultado acumulado em unidades, com plano fixo de stake: ${stakeLabel}. Sem stake variável, sem martingale. Quanto vale 1u em reais depende da banca de cada um.`}
                className="col-span-2 sm:col-span-1"
              />
            </div>
          </section>

          <section>
            <div className="flex items-center gap-2 mb-4">
              <h2 className="font-display text-base font-semibold text-ink-1">Valor de fechamento</h2>
              <Badge tone="green">CLV</Badge>
            </div>
            <ClvSection data={clv} loading={clvLoading} />
          </section>

          {byDay.length > 1 && (
            <section>
              <h2 className="font-display text-base font-semibold text-ink-1 mb-4">Aproveitamento no calendário</h2>
              <Panel>
                <div className="p-5">
                  <ActivityHeatmap data={byDay} />
                </div>
              </Panel>
            </section>
          )}

          {byDay.length > 1 && (
            <section>
              <h2 className="font-display text-base font-semibold text-ink-1 mb-4">Evolução por dia</h2>
              <Panel>
                <div className="p-5">
                  <DailyGreensChart data={byDay} />
                </div>
              </Panel>
            </section>
          )}

          {byLeague.length > 0 && (
            <section>
              <h2 className="font-display text-base font-semibold text-ink-1 mb-4">Aproveitamento por liga</h2>
              <Panel>
                <PanelHead label="Win rate por campeonato" meta={`${byLeague.length} ligas`} />
                <div className="px-5 py-4 space-y-3">
                  {[...byLeague]
                    .map(lg => ({ ...lg, wr: calcWinRate(lg.greens, lg.total) ?? 0 }))
                    .sort((a, b) => b.wr - a.wr)
                    .map(lg => (
                      <div key={lg.league_id ?? lg.league_name} className="flex items-center gap-3">
                        <span className="text-[11px] text-ink-3 w-28 shrink-0 truncate">{lg.league_name}</span>
                        <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${lg.wr >= 55 ? 'bg-accent' : 'bg-ink-4'}`}
                            style={{ width: `${Math.max(2, Math.min(100, lg.wr))}%` }}
                          />
                        </div>
                        <span className="font-mono text-[11px] font-bold text-ink-2 w-9 text-right shrink-0 tabular-nums">
                          {lg.wr}%
                        </span>
                      </div>
                    ))}
                </div>
              </Panel>
            </section>
          )}
        </>
      )}
    </PageShell>
  )
}
