import { BrainCircuit, Check as CheckIcon, Loader2, Share2 } from 'lucide-react'
import { cn } from '../lib/cn'

/*
 * Peças comuns dos cards de pick.
 *
 * Existem cinco cards (VIP, free, múltipla, alavancagem e mercados) e cada um
 * tinha desenhado o próprio rodapé, a própria barra de confiança e a própria
 * faixa de números. Resultado: o mesmo botão "Apostar" com três raios de
 * borda diferentes, e o card de mercados sem botão nenhum.
 *
 * Não virou um componente único com vinte props condicionais de propósito: as
 * diferenças entre os tipos são reais (múltipla tem N seleções, alavancagem
 * tem progressão de banca, mercados tem nome de goleiro). O que se unifica é
 * a ANATOMIA, não o conteúdo.
 */

/* ── Rodapé ─────────────────────────────────────────────────────────────── */

export function PickCardFooter({
  /** Ação principal. Ausente em pick já resolvido. */
  onBet,
  betState = 'idle',
  /** Sem banca configurada o botão vira convite pra configurar. */
  hasBanca = true,
  onShare,
  shareState = 'idle',
  className,
}: {
  onBet?: (e: React.MouseEvent) => void
  betState?: 'idle' | 'loading' | 'done'
  hasBanca?: boolean
  onShare?: (e: React.MouseEvent) => void
  shareState?: 'idle' | 'loading' | 'done'
  className?: string
}) {
  const betLabel =
    betState === 'loading' ? 'Registrando...'
    : betState === 'done' ? 'Registrado'
    : hasBanca ? 'Apostar'
    : 'Configurar banca'

  return (
    <div className={cn('flex items-center gap-2 px-5 py-3 border-t border-line/60', className)}>
      {onBet && (
        <button
          onClick={onBet}
          disabled={betState !== 'idle'}
          className={cn(
            'text-xs font-bold px-3 py-2 rounded-md border transition-colors duration-1 ease-smooth min-h-[36px]',
            betState === 'done'
              ? 'border-accent/30 text-accent bg-accent/10 cursor-default'
              : hasBanca
              ? 'border-accent/30 text-accent bg-accent/10 hover:bg-accent/20'
              : 'border-yellow-500/30 text-yellow-400 hover:border-yellow-500/60 hover:bg-yellow-500/5',
          )}
        >
          {betLabel}
        </button>
      )}

      <div className="flex items-center gap-2 ml-auto">
        {onShare && (
          <button
            onClick={onShare}
            disabled={shareState === 'loading'}
            title="Compartilhar pick"
            className="flex items-center gap-1.5 text-xs font-semibold text-ink-2 hover:text-accent border border-line-strong hover:border-accent/50 px-3 py-2 rounded-md transition-colors duration-1 ease-smooth disabled:opacity-60 min-h-[36px]"
          >
            {shareState === 'loading'
              ? <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
              : shareState === 'done'
              ? <CheckIcon className="w-3.5 h-3.5 text-accent shrink-0" />
              : <Share2 className="w-3.5 h-3.5 shrink-0" />}
            <span className="hidden sm:inline">
              {shareState === 'loading' ? 'Gerando...' : shareState === 'done' ? 'Pronto' : 'Compartilhar'}
            </span>
          </button>
        )}
      </div>
    </div>
  )
}

/* ── Entenda esta análise ───────────────────────────────────────────────── */

/**
 * Botão largo, no corpo do card e não no rodapé.
 *
 * Fica no meio de propósito: é a ação de LEITURA, e o rodapé é a fila de ação
 * (apostar, compartilhar). Largura cheia porque, espremido ao lado dos outros
 * dois, o rótulo tinha que virar só "Entenda" pra caber no celular, e aí a
 * frase perdia o convite.
 */
export function PickExplainButton({
  onClick,
  className,
}: {
  onClick: (e: React.MouseEvent) => void
  className?: string
}) {
  return (
    <div className={cn('px-5 pb-3', className)}>
      <button
        onClick={e => { e.stopPropagation(); onClick(e) }}
        className="w-full flex items-center justify-center gap-1.5 text-[11px] font-semibold text-ink-2 hover:text-ink-1 border border-line hover:border-line-strong rounded-md py-2.5 min-h-[36px] transition-colors duration-1 ease-smooth"
      >
        <BrainCircuit className="w-3.5 h-3.5 shrink-0" />
        Entenda esta análise
      </button>
    </div>
  )
}

/* ── Confiança ──────────────────────────────────────────────────────────── */

/**
 * Barra de confiança com a probabilidade estimada ao lado.
 *
 * Os cortes (75 e 60) são os mesmos usados no resto do site pra decidir cor,
 * então um pick de 76% parece igualmente forte em qualquer tela.
 */
export function PickConfidence({
  confidence,
  probability,
  className,
}: {
  /** Fração 0..1, como vem do banco. */
  confidence: number
  probability?: number | null
  className?: string
}) {
  const pct = Math.round((confidence ?? 0) * 100)
  const prob = probability != null ? Number(probability) * 100 : null

  return (
    <div className={cn('px-5 pb-3', className)}>
      <div className="flex justify-between items-baseline text-[10px] mb-1">
        <span className="text-ink-4">Confiança</span>
        <span className="flex items-center gap-2">
          {prob != null && (
            <span className="text-ink-4">
              prob. <span className="font-mono text-ink-3">{prob.toFixed(0)}%</span>
            </span>
          )}
          <span className={cn('font-mono', pct >= 75 ? 'text-accent font-bold' : 'text-ink-3')}>
            {pct}%
          </span>
        </span>
      </div>
      <div className="bg-surface-2 rounded-full h-1 overflow-hidden">
        <div
          className={cn(
            'h-1 rounded-full',
            pct >= 75 ? 'bg-accent' : pct >= 60 ? 'bg-yellow-500' : 'bg-ink-4',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

/* ── Faixa de números ───────────────────────────────────────────────────── */

export interface PickStat {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  tone?: 'default' | 'accent' | 'red'
}

/**
 * Tira de indicadores no topo do card (odd, stake, lucro, EV).
 *
 * Divisores entre colunas em vez de cards separados: é uma leitura só, e
 * caixinhas independentes faziam o olho tratar cada número como um bloco.
 */
export function PickStats({ items, className }: { items: PickStat[]; className?: string }) {
  const color = { default: 'text-ink-1', accent: 'text-accent', red: 'text-red-400' }

  return (
    <div className={cn('font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60', className)}>
      {items.map(({ label, value, sub, tone = 'default' }) => (
        <div key={label} className="flex-1 px-3 py-3 text-center min-w-0">
          <div className="text-[10px] text-ink-3 mb-0.5 truncate">{label}</div>
          <div className={cn('text-xl font-bold tabular-nums', color[tone])}>{value}</div>
          {sub != null && <div className="text-[10px] text-ink-4 mt-0.5 truncate">{sub}</div>}
        </div>
      ))}
    </div>
  )
}

/* ── Trecho do raciocínio ───────────────────────────────────────────────── */

export function PickReasoning({ text, className }: { text?: string | null; className?: string }) {
  if (!text) return null
  return (
    <div className={cn('mx-5 mb-3 px-3 py-2 bg-surface-1 border border-line rounded-md', className)}>
      <span className="label-micro">Fato · </span>
      <span className="text-[11px] text-ink-2 leading-relaxed line-clamp-3">{text}</span>
    </div>
  )
}
