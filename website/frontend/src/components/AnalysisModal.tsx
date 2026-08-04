import { BrainCircuit, Percent, Target, TrendingUp, Scale } from 'lucide-react'
import Modal from './ui/Modal'
import { Badge } from './ui'

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
 */

export interface AnalysisData {
  market: string
  line?: string | null
  odd: number
  confidence?: number | null
  probability?: number | null
  ev?: number | null
  reasoning?: string | null
  updatedAt?: string | null
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
  const ev = data.ev != null ? Number(data.ev) : null
  const edge = ourProb != null ? ourProb - implied : null

  return (
    <Modal
      onClose={onClose}
      width="lg"
      title="Entenda esta análise"
      description={`${data.market}${data.line ? ` · ${data.line}` : ''}`}
    >
      <div className="p-5 space-y-5">

        <div className="grid grid-cols-2 gap-3">
          {conf != null && (
            <Metric
              Icon={BrainCircuit}
              label="Confiança da IA"
              value={`${conf}%`}
              tone={conf >= 70 ? 'good' : 'default'}
              hint="quanto o modelo confia na leitura"
            />
          )}
          {ourProb != null && (
            <Metric
              Icon={Percent}
              label="Prob. estimada"
              value={`${ourProb.toFixed(1)}%`}
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
              O modelo estima <span className="font-mono text-ink-1">{ourProb!.toFixed(1)}%</span> de
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
