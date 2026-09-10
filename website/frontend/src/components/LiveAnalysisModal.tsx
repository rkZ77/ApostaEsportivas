import { Activity, BookOpen, Clock, Gauge, Percent, Scale, Target, TrendingUp } from 'lucide-react'
import Modal from './ui/Modal'
import { Badge } from './ui'
import MarketForm from './MarketForm'
import { explainMarket, regraDoMercado, translateLine, translateMarket } from '../utils/marketTranslate'

/*
 * "Entenda esta análise" · versão AO VIVO.
 *
 * O modal de pré-jogo (AnalysisModal) responde "por que este jogo virou pick
 * hoje": forma recente, amostra do motor, histórico do mercado. A pergunta
 * daqui é outra · o motor ao vivo decide com o jogo em andamento, então o que
 * o assinante quer saber é POR QUE NESTE MINUTO, e o que mudou desde então.
 *
 * O HISTÓRICO DOS TIMES ENTROU DEPOIS (2026-09-06, pedido do usuário). Ele
 * responde a pergunta que sobra quando o snapshot já foi lido: "esse jogo é
 * assim mesmo?". Um Over 9.5 escanteios aos 60' com 6 no placar significa uma
 * coisa se os dois times fazem 11 por jogo na competição, e outra bem
 * diferente se fazem 7 · e essa leitura é a mesma do pré-jogo, então ela usa o
 * mesmo componente e a mesma rota (`market-form`, que já sabia responder para
 * `picks_live`): últimos 10 jogos de cada time, no mando desta partida, na
 * liga e temporada desta fixture, medidos pelo contador do mercado do pick.
 *
 * Por isso a peça central é a comparação entre dois instantes:
 *   - o SNAPSHOT da criação (minuto, placar, valor observado, ritmo, pressão);
 *   - o ESTADO AGORA (minuto corrente, placar, valor observado).
 * A distância entre os dois é a informação que decide se ainda vale entrar ·
 * e era exatamente ela que estava espalhada em oito micro-rótulos de 11px no
 * rodapé do card.
 *
 * O que se compartilha com o pré-jogo é a ANATOMIA (regra do mercado primeiro,
 * depois os números, depois a conta do valor, por último a prosa do motor) e
 * a matemática do edge. O conteúdo do meio é próprio.
 */

export interface LiveAnalysisData {
  market: string
  line?: string | null
  odd: number
  probability?: number | null
  confidence?: number | null
  ev?: number | null
  reasoning?: string | null

  homeTeam: string
  awayTeam: string

  /* Snapshot da criação */
  minuteAtCreation?: number | null
  homeGoalsAtCreation?: number | null
  awayGoalsAtCreation?: number | null
  observedAtCreation?: number | null
  cornersAtCreation?: number | null
  shotsAtCreation?: number | null
  shotsOnTargetAtCreation?: number | null
  possessionHomeAtCreation?: number | null
  remainingMinutes?: number | null

  /* Leituras do motor no instante da criação */
  pressureHome?: number | null
  pressureAway?: number | null
  rhythmLevel?: string | null
  rhythmTrend?: string | null
  liveSignalScore?: number | null
  projectedTotal?: number | null
  dataFreshness?: string | null

  /* Estado atual */
  elapsed?: number | null
  homeGoals?: number | null
  awayGoals?: number | null
  currentVal?: number | null
  statLabel?: string | null
  isLive?: boolean
}

const RITMO_LABEL: Record<string, string> = {
  BAIXO: 'baixo', MEDIO: 'médio', ALTO: 'alto', MUITO_ALTO: 'muito alto',
}
const TENDENCIA_LABEL: Record<string, string> = {
  ACELERANDO: 'acelerando', DESACELERANDO: 'desacelerando',
  ESTAVEL: 'estável', INDEFINIDA: 'sem leitura',
}
const PRESSAO_LABEL: Record<string, string> = {
  BAIXA: 'baixa', MEDIA: 'média', ALTA: 'alta', MUITO_ALTA: 'muito alta',
}

/* Mesmos cortes de pressure_model.py (escala centrada em 0.5 = time médio). */
function nivelPressao(score?: number | null): string | null {
  if (score == null) return null
  if (score < 0.35) return 'BAIXA'
  if (score < 0.50) return 'MEDIA'
  if (score < 0.68) return 'ALTA'
  return 'MUITO_ALTA'
}

function impliedProb(odd: number): number {
  return odd > 1 ? (1 / odd) * 100 : 0
}

function Metric({
  Icon, label, value, tone = 'default', hint,
}: {
  Icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  tone?: 'default' | 'good' | 'muted' | 'bad'
  hint?: string
}) {
  const color = {
    default: 'text-ink-1', good: 'text-accent-ink', muted: 'text-ink-3', bad: 'text-red-400',
  }[tone]
  return (
    <div className="bg-surface-0 border border-line rounded-lg p-3">
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon className="w-3 h-3 text-ink-4" />
        <span className="stat-label !mt-0">{label}</span>
      </div>
      <div className={`font-mono text-lg font-bold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="text-[10px] text-ink-4 mt-0.5 leading-snug">{hint}</div>}
    </div>
  )
}

/** Uma coluna do "antes e agora". */
function Instante({
  titulo, minuto, placar, observado, rotuloObservado, destaque,
}: {
  titulo: string
  minuto: string
  placar: string | null
  observado: string | null
  rotuloObservado: string
  destaque?: boolean
}) {
  return (
    <div className={`rounded-lg border p-3 ${destaque ? 'border-accent/30 bg-accent/5' : 'border-line bg-surface-0'}`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="stat-label !mt-0">{titulo}</span>
        <span className="font-mono text-[11px] font-bold text-ink-2 tabular-nums">{minuto}</span>
      </div>
      <dl className="space-y-1">
        {placar && (
          <div className="flex items-baseline justify-between gap-2">
            <dt className="text-[11px] text-ink-4">Placar</dt>
            <dd className="font-mono text-sm font-bold text-ink-1 tabular-nums">{placar}</dd>
          </div>
        )}
        {observado && (
          <div className="flex items-baseline justify-between gap-2">
            <dt className="text-[11px] text-ink-4 truncate">{rotuloObservado}</dt>
            <dd className="font-mono text-sm font-bold text-ink-1 tabular-nums">{observado}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}

export default function LiveAnalysisModal({
  data, onClose, pickId,
}: {
  data: LiveAnalysisData
  onClose: () => void
  /** Id em `picks_live` · sem ele a série não tem o que pedir e some. */
  pickId?: number
}) {
  const odd = Number(data.odd)
  const implied = impliedProb(odd)
  const ourProb = data.probability != null ? Number(data.probability) * 100 : null
  const conf = data.confidence != null ? Math.round(Number(data.confidence) * 100) : null
  const ev = data.ev != null ? Number(data.ev) * 100 : null

  const probAproximada = ourProb == null
  const mostraProb = ourProb ?? conf
  const edge = mostraProb != null ? mostraProb - implied : null

  const regra = regraDoMercado(data.market, data.line ?? undefined)
  const regraTexto = !regra ? explainMarket(data.market, data.line ?? undefined) : ''

  const rotuloStat = (data.statLabel ?? 'no mercado').toLowerCase()

  /* Quanto o mercado andou desde que o pick nasceu. É o número que responde
     "ainda dá tempo?" sem obrigar a subtrair de cabeça duas leituras que
     estavam em pontas opostas do card. */
  const andou = data.currentVal != null && data.observedAtCreation != null
    ? Number(data.currentVal) - Number(data.observedAtCreation)
    : null
  const minutosCorridos = data.elapsed != null && data.minuteAtCreation != null
    ? Number(data.elapsed) - Number(data.minuteAtCreation)
    : null

  const pressaoCasa = data.pressureHome != null ? Number(data.pressureHome) : null
  const pressaoFora = data.pressureAway != null ? Number(data.pressureAway) : null
  const somaPressao = (pressaoCasa ?? 0) + (pressaoFora ?? 0)
  const fatiaCasa = somaPressao > 0 ? ((pressaoCasa ?? 0) / somaPressao) * 100 : 50

  return (
    <Modal
      onClose={onClose}
      width="lg"
      acimaDeTudo
      title="Entenda esta análise"
      description={`${data.homeTeam} x ${data.awayTeam}, ${translateMarket(data.market)}${data.line ? ` ${translateLine(data.line)}` : ''}`}
    >
      <div className="p-5 space-y-5">

        {/* A regra, antes de qualquer número · igual ao pré-jogo. */}
        {(regra || regraTexto) && (
          <div className="bg-accent/5 border border-accent/25 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2.5">
              <BookOpen className="w-3.5 h-3.5 text-accent-ink" />
              <span className="panel-label">Como este mercado funciona</span>
            </div>
            {regra ? (
              <>
                <p className="text-xs text-ink-2 leading-relaxed mb-3">{regra.oQueE}</p>
                <dl className="space-y-1.5">
                  <div className="flex items-start gap-2">
                    <dt className="text-[10px] font-black text-accent-ink w-12 shrink-0 pt-0.5">GREEN</dt>
                    <dd className="text-xs text-ink-1">{regra.green}</dd>
                  </div>
                  {regra.red && (
                    <div className="flex items-start gap-2">
                      <dt className="text-[10px] font-black text-red-400 w-12 shrink-0 pt-0.5">RED</dt>
                      <dd className="text-xs text-ink-1">{regra.red}</dd>
                    </div>
                  )}
                  {regra.devolve && (
                    <div className="flex items-start gap-2">
                      <dt className="text-[10px] font-black text-ink-4 w-12 shrink-0 pt-0.5">MEIO</dt>
                      <dd className="text-xs text-ink-2">{regra.devolve}</dd>
                    </div>
                  )}
                </dl>
              </>
            ) : (
              <p className="text-xs text-ink-2 leading-relaxed">{regraTexto}</p>
            )}
          </div>
        )}

        {/* O QUE MUDOU · a seção que não existe no card pré-jogo. */}
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="panel-label">O jogo, antes e agora</span>
            {data.isLive && <Badge tone="red">Em andamento</Badge>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Instante
              titulo="Quando nasceu"
              minuto={data.minuteAtCreation != null ? `${data.minuteAtCreation}'` : '-'}
              placar={data.homeGoalsAtCreation != null
                ? `${data.homeGoalsAtCreation} x ${data.awayGoalsAtCreation ?? 0}` : null}
              observado={data.observedAtCreation != null ? String(data.observedAtCreation) : null}
              rotuloObservado={rotuloStat}
            />
            <Instante
              destaque
              titulo="Agora"
              minuto={data.elapsed != null ? `${data.elapsed}'` : '-'}
              placar={data.homeGoals != null ? `${data.homeGoals} x ${data.awayGoals ?? 0}` : null}
              observado={data.currentVal != null ? String(data.currentVal) : null}
              rotuloObservado={rotuloStat}
            />
          </div>
          {(andou != null || minutosCorridos != null) && (
            <p className="text-[11px] text-ink-3 leading-relaxed mt-2">
              {minutosCorridos != null && minutosCorridos > 0 && (
                <>Passaram <span className="font-mono font-bold text-ink-1">{minutosCorridos} min</span> desde a publicação. </>
              )}
              {andou != null && (
                andou > 0
                  ? <>O mercado andou <span className="font-mono font-bold text-ink-1">+{andou}</span> {rotuloStat} nesse intervalo.</>
                  : <>O mercado não andou nada {rotuloStat} nesse intervalo.</>
              )}
            </p>
          )}
        </div>

        {/* Os números do valor · mesma leitura do pré-jogo. */}
        <div className="grid grid-cols-2 gap-3">
          {mostraProb != null && (
            <Metric
              Icon={Percent}
              label={`Probabilidade${probAproximada ? ' estimada' : ''}`}
              value={`${mostraProb.toFixed(1)}%`}
              tone={mostraProb >= 70 ? 'good' : 'default'}
              hint="calculada com o jogo em andamento"
            />
          )}
          <Metric
            Icon={Scale}
            label="Prob. da casa"
            value={`${implied.toFixed(1)}%`}
            tone="muted"
            hint={`implícita na odd ${odd.toFixed(2)}`}
          />
          {ev != null && (
            <Metric
              Icon={TrendingUp}
              label="Valor esperado"
              value={`${ev > 0 ? '+' : ''}${ev.toFixed(1)}%`}
              tone={ev > 0 ? 'good' : 'muted'}
              hint="retorno esperado por unidade"
            />
          )}
          {data.projectedTotal != null && (
            <Metric
              Icon={Target}
              label="Projeção do motor"
              value={Number(data.projectedTotal).toFixed(1)}
              hint={`${rotuloStat} até o apito final`}
            />
          )}
        </div>

        {/* A conta, em uma linha · com o recorte do tempo restante, que é o
            que separa a versão ao vivo da de pré-jogo. */}
        {edge != null && (
          <div className="bg-surface-0 border border-line rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Target className="w-3.5 h-3.5 text-ink-4" />
              <span className="panel-label">Por que virou pick neste minuto</span>
            </div>
            <p className="text-xs text-ink-2 leading-relaxed">
              Com o jogo no {data.minuteAtCreation != null ? `${data.minuteAtCreation}'` : 'minuto da leitura'},
              o modelo estimou <span className="font-mono text-ink-1">{mostraProb!.toFixed(1)}%</span> de
              chance, e a odd {odd.toFixed(2)} pagava como se fosse{' '}
              <span className="font-mono text-ink-1">{implied.toFixed(1)}%</span>.
              {edge > 0 ? (
                <>
                  {' '}A diferença de{' '}
                  <span className="font-mono text-accent-ink">{edge.toFixed(1)} pontos</span>{' '}
                  é o valor que o pick busca capturar
                  {data.remainingMinutes != null && (
                    <> nos <span className="font-mono text-ink-1">{data.remainingMinutes} min</span> que restavam</>
                  )}.
                </>
              ) : (
                <> Sem diferença a nosso favor, o pick não seria publicado.</>
              )}
            </p>
          </div>
        )}

        {/* Leitura de campo · ritmo, sinais e pressão. */}
        {(data.rhythmLevel || data.liveSignalScore != null || pressaoCasa != null) && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-3.5 h-3.5 text-ink-4" />
              <span className="panel-label">O que o motor leu em campo</span>
            </div>
            <div className="bg-surface-0 border border-line rounded-lg p-4 space-y-3">
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {data.rhythmLevel && (
                  <div>
                    <div className="stat-label !mt-0">Ritmo</div>
                    <div className="text-sm font-bold text-ink-1">
                      {RITMO_LABEL[data.rhythmLevel] ?? data.rhythmLevel.toLowerCase()}
                      {data.rhythmTrend && data.rhythmTrend !== 'INDEFINIDA' && (
                        <span className={
                          data.rhythmTrend === 'ACELERANDO' ? ' text-green-400'
                            : data.rhythmTrend === 'DESACELERANDO' ? ' text-amber-400' : ' text-ink-3'}>
                          {' '}{TENDENCIA_LABEL[data.rhythmTrend] ?? data.rhythmTrend.toLowerCase()}
                        </span>
                      )}
                    </div>
                  </div>
                )}
                {data.liveSignalScore != null && (
                  <div>
                    <div className="stat-label !mt-0">Sinais</div>
                    <div className="font-mono text-sm font-bold text-ink-1 tabular-nums">
                      {(Number(data.liveSignalScore) * 100).toFixed(0)}%
                    </div>
                  </div>
                )}
                {data.possessionHomeAtCreation != null && (
                  <div>
                    <div className="stat-label !mt-0">Posse na criação</div>
                    <div className="font-mono text-sm font-bold text-ink-1 tabular-nums">
                      {Number(data.possessionHomeAtCreation).toFixed(0)}% {data.homeTeam}
                    </div>
                  </div>
                )}
                {data.shotsOnTargetAtCreation != null && (
                  <div>
                    <div className="stat-label !mt-0">Chutes no gol</div>
                    <div className="font-mono text-sm font-bold text-ink-1 tabular-nums">
                      {data.shotsOnTargetAtCreation}
                      {data.shotsAtCreation != null && <span className="text-ink-4"> / {data.shotsAtCreation}</span>}
                    </div>
                  </div>
                )}
                {data.cornersAtCreation != null && (
                  <div>
                    <div className="stat-label !mt-0">Escanteios</div>
                    <div className="font-mono text-sm font-bold text-ink-1 tabular-nums">
                      {data.cornersAtCreation}
                    </div>
                  </div>
                )}
              </div>

              {pressaoCasa != null && pressaoFora != null && (
                <div>
                  <div className="flex items-baseline justify-between text-[10px] text-ink-4 mb-1.5">
                    <span>Pressão ofensiva</span>
                    <span className="tabular-nums">
                      {pressaoCasa.toFixed(2)} {PRESSAO_LABEL[nivelPressao(pressaoCasa) ?? ''] ?? ''}
                      {' / '}
                      {pressaoFora.toFixed(2)} {PRESSAO_LABEL[nivelPressao(pressaoFora) ?? ''] ?? ''}
                    </span>
                  </div>
                  <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-3/60">
                    <div className="bg-accent/70" style={{ width: `${fatiaCasa}%` }} />
                    <div className="bg-ink-4/40" style={{ width: `${100 - fatiaCasa}%` }} />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-ink-4 mt-1">
                    <span className="truncate max-w-[45%]">{data.homeTeam}</span>
                    <span className="truncate max-w-[45%] text-right">{data.awayTeam}</span>
                  </div>
                </div>
              )}

              {data.dataFreshness && data.dataFreshness !== 'FRESH' && (
                <p className="flex items-center gap-1.5 text-[11px] text-amber-400">
                  <Clock className="w-3 h-3 shrink-0" />
                  A leitura usada foi marcada como {data.dataFreshness.toLowerCase()}: o provedor
                  atrasou a folha do jogo nesse instante.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Prosa do motor, por último · igual ao pré-jogo. */}
        {data.reasoning && (
          <div>
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="panel-label">Leitura do jogo</span>
              <Badge tone="neutral">Motor ao vivo</Badge>
            </div>
            <div className="bg-surface-0 border border-line rounded-lg p-4">
              <p className="text-xs text-ink-2 leading-relaxed whitespace-pre-line">
                {data.reasoning}
              </p>
            </div>
          </div>
        )}

        {/* Depois do snapshot e da conta do valor, na mesma ordem do modal de
            pré-jogo: primeiro por que ESTE minuto, depois como o jogo dos dois
            times costuma ser. */}
        {pickId != null && <MarketForm pickId={pickId} pickType="live" />}

        <p className="flex items-start gap-1.5 text-[10px] text-ink-4 leading-relaxed">
          <Gauge className="w-3 h-3 mt-0.5 shrink-0" />
          <span>
            Ao vivo a linha e a odd se movem a cada minuto. A odd mostrada é a do instante da
            publicação. Confira o preço na casa antes de entrar. O histórico de acertos e erros
            do motor ao vivo fica na página de Resultados.
          </span>
        </p>
      </div>
    </Modal>
  )
}
