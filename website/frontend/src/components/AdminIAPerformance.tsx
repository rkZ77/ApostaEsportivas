import { useEffect, useState } from 'react'
import { Brain, ShieldAlert, TriangleAlert } from 'lucide-react'
import api from '../services/api'
import { Badge, EmptyState, Panel, PanelHead, PillGroup, SpinnerBlock, StatTile, Table, type Column } from './ui'

/*
 * Aba "IA" do painel admin.
 *
 * ORDEM DA TELA, e por quê. Ela abre no resultado POR MERCADO, não no ranking
 * de modelos. O ranking respondia uma pergunta que quase não tem resposta hoje
 * (a amostra de vetos é de 3 a 8 picks por fluxo, e 215 das 353 pernas dos
 * últimos 60 dias não têm parecer nenhum), enquanto "escanteio está dando
 * prejuízo há dois meses" é acionável na mesma hora.
 *
 * O que esta tela NÃO é: um ranking de "qual IA gera pick melhor". Nenhuma IA
 * gera pick aqui. O motor é determinístico e escolhe sozinho; o modelo entra
 * depois, só para aprovar ou vetar o que o motor já decidiu (AI_REVIEW.md).
 *
 * Então a pergunta com resposta é outra: o veto do modelo separa pick ruim de
 * pick bom? Como o gate roda em modo sombra, o pick vetado é publicado assim
 * mesmo e a gente vê no que ele deu. Se o que o modelo quis vetar deu mais red
 * que o que ele aprovou, o veto está certo e vale ligar o enforce. Se deu
 * menos, ligar o enforce derrubaria justamente os melhores picks.
 *
 * A comparação entre modelos só vale dentro do mesmo pipeline: cada fluxo tem
 * provider próprio e dificuldade própria, então o total por modelo mistura
 * mercados diferentes. Por isso o recorte por pipeline vem logo abaixo.
 */

interface Bucket {
  n: number; green: number; red: number; push: number; pendentes: number
  resolvidos: number; hit: number | null; lucro: number; roi: number | null; clv: number | null
}
interface Modelo {
  provider: string | null; model: string | null
  aprovados: Bucket; vetados: Bucket
  lift: number | null; economia_do_veto: number | null
  reviews?: number; cache?: number; chamadas?: number; vetos?: number
  falhas?: number; taxa_veto?: number | null; pipelines?: string[]
}
interface PorPipeline extends Modelo { pick_type: string }
interface PorMercado {
  market_type: string; label: string
  todos: Bucket; aprovados: Bucket; vetados: Bucket
}
interface Performance {
  days: number
  migration_pending?: boolean
  cobertura: {
    pernas?: number; com_parecer?: number; sem_parecer?: number
    autor_gravado?: number; autor_inferido?: number; autor_desconhecido?: number
  }
  modelos: Modelo[]
  por_mercado: PorMercado[]
  por_pipeline: PorPipeline[]
  falhas: Array<{ status: string; n: number }>
}

interface AIReviewStatus {
  config: { environment?: string; mode?: string; daily_limit?: number }
  events: Array<{
    pipeline: string; mode: string; provider: string; model: string; status: string
    decision: string; risk_level: string | null; cached: boolean
    review: { reasons?: string[] }; created_at: string
  }>
  migration_pending?: boolean
}

const PERIODOS: Array<{ value: string; label: string }> = [
  { value: '30', label: '30 dias' },
  { value: '60', label: '60 dias' },
  { value: '90', label: '90 dias' },
  { value: '180', label: '180 dias' },
]

const PICK_LABEL: Record<string, string> = {
  vip: 'VIP', free: 'Dica do Dia', multipla: 'Múltiplas',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
}

// Abaixo disso o número é ruído. Uma amostra de 3 picks vetados vira 0% ou
// 100% de acerto por acaso, e o painel passaria a recomendar ligar o enforce
// com base em nada.
const AMOSTRA_MINIMA = 8

const pct = (v: number | null | undefined) => (v == null ? '·' : `${v.toFixed(1)}%`)
const sinal = (v: number | null | undefined, casas = 1) =>
  v == null ? '·' : `${v > 0 ? '+' : ''}${v.toFixed(casas)}`

/** Leitura em uma frase do que o par (aprovados, vetados) está dizendo. */
function veredito(m: Modelo): { texto: string; tom: 'green' | 'red' | 'neutral' | 'muted' } {
  if (m.lift == null) {
    return { texto: 'Ainda sem picks vetados e aprovados resolvidos no período.', tom: 'muted' }
  }
  if (m.vetados.resolvidos < AMOSTRA_MINIMA) {
    return {
      texto: `Só ${m.vetados.resolvidos} veto(s) resolvido(s). Amostra pequena demais para concluir.`,
      tom: 'muted',
    }
  }
  if (m.lift > 5) {
    return {
      texto: `O que este modelo vetou acertou ${pct(m.vetados.hit)} contra ${pct(m.aprovados.hit)} do que ele aprovou. O veto está separando certo.`,
      tom: 'green',
    }
  }
  if (m.lift < -5) {
    return {
      texto: `O que ele vetou acertou MAIS (${pct(m.vetados.hit)}) que o que aprovou (${pct(m.aprovados.hit)}). Ligar o enforce derrubaria pick bom.`,
      tom: 'red',
    }
  }
  return {
    texto: 'Aprovados e vetados acertam quase igual. O veto não está agregando informação.',
    tom: 'neutral',
  }
}

function CardModelo({ m }: { m: Modelo }) {
  const v = veredito(m)
  const cor = {
    green: 'border-green-500/40 bg-green-500/5',
    red: 'border-red-500/40 bg-red-500/5',
    neutral: 'border-orange-500/30 bg-orange-500/5',
    muted: 'border-line',
  }[v.tom]

  return (
    <div className={`rounded-lg border p-4 ${cor}`}>
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="min-w-0">
          <p className="font-mono text-sm font-bold text-ink-1 break-all">{m.model ?? 'sem modelo'}</p>
          <p className="text-[11px] text-ink-4 mt-0.5">
            {m.provider ?? 'provider desconhecido'}
            {m.pipelines?.length ? ` · ${m.pipelines.join(', ')}` : ''}
          </p>
        </div>
        {m.lift != null && m.vetados.resolvidos >= AMOSTRA_MINIMA && (
          <Badge tone={m.lift > 5 ? 'green' : m.lift < -5 ? 'red' : 'neutral'}>
            {m.lift > 0 ? 'veto útil' : 'veto atrapalha'} {sinal(m.lift)} p.p.
          </Badge>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="rounded-md bg-surface-0 border border-line p-3">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide mb-1">Aprovou</p>
          <p className="font-mono text-xl font-bold text-ink-1">{pct(m.aprovados.hit)}</p>
          <p className="text-[10px] text-ink-4 mt-0.5">
            {m.aprovados.green}G · {m.aprovados.red}R
            {m.aprovados.pendentes > 0 && ` · ${m.aprovados.pendentes} pend.`}
          </p>
        </div>
        <div className="rounded-md bg-surface-0 border border-line p-3">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide mb-1">Quis vetar</p>
          <p className="font-mono text-xl font-bold text-ink-1">{pct(m.vetados.hit)}</p>
          <p className="text-[10px] text-ink-4 mt-0.5">
            {m.vetados.green}G · {m.vetados.red}R
            {m.vetados.pendentes > 0 && ` · ${m.vetados.pendentes} pend.`}
          </p>
        </div>
      </div>

      <p className="text-[11px] text-ink-2 leading-relaxed mb-3">{v.texto}</p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-[11px] pt-3 border-t border-line">
        <div>
          <p className="text-ink-4">Chamadas</p>
          <p className="font-mono text-ink-1 font-semibold">
            {m.chamadas ?? '·'}
            {m.cache ? <span className="text-ink-4 font-normal"> +{m.cache} cache</span> : null}
          </p>
        </div>
        <div>
          <p className="text-ink-4">Taxa de veto</p>
          <p className="font-mono text-ink-1 font-semibold">{pct(m.taxa_veto)}</p>
        </div>
        <div>
          <p className="text-ink-4">Lucro aprovados</p>
          <p className={`font-mono font-semibold ${m.aprovados.lucro >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {sinal(m.aprovados.lucro, 2)}u
          </p>
        </div>
        <div>
          <p className="text-ink-4">Veto teria poupado</p>
          <p className={`font-mono font-semibold ${
            (m.economia_do_veto ?? 0) > 0 ? 'text-green-400'
              : (m.economia_do_veto ?? 0) < 0 ? 'text-red-400' : 'text-ink-1'
          }`}>
            {m.economia_do_veto == null ? '·' : `${sinal(m.economia_do_veto, 2)}u`}
          </p>
        </div>
      </div>

      {(m.falhas ?? 0) > 0 && (
        <p className="text-[11px] text-orange-400 mt-3 flex items-center gap-1.5">
          <TriangleAlert className="w-3 h-3 shrink-0" />
          {m.falhas} revisão(ões) sem parecer válido. O gate falha aberto, então esses picks saíram sem revisão.
        </p>
      )}
    </div>
  )
}

export default function AdminIAPerformance({ status }: { status: AIReviewStatus | null }) {
  const [dias, setDias] = useState<string>('60')
  const [data, setData] = useState<Performance | null>(null)
  const [loading, setLoading] = useState(true)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    setLoading(true)
    setErro(false)
    api.get('/admin/ai-performance', { params: { days: Number(dias) } })
      .then(r => setData(r.data))
      .catch(() => { setData(null); setErro(true) })
      .finally(() => setLoading(false))
  }, [dias])

  const modo = status?.config.mode ?? 'off'
  const cobertura = data?.cobertura ?? {}
  const semAutor = cobertura.autor_desconhecido ?? 0

  const colsPipeline: Column<PorPipeline>[] = [
    {
      key: 'pipeline',
      header: 'Pipeline',
      cell: r => (
        <div className="min-w-0">
          <p className="text-xs text-ink-1 font-semibold">{PICK_LABEL[r.pick_type] ?? r.pick_type}</p>
          <p className="font-mono text-[10px] text-ink-4 truncate">{r.model ?? 'sem modelo'}</p>
        </div>
      ),
    },
    {
      key: 'aprovados', header: 'Aprovou', align: 'right',
      cell: r => (
        <div>
          <span className="font-mono text-xs font-bold text-ink-1 tabular-nums">{pct(r.aprovados.hit)}</span>
          <p className="text-[10px] text-ink-4">{r.aprovados.resolvidos} picks</p>
        </div>
      ),
    },
    {
      key: 'vetados', header: 'Quis vetar', align: 'right',
      cell: r => (
        <div>
          <span className="font-mono text-xs font-bold text-ink-1 tabular-nums">{pct(r.vetados.hit)}</span>
          <p className="text-[10px] text-ink-4">{r.vetados.resolvidos} picks</p>
        </div>
      ),
    },
    {
      key: 'lift', header: 'Veto', align: 'right',
      cell: r => (
        <span className={`font-mono text-xs font-bold tabular-nums ${
          r.lift == null || r.vetados.resolvidos < AMOSTRA_MINIMA ? 'text-ink-4'
            : r.lift > 0 ? 'text-green-400' : 'text-red-400'
        }`}>
          {r.lift == null ? '·' : sinal(r.lift)}
        </span>
      ),
    },
    {
      key: 'clv', header: 'CLV', align: 'right', hideOnMobile: true,
      cell: r => (
        <span className="font-mono text-xs text-ink-3 tabular-nums">
          {r.aprovados.clv == null ? '·' : `${sinal(r.aprovados.clv, 2)}%`}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="card p-4">
        <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
          <div className="min-w-0">
            <h2 className="text-xs font-semibold text-ink-3 flex items-center gap-1.5">
              <Brain className="w-3.5 h-3.5" /> Mercados e revisão da IA
            </h2>
            {/* A frase mais importante da tela. Sem ela, tudo aqui é lido como
                "ranking de qual IA gera pick melhor", que é uma pergunta que
                não existe neste produto. */}
            <p className="text-[11px] text-ink-4 mt-1 leading-relaxed max-w-2xl">
              <span className="text-ink-2 font-semibold">Nenhuma IA escolhe pick aqui.</span>{' '}
              Quem decide é o motor estatístico, sozinho. A IA entra depois e só pode vetar o que o
              motor já escolheu · e hoje nem isso, porque está em modo sombra: o veto é anotado, mas
              o pick sai do mesmo jeito.
            </p>
          </div>
          <span className={`text-xs font-bold px-2 py-1 rounded shrink-0 ${
            modo === 'enforce' ? 'bg-orange-500/15 text-orange-300' : 'bg-blue-500/15 text-blue-300'
          }`}>
            {modo === 'enforce' ? 'VETO ATIVO' : modo === 'off' ? 'DESLIGADO' : 'SOMBRA'}
          </span>
        </div>
        <PillGroup options={PERIODOS} value={dias} onChange={setDias} />
      </div>

      {/* ── Mercado por mercado · o que dá e o que não dá dinheiro ───────────
          Vem PRIMEIRO porque é a única pergunta desta tela que muda o que se
          faz amanhã de manhã. "Qual modelo revisa melhor" é interessante;
          "escanteio está sangrando há 60 dias" é acionável. */}
      {!loading && !erro && !!data?.por_mercado?.length && (
        <Panel>
          <PanelHead label="Resultado por mercado" meta={`${data.days} dias · todos os picks`} />
          <div className="px-4 py-3 border-b border-line">
            <p className="text-[11px] text-ink-4 leading-relaxed">
              Todo pick do período, tenha a IA olhado ou não. Do pior pro melhor em unidades ·
              lucro é o que importa, não taxa de acerto: mercado com 55% de acerto em odd baixa
              perde dinheiro.
            </p>
          </div>
          <div className="divide-y divide-line">
            {data.por_mercado.map(m => {
              const t = m.todos
              const ganha = t.lucro > 0
              const relevante = t.resolvidos >= AMOSTRA_MINIMA
              return (
                <div key={m.market_type} className="px-4 py-3 flex items-center gap-3">
                  <div className={`w-1 self-stretch rounded-full shrink-0 ${
                    !relevante ? 'bg-surface-3' : ganha ? 'bg-green-500' : 'bg-red-500'}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-ink-1 truncate">{m.label}</p>
                    <p className="text-[10px] text-ink-4">
                      {t.resolvidos} resolvido(s) · {t.green}G {t.red}R
                      {t.pendentes > 0 && ` · ${t.pendentes} pend.`}
                      {!relevante && ' · amostra pequena'}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className={`font-mono text-sm font-black tabular-nums ${
                      !relevante ? 'text-ink-3' : ganha ? 'text-green-400' : 'text-red-400'}`}>
                      {sinal(t.lucro, 2)}u
                    </p>
                    <p className="text-[10px] text-ink-4 tabular-nums">
                      {pct(t.hit)} acerto · ROI {pct(t.roi)}
                    </p>
                  </div>
                  {/* Só aparece onde a IA de fato opinou · em branco não é
                      zero, é "ela nunca viu este mercado". */}
                  <div className="hidden sm:block text-right shrink-0 w-24 border-l border-line pl-3">
                    <p className="text-[10px] text-ink-4">a IA viu</p>
                    <p className="font-mono text-[11px] text-ink-2 tabular-nums">
                      {m.aprovados.n + m.vetados.n === 0
                        ? '·'
                        : `${m.aprovados.n} ok / ${m.vetados.n} veto`}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        </Panel>
      )}

      {modo === 'enforce' && (
        <div className="rounded-lg border border-orange-500/30 bg-orange-500/5 p-4 flex gap-2.5">
          <ShieldAlert className="w-4 h-4 text-orange-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-ink-2 leading-relaxed">
            <span className="font-semibold text-ink-1">Coluna "quis vetar" para de crescer no enforce.</span>{' '}
            Com o veto ativo o pick vetado não é publicado, então nunca se descobre no que ele daria.
            É o modo sombra que produz a comparação desta tela. Para reavaliar os modelos, volte um
            período para sombra.
          </p>
        </div>
      )}

      {loading ? <SpinnerBlock /> : erro ? (
        <EmptyState Icon={TriangleAlert} title="Não foi possível carregar" compact
          description="A consulta de desempenho por modelo falhou. Tente recarregar." />
      ) : data?.migration_pending ? (
        <EmptyState Icon={Brain} title="Aguardando a migração do ledger" compact
          description={'As colunas de autoria da revisão entram em picks_ledger na próxima execução de '
            + '"Atualizar Resultados". Rode uma vez e esta tela passa a ter dado.'} />
      ) : !data?.modelos.length ? (
        <EmptyState Icon={Brain} title="Nenhuma revisão registrada no período" compact
          description="Assim que os pipelines rodarem com o gate ligado, a comparação aparece aqui." />
      ) : (
        <>
          <div>
            <h3 className="text-xs font-semibold text-ink-3 mb-1">O veto da IA acerta?</h3>
            <p className="text-[11px] text-ink-4 leading-relaxed mb-3 max-w-2xl">
              Como o gate está em sombra, o pick vetado é publicado assim mesmo · dá pra ver no que
              ele deu. Se o que o modelo quis vetar deu mais red que o que ele aprovou, o veto está
              separando certo e vale ligar. Se deu menos, ligar derrubaria justamente os melhores.
              {' '}
              <span className="text-ink-3">
                Hoje a amostra de vetos é pequena na maioria dos fluxos · onde estiver escrito
                &quot;amostra pequena&quot;, o número ainda não decide nada.
              </span>
            </p>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.modelos.map(m => <CardModelo key={`${m.provider}-${m.model}`} m={m} />)}
          </div>

          <Panel>
            <PanelHead
              label="Por pipeline"
              meta="a comparação que vale"
            />
            <div className="px-4 py-3 border-b border-line">
              <p className="text-[11px] text-ink-4 leading-relaxed">
                Cada fluxo tem provider próprio e dificuldade própria. Comparar dois modelos pelo
                total mistura mercados diferentes; a leitura honesta é dentro da mesma linha.
              </p>
            </div>
            {data.por_pipeline.length ? (
              <Table columns={colsPipeline} rows={data.por_pipeline}
                rowKey={(r, i) => `${r.pick_type}-${r.model}-${i}`} minWidth={520} />
            ) : (
              <p className="text-xs text-ink-4 px-4 py-6 text-center">Sem picks resolvidos com parecer no período.</p>
            )}
          </Panel>

          <Panel>
            <PanelHead label="Cobertura do gate" meta={`${data.days} dias`} />
            <div className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
              <StatTile label="Pernas no período" value={String(cobertura.pernas ?? 0)} />
              <StatTile label="Com parecer" value={String(cobertura.com_parecer ?? 0)}
                hint="a IA de fato opinou" />
              <StatTile label="Sem parecer" value={String(cobertura.sem_parecer ?? 0)}
                tone={(cobertura.sem_parecer ?? 0) > (cobertura.com_parecer ?? 0) ? 'red' : 'muted'}
                hint="gate off, teto do dia ou falha" />
              <StatTile label="Autoria inferida" value={String(cobertura.autor_inferido ?? 0)}
                hint="pick antigo, modelo deduzido" />
            </div>
            {semAutor > 0 && (
              <p className="text-[11px] text-ink-4 px-4 pb-4">
                {semAutor} pick(s) com parecer mas sem como descobrir qual modelo o emitiu. Ficam
                fora das contas acima em vez de entrar num modelo por chute.
              </p>
            )}
            {data.falhas.length > 0 && (
              <div className="px-4 pb-4">
                <p className="text-[11px] text-ink-3 font-semibold mb-2">Por que ficou sem parecer</p>
                <div className="flex flex-wrap gap-2">
                  {data.falhas.map(f => (
                    <span key={f.status} className="text-[10px] font-mono px-2 py-1 rounded bg-surface-1 text-ink-2">
                      {f.status} · {f.n}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </Panel>
        </>
      )}

      <Panel>
        <PanelHead label="Últimas revisões" meta={`limite ${status?.config.daily_limit ?? 0}/dia`} />
        <div className="divide-y divide-line max-h-72 overflow-y-auto">
          {(status?.events ?? []).map((event, index) => (
            <div key={`${event.created_at}-${index}`} className="px-4 py-2 text-[11px] flex gap-2 text-ink-2 items-baseline">
              <span className={event.decision === 'reject' ? 'text-red-400 font-bold shrink-0' : 'text-green-400 font-bold shrink-0'}>
                {event.decision === 'reject' ? 'VETADO' : 'OK'}
              </span>
              <span className="shrink-0">{event.pipeline}</span>
              <span className="font-mono text-ink-4 shrink-0 hidden sm:inline">{event.model}</span>
              <span className="text-ink-4 shrink-0">{event.cached ? 'cache' : 'novo'}</span>
              <span className="ml-auto truncate text-right">{event.review?.reasons?.[0] ?? event.status}</span>
            </div>
          ))}
          {!status?.events?.length && (
            <p className="text-xs text-ink-4 px-4 py-6 text-center">Sem revisões registradas ainda.</p>
          )}
        </div>
      </Panel>
    </div>
  )
}
