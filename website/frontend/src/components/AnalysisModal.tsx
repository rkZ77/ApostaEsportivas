import { BookOpen, Percent, Target, TrendingUp, Scale } from 'lucide-react'
import Modal from './ui/Modal'
import { Badge } from './ui'
import { explainMarket, regraDoMercado, translateLine, translateMarket } from '../utils/marketTranslate'
import MarketForm from './MarketForm'

/*
 * "Entenda esta análise".
 *
 * Mostra os números que sustentaram o pick e o texto que o motor produziu, sem
 * pedir nada novo à API: confiança, probabilidade estimada, odd, EV e o
 * reasoning já vêm no mesmo payload que desenha o card.
 *
 * A leitura é sempre a mesma conta, e ela fica explícita no rodapé do modal:
 * vale a pena quando a nossa probabilidade é maior que a probabilidade
 * implícita na odd. Sem isso o número de EV vira só mais um selo.
 *
 * A explicação das REGRAS do mercado abre o modal, antes dos números. Ela
 * existia só no ícone de informação ao lado da linha, o que colocava duas
 * perguntas diferentes em dois lugares diferentes: "o que preciso que aconteça
 * para ganhar" (regra) e "por que a IA acha que acontece" (análise). A
 * primeira vem antes, porque sem ela a segunda não quer dizer nada · não
 * adianta saber que a probabilidade é 70% sem saber 70% de quê.
 *
 * Continua também no ícone, que serve à leitura rápida na lista sem abrir modal.
 */

export interface AnalysisData {
  /** Já traduzido, para exibir. */
  market: string
  line?: string | null
  /**
   * Mercado e linha CRUS, como vieram da API ("Cards Over/Under", "Over 4.5").
   *
   * Separados dos traduzidos de propósito: explainMarket casa por chave em
   * inglês, então passar "Cartões Mais/Menos" para ele não bate com nada e cai
   * no texto genérico, em silêncio. Ausentes, a seção de regra some, que é
   * melhor do que uma explicação vaga.
   */
  marketRaw?: string | null
  lineRaw?: string | null
  odd: number
  confidence?: number | null
  probability?: number | null
  ev?: number | null
  reasoning?: string | null
  updatedAt?: string | null
  /**
   * Identidade do pick, pra buscar a forma recente do mercado.
   *
   * Opcionais porque múltipla e alavancagem não têm UMA série que descreva o
   * bilhete: são pernas de mercados diferentes. Sem eles o bloco some, em vez
   * de desenhar a série de uma perna e passar por ser a do conjunto.
   */
  pickId?: number
  pickType?: string
  /**
   * Pernas do bilhete (múltipla, alavancagem), cruas.
   *
   * Sem isto os dois recebiam um modal degradado: sem regra de mercado e sem
   * forma recente, porque nenhuma das duas descreve um bilhete de vários
   * mercados. Mas ficar sem explicação nenhuma era pior · são justamente os
   * tipos em que o apostador entende menos o que precisa acontecer. A regra
   * aparece PERNA A PERNA, que é a versão honesta de "igual aos outros".
   */
  legs?: Array<{ market?: string | null; line?: string | null; odd?: number | null }>
}

/** Probabilidade que a casa está embutindo na odd. */
function impliedProb(odd: number): number {
  return odd > 1 ? (1 / odd) * 100 : 0
}

function Metric({
  Icon, label, value, tone = 'default', hint,
}: {
  Icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  tone?: 'default' | 'good' | 'muted'
  hint?: string
}) {
  const color = { default: 'text-ink-1', good: 'text-accent', muted: 'text-ink-3' }[tone]
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

export default function AnalysisModal({
  data,
  onClose,
}: {
  data: AnalysisData
  onClose: () => void
}) {
  const odd = Number(data.odd)
  const implied = impliedProb(odd)
  // probability é fração (0..1) no banco; confidence idem. Vira % aqui.
  const ourProb = data.probability != null ? Number(data.probability) * 100 : null
  const conf = data.confidence != null ? Math.round(Number(data.confidence) * 100) : null
  // ev também é fração no banco (picks_vip.ev = 0.3203 para 32%), mesma
  // convenção de probability/confidence acima. Faltava o x100 aqui: os quatro
  // chamadores passam a fração crua, então um EV de +32% aparecia como
  // "+0.3%" · erro silencioso, porque 0.3% ainda é um número plausível.
  const ev = data.ev != null ? Number(data.ev) * 100 : null

  // Sem probabilidade real (pick VIP antigo, multipla), confidence entra como
  // aproximacao e o rotulo avisa. Ver PickProbability em PickCardParts.
  const probAproximada = ourProb == null
  const mostraProb = ourProb ?? (conf != null ? conf : null)
  const edge = mostraProb != null ? mostraProb - implied : null

  const regra = data.marketRaw ? regraDoMercado(data.marketRaw, data.lineRaw ?? undefined) : null
  // Mercado que não é de contagem (resultado, ambas marcam) não vira número
  // inteiro · aí vale o texto corrido de sempre.
  const regraTexto = !regra && data.marketRaw
    ? explainMarket(data.marketRaw, data.lineRaw ?? undefined)
    : ''

  return (
    <Modal
      onClose={onClose}
      width="lg"
      title="Entenda esta análise"
      description={`${data.market}${data.line ? ` · ${data.line}` : ''}`}
    >
      <div className="p-5 space-y-5">

        {/*
          A regra, antes de qualquer número, e em contagem inteira.

          A linha vem com meio ponto ("Menos de 10.5") por motivo técnico: meio
          escanteio não existe, a fração só serve pra impedir empate. Mas quem
          lê "10.5 escanteios" pela primeira vez trava, porque o jogo nunca vai
          ter isso. Aqui vira o que se conta no campo · 10 ou menos, 11 ou mais.
        */}
        {(regra || regraTexto) && (
          <div className="bg-accent/5 border border-accent/25 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2.5">
              <BookOpen className="w-3.5 h-3.5 text-accent" />
              <span className="panel-label">Como este mercado funciona</span>
            </div>

            {regra ? (
              <>
                <p className="text-xs text-ink-2 leading-relaxed mb-3">{regra.oQueE}</p>
                <dl className="space-y-1.5">
                  <div className="flex items-start gap-2">
                    <dt className="text-[10px] font-black text-accent w-12 shrink-0 pt-0.5">GREEN</dt>
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

        {/*
          * Uma probabilidade so'.
          *
          * Havia dois cartoes aqui, "Confianca da IA" e "Prob. estimada", com
          * numeros diferentes (confidence vem sistematicamente acima de
          * probability no banco). Dois valores concorrentes pra mesma pergunta
          * so' confundem: fica o que o rotulo promete, a probabilidade.
          */}
        <div className="grid grid-cols-2 gap-3">
          {mostraProb != null && (
            <Metric
              Icon={Percent}
              label={`Probabilidade${probAproximada ? ' estimada' : ''}`}
              value={`${mostraProb.toFixed(1)}%`}
              tone={mostraProb >= 70 ? 'good' : 'default'}
              hint="chance calculada pelo modelo"
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
        </div>

        {/* A conta, em uma linha */}
        {edge != null && (
          <div className="bg-surface-0 border border-line rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Target className="w-3.5 h-3.5 text-ink-4" />
              <span className="panel-label">Por que virou pick</span>
            </div>
            <p className="text-xs text-ink-2 leading-relaxed">
              O modelo estima <span className="font-mono text-ink-1">{mostraProb!.toFixed(1)}%</span> de
              chance, e a odd {odd.toFixed(2)} está pagando como se fosse{' '}
              <span className="font-mono text-ink-1">{implied.toFixed(1)}%</span>.
              {edge > 0 ? (
                <>
                  {' '}A diferença de{' '}
                  <span className="font-mono text-accent">{edge.toFixed(1)} pontos</span>{' '}
                  a nosso favor é o valor que o pick busca capturar.
                </>
              ) : (
                <>
                  {' '}Sem diferença a nosso favor, o pick não seria publicado.
                </>
              )}
            </p>
          </div>
        )}

        {/* Bilhete de várias seleções: uma regra por perna. */}
        {(data.legs?.length ?? 0) > 0 && (
          <div className="bg-accent/5 border border-accent/25 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <BookOpen className="w-3.5 h-3.5 text-accent" />
              <span className="panel-label">O que precisa acontecer em cada jogo</span>
            </div>
            <ol className="space-y-3">
              {data.legs!.map((leg, i) => {
                const r = regraDoMercado(leg.market ?? undefined, leg.line ?? undefined)
                const txt = r ? null : explainMarket(leg.market ?? undefined, leg.line ?? undefined)
                return (
                  <li key={i} className="flex gap-2.5">
                    <span className="font-mono text-[10px] font-bold text-ink-4 pt-0.5 shrink-0">{i + 1}</span>
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold text-ink-1">
                        {translateMarket(leg.market ?? '')}
                        {leg.line && <span className="text-ink-3"> · {translateLine(leg.line)}</span>}
                      </p>
                      <p className="text-xs text-ink-2 leading-relaxed mt-0.5">
                        {r ? r.green : txt}
                      </p>
                    </div>
                  </li>
                )
              })}
            </ol>
            <p className="text-[10px] text-ink-4 leading-relaxed mt-3 pt-3 border-t border-line">
              Todas as seleções precisam dar certo. Uma que falhe derruba o bilhete inteiro.
            </p>
          </div>
        )}

        {/* O que aconteceu de verdade, antes do que a IA escreveu. */}
        {data.pickId != null && data.pickType && (
          <MarketForm pickId={data.pickId} pickType={data.pickType} />
        )}

        {/* Texto do motor */}
        {data.reasoning && (
          <div>
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="panel-label">Leitura do jogo</span>
              <Badge tone="neutral">Gerado pela IA</Badge>
            </div>
            <div className="bg-surface-0 border border-line rounded-lg p-4">
              <p className="text-xs text-ink-2 leading-relaxed whitespace-pre-line">
                {data.reasoning}
              </p>
            </div>
          </div>
        )}

        <p className="text-[10px] text-ink-4 leading-relaxed">
          Probabilidade estimada não é garantia de resultado. O histórico completo de acertos e
          erros fica público na página de Resultados.
          {data.updatedAt && (
            <> Última atualização em {new Date(data.updatedAt).toLocaleString('pt-BR', {
              day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
            })}.</>
          )}
        </p>
      </div>
    </Modal>
  )
}
