import { useState, useEffect, useCallback, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Radio, ChevronDown, RefreshCw, CornerUpRight, RectangleVertical,
  Footprints, Hand, Crosshair, Target, Flag, Goal,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import api from '../services/api'
import { backdropFade, sheetUp } from '../lib/motion'

const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null
const LIVE_SET     = new Set(['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'])
const FINISHED_SET = new Set(['FT', 'AET', 'PEN', 'CANC', 'PST', 'ABD', 'AWD', 'WO'])

const STATUS_LABEL: Record<string, string> = {
  NS: 'Não iniciado', '1H': '1º Tempo', HT: 'Intervalo',
  '2H': '2º Tempo', ET: 'Prorrogação', FT: 'Encerrado',
  AET: 'Encerrado', CANC: 'Cancelado', PST: 'Adiado', SUSP: 'Suspenso',
}
const TYPE_CLS: Record<string, string> = {
  vip: 'text-yellow-400 bg-yellow-400/10', free: 'text-green-400 bg-green-400/10',
  multipla: 'text-blue-400 bg-blue-400/10', alavancagem: 'text-orange-400 bg-orange-400/10',
  // Aposta que veio de um pick Ao Vivo. Sem isso o card aparecia aqui sem
  // rótulo nenhum e o usuário não distinguia de uma aposta pré-jogo · são
  // produtos com risco diferente e a origem precisa ficar visível.
  live: 'text-accent-ink bg-accent/10',
}
const TYPE_LABEL: Record<string, string> = {
  vip: 'VIP', free: 'FREE', multipla: 'MÚLT.', alavancagem: 'ALAV.',
  live: 'AO VIVO',
}

// Poisson-based live win probability (same math bookmakers use)
function poissonPmf(lambda: number, k: number): number {
  if (k < 0) return 0
  let p = Math.exp(-lambda)
  for (let i = 0; i < k; i++) p *= lambda / (i + 1)
  return p
}
function poissonGe(lambda: number, k: number): number {
  if (k <= 0) return 1
  let sum = 0
  for (let i = 0; i < k; i++) sum += poissonPmf(lambda, i)
  return Math.max(0, Math.min(1, 1 - sum))
}
function poissonLe(lambda: number, k: number): number {
  if (k < 0) return 0
  let sum = 0
  for (let i = 0; i <= k; i++) sum += poissonPmf(lambda, i)
  return Math.max(0, Math.min(1, sum))
}
// Bisection: find lambda such that P(X >= minGoals) = targetProb
function findLambda(targetProb: number, minGoals: number): number {
  if (targetProb <= 0) return 0
  if (targetProb >= 1) return 20
  let lo = 0.001, hi = 20
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2
    if (poissonGe(mid, minGoals) < targetProb) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}
function calcLiveProb(pick: any): number | null {
  const odd = Number(pick.odd)
  if (!odd || odd <= 1) return null
  const baseProb  = 1 / odd
  const lineLc    = (pick.line   || '').toLowerCase()
  const marketLc  = (pick.market || '').toLowerCase()
  const isOver    = lineLc.startsWith('over')  || lineLc.startsWith('mais')
  const isUnder   = lineLc.startsWith('under') || lineLc.startsWith('menos')
  const isBTTS    = marketLc.includes('both teams') || marketLc.includes('ambas') || marketLc.includes('btts')

  const totalMins   = pick.status === 'ET' ? 120 : 90
  const elapsed     = pick.elapsed ? Math.min(Number(pick.elapsed), totalMins) : null
  const remaining   = elapsed != null ? Math.max(0, totalMins - elapsed) : null
  const remainRatio = remaining != null ? remaining / totalMins : null

  // Over/Under · Poisson sobre gols/eventos restantes
  if ((isOver || isUnder) && pick.current_val != null && pick.line_val != null && elapsed != null && remainRatio != null) {
    if (isOver) {
      const needed = Math.ceil(pick.line_val) - Math.floor(Number(pick.current_val))
      if (needed <= 0) return 99
      if (remaining === 0) return 1
      const lambdaFull = findLambda(baseProb, Math.ceil(pick.line_val))
      return Math.round(poissonGe(lambdaFull * remainRatio, needed) * 100)
    }
    if (isUnder) {
      const maxMore = Math.floor(pick.line_val) - Math.ceil(Number(pick.current_val))
      if (maxMore < 0) return 1
      if (remaining === 0) return 99
      const lambdaFull = findLambda(1 - baseProb, Math.ceil(pick.line_val))
      return Math.round(poissonLe(lambdaFull * remainRatio, maxMore) * 100)
    }
  }

  // Ambas as Equipes Marcam (BTTS) · Poisson independente por equipe
  if (isBTTS && pick.home_goals != null && pick.away_goals != null && elapsed != null && remainRatio != null) {
    const scoredHome = Number(pick.home_goals) > 0
    const scoredAway = Number(pick.away_goals) > 0
    // Copa do Mundo (league_id=1): ~1.0 gols/equipe/90min. Outras ligas: ~1.3
    const lambdaBase = pick.league_id === 1 ? 1.0 : 1.3
    const lambda  = lambdaBase * remainRatio
    const pScore  = 1 - poissonPmf(lambda, 0) // P(marcar pelo menos 1)
    const pNoScore = poissonPmf(lambda, 0)     // P(não marcar)

    if (lineLc === 'yes' || lineLc === 'sim') {
      if (scoredHome && scoredAway)  return 99 // early lock cuida, mas garante
      if (!scoredHome && !scoredAway) return Math.round(pScore * pScore * 100)
      return Math.round(pScore * 100) // uma já marcou, falta a outra
    }
    if (lineLc === 'no' || lineLc === 'não' || lineLc === 'nao') {
      if (scoredHome && scoredAway)  return 1  // perdeu
      if (!scoredHome && !scoredAway) return Math.round((pNoScore * pNoScore + 2 * pNoScore * pScore) * 100)
      return Math.round(pNoScore * 100) // uma já marcou; precisa que a outra não marque
    }
  }

  // Match Winner / Dupla Chance · ajuste dinâmico por placar e tempo
  if (elapsed != null && remainRatio != null && pick.home_goals != null && pick.away_goals != null && pick.pick_status) {
    const progress = elapsed / totalMins
    if (pick.pick_status === 'winning') {
      // Quanto mais perto do FT ganhando, maior a probabilidade
      return Math.round(Math.min(97, (baseProb + (1 - baseProb) * progress * 0.65) * 100))
    }
    if (pick.pick_status === 'losing') {
      // Probabilidade cai conforme o tempo passa sem virar
      return Math.round(Math.max(2, baseProb * (1 - progress * 0.7) * 100))
    }
  }

  // Fallback estático: probabilidade implícita da odd
  return elapsed != null ? null : Math.round(baseProb * 100)
}

function TeamLogo({ id, name, size = 24 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size}
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

/* ── Relógio do jogo ────────────────────────────────────────────────────────
 *
 * A API-Football devolve o minuto INTEIRO (`elapsed`) e o poll é de 15s, então
 * o card mostrava "67'" congelado até a rodada seguinte: três quartos do tempo
 * parado numa tela que promete acompanhamento ao vivo. É a diferença que salta
 * aos olhos ao comparar com o bilhete da Betano, onde o cronômetro corre.
 *
 * Aqui o minuto do servidor é a âncora e os segundos correm no cliente até o
 * próximo fetch. O que ele NÃO faz é inventar: como a API não diz em que
 * segundo do minuto respondeu, o relógio parte de :00 e o fetch seguinte
 * corrige o desvio (no máximo 59s, na prática 15s).
 *
 * Intervalo, pênaltis e jogo suspenso PARAM o relógio · lá o tempo de jogo não
 * corre. E acréscimo trava no teto do período ("45+", "90+") em vez de exibir
 * um 47:12 que não existe: passado o teto, o quanto ainda falta é decisão do
 * árbitro, não conta de minuto.
 */
const PERIODO_CAP: Record<string, number> = { '1H': 45, '2H': 90, ET: 120 }
const RELOGIO_PARADO = new Set(['HT', 'BT', 'P', 'SUSP', 'INT'])

function useRelogio(elapsed: number | null | undefined, status: string, syncedAt: number): string | null {
  const correndo = elapsed != null && LIVE_SET.has(status) && !RELOGIO_PARADO.has(status)
  const [, tick] = useState(0)
  useEffect(() => {
    if (!correndo) return
    const id = setInterval(() => tick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [correndo])

  if (elapsed == null) return null
  if (!correndo) return `${elapsed}'`
  const cap   = PERIODO_CAP[status]
  const total = elapsed * 60 + Math.max(0, Math.floor((Date.now() - syncedAt) / 1000))
  if (cap != null && total >= cap * 60) return `${cap}+`
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/* Avisa por ~1,4s que o número mudou de uma leitura para a outra.
 *
 * Num card que respira de 15 em 15 segundos, o escanteio novo (ou o gol)
 * trocava o dígito em silêncio e passava despercebido: o usuário só descobria
 * comparando com o que lembrava. É o que a casa de aposta resolve piscando o
 * contador quando o evento entra.
 *
 * Só dispara da segunda leitura em diante · a primeira renderização é o estado
 * inicial da tela, não novidade, e piscar tudo ao abrir seria ruído. */
function useMudou(valor: number | null | undefined): boolean {
  const anterior = useRef(valor)
  const [mudou, setMudou] = useState(false)
  useEffect(() => {
    if (anterior.current === valor) return
    const tinhaAntes = anterior.current != null
    anterior.current = valor
    if (!tinhaAntes || valor == null) return
    setMudou(true)
    const id = setTimeout(() => setMudou(false), 1400)
    return () => clearTimeout(id)
  }, [valor])
  return mudou
}

const DESTAQUE = 'bg-green-400/20 ring-1 ring-green-400/40 rounded-sm px-1'

/* Ícone da família de estatística, lido do rótulo que o backend já monta
   ("Escanteios Casa", "Defesas do Goleiro", ...). Casa por palavra e não por
   market_type porque o rótulo é o único campo que /live/my-picks manda pro
   card · e é ele que o usuário lê ao lado do número. Sem correspondência,
   devolve null e o chip aparece só com texto, como antes. */
function iconeDoStat(label?: string | null): LucideIcon | null {
  const l = (label || '').toLowerCase()
  if (l.includes('escanteio'))  return CornerUpRight
  if (l.includes('cart'))       return RectangleVertical
  if (l.includes('falta'))      return Footprints
  if (l.includes('defesa'))     return Hand
  if (l.includes('alvo'))       return Crosshair
  if (l.includes('chute'))      return Target
  if (l.includes('impediment')) return Flag
  if (l.includes('gol') || l.includes('ambas')) return Goal
  return null
}

/* O contador do mercado apostado, no formato do bilhete de casa de aposta:
   ícone da estatística, rótulo e o número em destaque. */
function StatChip({ label, value, cls = '', compact = false }: {
  label?: string | null; value: number; cls?: string; compact?: boolean
}) {
  const Icon   = iconeDoStat(label)
  const mudou  = useMudou(value)
  return (
    <span className={`font-mono inline-flex items-center gap-1 font-black shrink-0 ml-2 ${cls}`}>
      {Icon && <Icon className={compact ? 'w-3 h-3 shrink-0' : 'w-3.5 h-3.5 shrink-0'} strokeWidth={2.5} />}
      {!compact && label && <span className="truncate font-semibold">{label}</span>}
      <span className={`tabular-nums transition-all duration-500 ${mudou ? DESTAQUE : ''}`}>{value}</span>
    </span>
  )
}

/* Placar, com a mesma piscada do contador quando sai gol. */
function Placar({ home, away, cls }: { home: number | null; away: number | null; cls: string }) {
  const mudou = useMudou((Number(home) || 0) * 100 + (Number(away) || 0))
  return (
    <span className={`font-mono font-black tabular-nums mx-1 transition-all duration-500 ${cls} ${mudou ? DESTAQUE : ''}`}>
      {home} x {away}
    </span>
  )
}

function StatBar({ currentVal, lineVal, direction }: {
  currentVal: number; lineVal: number; direction: 'over' | 'under'
}) {
  const maxVal  = Math.max(lineVal * 1.7, currentVal * 1.1 + 1)
  const linePos = Math.min((lineVal / maxVal) * 100, 98)
  const fillPos = Math.min((currentVal / maxVal) * 100, 100)
  const winning = direction === 'over' ? currentVal > lineVal : currentVal < lineVal
  const fillColor = winning ? 'rgb(var(--c-green-400))' : 'rgb(var(--c-red-400))'
  /* Só o rótulo da LINHA fica sobre a barra.
   *
   * O valor atual também tinha um rótulo, pendurado abaixo do preenchimento:
   * ele invadia a frase "Probabilidade de acertar" quando o contador estava em
   * zero, e repetia o número que o chip da estatística já mostra a dois
   * centímetros dali, na mesma cor. Sobrou o que a barra sozinha não diz · onde
   * está a linha. O tamanho do preenchimento continua contando o resto.
   */
  return (
    <div className="relative h-2 bg-surface-3/60 rounded-full mt-6 mb-3">
      <div className="absolute left-0 top-0 h-full rounded-full transition-all duration-700"
        style={{ width: `${fillPos}%`, backgroundColor: fillColor }} />
      <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-ink-1/50 rounded"
        style={{ left: `${linePos}%` }} />
      <div className="absolute -top-5 text-[10px] font-black text-ink-1/70 tabular-nums"
        style={{ left: `${Math.max(linePos, 4)}%`, transform: 'translateX(-50%)' }}>
        {lineVal}
      </div>
    </div>
  )
}

function LiveLeg({ leg, syncedAt }: { leg: any; syncedAt: number }) {
  const isLive    = LIVE_SET.has(leg.status)
  const relogio   = useRelogio(leg.elapsed, leg.status, syncedAt)
  const legLineLc = leg.line?.toLowerCase() ?? ''
  const hasBar    = leg.current_val != null && leg.line_val != null &&
    (legLineLc.startsWith('over') || legLineLc.startsWith('mais') ||
     legLineLc.startsWith('under') || legLineLc.startsWith('menos'))
  const direction: 'over' | 'under' = (leg.line || '').toLowerCase().startsWith('under') ||
    (leg.line || '').toLowerCase().startsWith('menos') ? 'under' : 'over'
  const stColor = leg.pick_status === 'winning' ? 'text-green-400'
    : leg.pick_status === 'losing' ? 'text-red-400' : 'text-ink-2'

  const legProb = isLive && leg.elapsed != null && !leg.is_locked ? calcLiveProb(leg) : null
  const probCls = legProb == null ? '' : legProb >= 60
    ? 'text-green-400 bg-green-400/10 border-green-500/25'
    : legProb >= 35 ? 'text-yellow-400 bg-yellow-400/10 border-yellow-500/25'
    : 'text-red-400 bg-red-400/10 border-red-500/25'

  return (
    <div className="bg-surface-2/60 rounded-lg p-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <TeamLogo id={leg.home_team_id} name={leg.home_team || ''} size={14} />
          <span className="text-xs text-ink-2 truncate">{leg.home_team}</span>
          {leg.status !== 'NS' && (
            <Placar home={leg.home_goals} away={leg.away_goals} cls="text-xs text-ink-1 shrink-0" />
          )}
          <span className="text-ink-4 text-xs shrink-0">vs</span>
          <span className="text-xs text-ink-2 truncate">{leg.away_team}</span>
          <TeamLogo id={leg.away_team_id} name={leg.away_team || ''} size={14} />
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-2">
          {isLive && relogio && (
            <span className="font-mono flex items-center gap-1 text-[9px] font-black text-green-400 tabular-nums">
              <span className="w-1 h-1 rounded-full bg-green-500 animate-pulse shrink-0" />
              {relogio}
            </span>
          )}
          {legProb != null && (
            <span className={`font-mono text-[9px] font-black border px-1.5 py-0.5 rounded ${probCls}`}>
              {legProb}%
            </span>
          )}
          {leg.is_locked && leg.pick_status === 'winning' && (
            <span className="text-[9px] font-black text-green-400 bg-green-400/15 border border-green-500/30 px-1.5 py-0.5 rounded">✓</span>
          )}
          {leg.is_locked && leg.pick_status === 'losing' && (
            <span className="text-[9px] font-black text-red-400 bg-red-400/15 border border-red-500/30 px-1.5 py-0.5 rounded">✗</span>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-ink-3 truncate">{leg.market}, {leg.line}</span>
        {leg.current_val != null && (
          <StatChip label={leg.stat_label} value={leg.current_val} cls={stColor} compact />
        )}
      </div>
      {hasBar && !leg.is_locked && (
        <StatBar currentVal={leg.current_val} lineVal={leg.line_val} direction={direction} />
      )}
    </div>
  )
}

function CashoutModal({ pick, unitValue, onClose, onDone }: {
  pick: any; unitValue?: number; onClose: () => void; onDone: () => void
}) {
  const [amount, setAmount]   = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  // Mesma regra do card: valor pronto do servidor vence a conta por unidades,
  // senao o cashout de uma alavancagem calcularia o lucro contra R$10 quando a
  // aposta foi de R$30.
  const stakeR = pick.stake_amount != null
    ? Number(pick.stake_amount)
    : unitValue ? Number(pick.stake_units) * unitValue : null
  const received = parseFloat(amount)
  const pnlR = stakeR != null && !isNaN(received) ? received - stakeR : null
  const pnlColor = pnlR == null ? 'text-ink-2' : pnlR >= 0 ? 'text-green-400' : 'text-red-400'

  const confirm = async () => {
    if (isNaN(received) || received < 0) { setError('Informe um valor válido.'); return }
    setLoading(true); setError('')
    try {
      await api.post(`/banca/cashout/${pick.pick_id}/${pick.pick_type}`, { cashout_amount: received })
      onDone()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Erro ao registrar cashout.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm px-4" onClick={onClose}
    >
      <motion.div variants={sheetUp} className="w-full max-w-sm bg-surface-1 border border-line-strong rounded-lg p-5 space-y-4 overflow-y-auto max-h-[92dvh]" onClick={e => e.stopPropagation()}>
        <div>
          <p className="font-bold text-ink-1 text-sm">Registrar Cashout</p>
          <p className="text-xs text-ink-3 mt-0.5">
            Digite o valor que a casa pagou ao encerrar a aposta.
          </p>
        </div>

        {stakeR != null && (
          <div className="font-mono bg-surface-2/60 rounded-md px-3 py-2 flex justify-between text-xs">
            <span className="text-ink-3">Apostado</span>
            <span className="text-ink-1 font-semibold">{pick.stake_units}u. R$ {stakeR.toFixed(2)}</span>
          </div>
        )}

        <div className="space-y-1">
          <label className="text-xs text-ink-2">Valor recebido (R$)</label>
          <input
            ref={inputRef}
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={e => { setAmount(e.target.value); setError('') }}
            onKeyDown={e => e.key === 'Enter' && confirm()}
            placeholder="0.00"
            className="font-mono w-full bg-surface-2 border border-line-strong focus:border-green-500/50 rounded-md px-3 py-2.5 text-ink-1 text-sm outline-none transition-colors"
          />
        </div>

        {pnlR != null && (
          <div className={`font-mono text-sm font-bold text-center ${pnlColor}`}>
            {pnlR >= 0 ? '+' : ''}R$ {pnlR.toFixed(2)}
            {stakeR != null && stakeR > 0 && (
              <span className="text-xs font-normal text-ink-3 ml-1">
                ({(pnlR / stakeR * 100).toFixed(0)}%)
              </span>
            )}
          </div>
        )}

        {error && <p className="text-xs text-red-400 text-center">{error}</p>}

        <div className="flex gap-2">
          <button onClick={onClose} disabled={loading}
            className="flex-1 text-sm text-ink-2 border border-line-strong rounded-md py-2.5 hover:bg-surface-2 transition-colors">
            Cancelar
          </button>
          <button onClick={confirm} disabled={loading || amount === ''}
            className="flex-1 text-sm font-semibold bg-green-500/20 text-green-400 border border-green-500/30 rounded-md py-2.5 hover:bg-green-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {loading ? 'Salvando...' : 'Confirmar'}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// Probabilidade combinada de uma múltipla/alavancagem
// Produto das probabilidades individuais de cada leg ainda em aberto.
function calcMultiProb(legs: any[]): number | null {
  if (!legs || legs.length === 0) return null
  let combined = 1.0
  for (const leg of legs) {
    const finished = FINISHED_SET.has(leg.status)
    if (leg.is_locked || finished) {
      if (leg.pick_status === 'winning') continue  // já ganhou, fator 1
      return 1                                     // já perdeu, pick inteiro perdido
    }
    const isLive = LIVE_SET.has(leg.status)
    const legOdd = Number(leg.odd)
    if (legOdd <= 1) return null
    // Leg ao vivo: usa Poisson. Leg aguardando: probabilidade implícita da odd.
    const legProb = isLive && leg.elapsed != null
      ? (calcLiveProb(leg) ?? Math.round(100 / legOdd))
      : Math.round(100 / legOdd)
    combined *= legProb / 100
  }
  return Math.round(combined * 100)
}

// Detecta se o resultado já é matematicamente irreversível (gols não voltam atrás, etc.)
function isEarlyLocked(pick: any): boolean {
  const lineLc   = (pick.line   || '').toLowerCase()
  const marketLc = (pick.market || '').toLowerCase()
  const cur      = Number(pick.current_val)
  const lineVal  = Number(pick.line_val)
  if (pick.current_val == null) return false

  // Ambas as Equipes Marcam · uma vez que ambas marcaram, é irreversível
  if (marketLc.includes('both teams') || marketLc.includes('ambas') || marketLc.includes('btts')) {
    return cur >= 1
  }
  if (!pick.line_val) return false
  // Over X.5 · gols não são descontados
  if (lineLc.startsWith('over') || lineLc.startsWith('mais')) {
    return cur > lineVal
  }
  // Under X.5 · já passou do limite, pick perdido para sempre
  if (lineLc.startsWith('under') || lineLc.startsWith('menos')) {
    return cur >= Math.ceil(lineVal)
  }
  return false
}

function PickCard({ pick, unitValue, onRefresh, syncedAt }: {
  pick: any; unitValue?: number; onRefresh: () => void; syncedAt: number
}) {
  const [showCashout, setShowCashout] = useState(false)
  const relogio     = useRelogio(pick.elapsed, pick.status, syncedAt)
  const isLive      = pick.is_live
  const isFinished  = FINISHED_SET.has(pick.status)
  const isMulti     = pick.pick_type === 'multipla' || pick.pick_type === 'alavancagem'
  const hasCashout  = pick.cashout_amount != null

  const earlyLocked     = !pick.is_locked && isLive && !isMulti && isEarlyLocked(pick)
  const effectiveLocked = pick.is_locked || earlyLocked

  // Quando o jogo encerrou mas o resultado ainda não foi gravado pelo backend,
  // derivamos GREEN/RED de pick_status para mostrar ao usuário
  const effectiveResult: 'GREEN' | 'RED' | null =
    pick.result ??
    (isFinished
      ? pick.pick_status === 'winning' ? 'GREEN'
        : pick.pick_status === 'losing' ? 'RED'
        : null
      : null)
  const hasResult   = !!effectiveResult
  const canCashout  = isLive && !isFinished && !hasCashout && !effectiveLocked && !hasResult

  // Odds e valores financeiros
  const effOdd   = pick.actual_odd ?? Number(pick.odd)
  /*
   * `stake_amount` vem pronto do servidor e SEMPRE vence quando existe.
   *
   * Hoje só a alavancagem manda esse campo, porque ela é o único produto que
   * não aposta em unidades: ela aposta a banca inteira e a compõe. O
   * stake_units dela é 1.00 fixo -- um placeholder --, então a conta genérica
   * `stake_units × unit_value` anunciava R$10 numa aposta de R$30.
   */
  const stakeR   = pick.stake_amount != null
    ? Number(pick.stake_amount)
    : unitValue != null ? pick.stake_units * unitValue : null
  const potRetR  = stakeR != null ? stakeR * effOdd : null
  const premioR  = potRetR != null
    ? (effectiveResult === 'GREEN' ? potRetR : effectiveResult === 'RED' ? 0 : null)
    : null

  // Probabilidade ao vivo
  const lineLc      = pick.line?.toLowerCase() ?? ''
  const hasBar      = !isMulti && pick.current_val != null && pick.line_val != null &&
    (lineLc.startsWith('over') || lineLc.startsWith('mais') ||
     lineLc.startsWith('under') || lineLc.startsWith('menos'))
  const direction: 'over' | 'under' = lineLc.startsWith('under') || lineLc.startsWith('menos') ? 'under' : 'over'
  const stColor     = pick.pick_status === 'winning' ? 'text-green-400'
    : pick.pick_status === 'losing' ? 'text-red-400' : 'text-ink-2'
  const liveProb    = !isMulti && isLive && !effectiveLocked && pick.elapsed != null ? calcLiveProb(pick) : null
  const multiProb   = isMulti ? calcMultiProb(pick.legs ?? []) : null
  const displayProb = liveProb ?? multiProb
  const probCls     = displayProb == null ? '' : displayProb >= 60
    ? 'text-green-400 bg-green-400/10 border-green-500/25'
    : displayProb >= 35
    ? 'text-yellow-400 bg-yellow-400/10 border-yellow-500/25'
    : 'text-red-400 bg-red-400/10 border-red-500/25'
  /* O botão NÃO estima quanto a casa vai pagar de cashout.
   *
   * A conta antiga era retorno potencial x probabilidade, e ela não tem como
   * bater com a Betano ou a Superbet: cada casa aplica a própria margem sobre
   * a odd repreçada DELA, e a API-Football sequer publica odd ao vivo para
   * metade dos mercados que o motor gera (escanteios de um time, faltas,
   * defesas do goleiro). O número saía convincente e errado, ao lado de um
   * campo onde o usuário digita o valor verdadeiro.
   *
   * Quem sabe quanto recebeu é ele, na tela da casa. Aqui só se registra.
   */
  const isCopa = pick.league_id === 1

  // Expandido por padrão: só ao vivo; aguardando e resolvido ficam fechados
  const [expanded, setExpanded] = useState(isLive)

  // Header right-side content
  const headerRight = hasCashout ? (
    <span className="font-mono text-sm font-black text-orange-400">R${Number(pick.cashout_amount).toFixed(2)}</span>
  ) : (hasResult || isFinished) ? (
    <div className="font-mono text-right">
      {effectiveResult === 'GREEN' && potRetR != null ? (
        <span className="text-sm font-black text-green-400">+R${(potRetR - (stakeR ?? 0)).toFixed(2)}</span>
      ) : effectiveResult === 'RED' && stakeR != null ? (
        <span className="text-sm font-black text-red-400">-R${stakeR.toFixed(2)}</span>
      ) : (
        <span className="text-xs text-ink-3">{STATUS_LABEL[pick.status] ?? pick.status}</span>
      )}
    </div>
  ) : displayProb != null ? (
    <span className={`font-mono text-xs font-black border px-1.5 py-0.5 rounded ${probCls}`}>{displayProb}%</span>
  ) : isLive ? (
    <span className="flex items-center gap-1 text-[9px] font-black text-green-400">
      <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
      AO VIVO
    </span>
  ) : (
    <span className="text-[10px] text-ink-4">{STATUS_LABEL[pick.status] ?? 'Aguardando'}</span>
  )

  // Sub-label do header
  const headerSub = isMulti
    ? `${(pick.legs ?? []).length} seleções`
    : [pick.market, pick.line].filter(Boolean).join(', ')

  return (
    <div className={`rounded-lg border overflow-hidden transition-colors ${
      earlyLocked && pick.pick_status === 'winning' ? 'border-green-500/40 bg-green-500/5' :
      earlyLocked && pick.pick_status === 'losing'  ? 'border-red-500/30 bg-red-500/5' :
      isCopa && isLive ? 'border-yellow-500/25 bg-surface-1' :
      isLive           ? 'border-green-500/20 bg-surface-1' :
      hasResult && effectiveResult === 'GREEN' ? 'border-green-500/15 bg-surface-1/60' :
      hasResult && effectiveResult === 'RED'   ? 'border-red-500/15 bg-surface-1/60' :
      hasCashout       ? 'border-orange-500/15 bg-surface-1/60' :
                         'border-line bg-surface-1/60'
    }`}>
      {/* ── Header colapsável ── */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-2/40 transition-colors"
        onClick={() => setExpanded((e: boolean) => !e)}
      >
        {/* Esquerda: badge + valor apostado + sub */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] font-black px-1.5 py-0.5 rounded ${TYPE_CLS[pick.pick_type] ?? 'text-ink-2 bg-surface-3/50'}`}>
              {TYPE_LABEL[pick.pick_type] ?? pick.pick_type}
            </span>
            {isLive && (
              <span className="font-mono flex items-center gap-1 text-[10px] font-black text-green-400 tabular-nums">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse shrink-0" />
                {relogio ?? 'AO VIVO'}
              </span>
            )}
            {stakeR != null && (
              <span className="font-mono text-sm font-bold text-ink-1">R${stakeR.toFixed(2)}</span>
            )}
            {pick.bet_house && (
              <span className="text-[10px] text-ink-4">{pick.bet_house}</span>
            )}
          </div>
          {headerSub && (
            <p className="text-xs text-ink-3 mt-0.5 truncate">{headerSub}</p>
          )}
        </div>

        {/* Direita: cashout / resultado + chevron */}
        <div className="flex items-center gap-2 shrink-0">
          {headerRight}
          <ChevronDown className={`w-4 h-4 text-ink-4 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </div>

      {/* ── Conteúdo expandido ── */}
      {expanded && (
        <div className="border-t border-line/60">
          <div className="px-4 py-3">
            {isMulti ? (
              <div className="space-y-2">
                {(pick.legs ?? []).map((leg: any, i: number) => <LiveLeg key={i} leg={leg} syncedAt={syncedAt} />)}
                {multiProb != null && !hasResult && (
                  <div className="pt-2 border-t border-line/60 space-y-1.5">
                    <div className="font-mono flex justify-between text-xs">
                      <span className="text-ink-3">Prob. combinada</span>
                      <span className={`font-black ${multiProb >= 60 ? 'text-green-400' : multiProb >= 35 ? 'text-yellow-400' : 'text-red-400'}`}>{multiProb}%</span>
                    </div>
                    <div className="h-1 bg-surface-2 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all duration-700 ${multiProb >= 60 ? 'bg-green-500' : multiProb >= 35 ? 'bg-yellow-400' : 'bg-red-500'}`} style={{ width: `${multiProb}%` }} />
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                {/* Times + placar */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  <TeamLogo id={pick.home_team_id} name={pick.home_team || ''} size={16} />
                  <span className="text-sm font-bold text-ink-1 truncate">{pick.home_team}</span>
                  {pick.status !== 'NS' && (
                    <Placar home={pick.home_goals} away={pick.away_goals}
                      cls={`text-sm ${isLive ? 'text-green-400' : 'text-ink-2'}`} />
                  )}
                  <span className="text-ink-4 text-xs">vs</span>
                  <span className="text-sm font-bold text-ink-1 truncate">{pick.away_team}</span>
                  <TeamLogo id={pick.away_team_id} name={pick.away_team || ''} size={16} />
                </div>
                {/* Mercado + stat atual */}
                <div className="flex items-center justify-between text-xs">
                  <span className="text-ink-2 truncate">{pick.market}, {pick.line}</span>
                  {pick.current_val != null && (
                    <StatChip label={pick.stat_label} value={pick.current_val} cls={stColor} />
                  )}
                </div>
                {hasBar && !effectiveLocked && (
                  <StatBar currentVal={pick.current_val} lineVal={pick.line_val} direction={direction} />
                )}
                {/* Probabilidade ao vivo */}
                {liveProb != null && !effectiveLocked && isLive && (
                  <div className="pt-1 space-y-1">
                    <div className="font-mono flex justify-between text-xs">
                      <span className="text-ink-3">Probabilidade de acertar</span>
                      <span className={`font-black ${liveProb >= 60 ? 'text-green-400' : liveProb >= 35 ? 'text-yellow-400' : 'text-red-400'}`}>{liveProb}%</span>
                    </div>
                    <div className="h-1 bg-surface-2 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all duration-700 ${liveProb >= 60 ? 'bg-green-500' : liveProb >= 35 ? 'bg-yellow-400' : 'bg-red-500'}`} style={{ width: `${liveProb}%` }} />
                    </div>
                    <p className="text-[9px] text-ink-4">Estimativa via Poisson, atualiza a cada 15s</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Detalhes da aposta + Cashout ── */}
          <div className="px-4 pb-4 space-y-2 border-t border-line/60 pt-3">
            {effOdd > 1 && (
              <div className="font-mono flex justify-between text-sm">
                <span className="text-ink-2">{isMulti ? 'Odd total' : 'Odd apostada'}</span>
                <span className="text-ink-1 font-semibold">{effOdd.toFixed(2)}</span>
              </div>
            )}
            {pick.bet_house && (
              <div className="flex justify-between text-sm">
                <span className="text-ink-2">Casa</span>
                <span className="text-ink-1 font-semibold">{pick.bet_house}</span>
              </div>
            )}
            {stakeR != null && (
              <div className="font-mono flex justify-between text-sm">
                <span className="text-ink-2">Montante apostado</span>
                <span className="text-ink-1 font-semibold">R${stakeR.toFixed(2)}</span>
              </div>
            )}
            {premioR != null && !hasCashout && (
              <div className="font-mono flex justify-between text-sm">
                <span className={`font-bold ${premioR > 0 ? 'text-green-400' : 'text-ink-2'}`}>Retorno</span>
                <span className={`font-black ${premioR > 0 ? 'text-green-400' : 'text-red-400'}`}>
                  R${premioR.toFixed(2)}
                </span>
              </div>
            )}
            {hasCashout && (
              <div className="font-mono flex justify-between text-sm">
                <span className="text-ink-2">Cash Out recebido</span>
                <span className="font-black text-orange-400">R${Number(pick.cashout_amount).toFixed(2)}</span>
              </div>
            )}
            {canCashout && (
              /* Alvo de toque cheio no celular; no desktop encolhe e vai pra
                 direita, onde moram os valores · registrar cashout é exceção,
                 não a ação principal do card, e uma faixa verde de 1100px
                 dizia o contrário. O alinhamento sai do wrapper e não de um
                 `ml-auto` no botão, que dependia do modo de layout do pai. */
              <div className="flex sm:justify-end mt-1">
                <button
                  onClick={() => setShowCashout(true)}
                  className="w-full sm:w-auto sm:px-6 text-sm font-bold text-white bg-green-700 hover:bg-green-600 border border-green-600/40 rounded-md py-2.5 transition-colors"
                >
                  Registrar Cash Out
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <AnimatePresence>
      {showCashout && (
        <CashoutModal
          pick={pick}
          unitValue={unitValue}
          onClose={() => setShowCashout(false)}
          onDone={() => { setShowCashout(false); onRefresh() }}
        />
      )}
      </AnimatePresence>
    </div>
  )
}

const REFRESH_LIVE = 30_000 // 30s · alinhado com o TTL de fixture do backend (30s)

function LiveSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="rounded-lg border border-line bg-surface-1 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-4 w-10 bg-surface-2 rounded" />
              <div className="h-4 w-16 bg-surface-2 rounded" />
            </div>
            <div className="h-4 w-14 bg-surface-2 rounded-sm" />
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-surface-2 rounded-full" />
            <div className="h-4 w-24 bg-surface-2 rounded" />
            <div className="h-4 w-8 bg-surface-3 rounded" />
            <div className="h-4 w-24 bg-surface-2 rounded" />
          </div>
          <div className="h-3 w-32 bg-surface-2 rounded" />
          <div className="h-1.5 bg-surface-2 rounded-full" />
        </div>
      ))}
    </div>
  )
}

export default function LivePicks({ isActive = true, unitValue }: { isActive?: boolean; unitValue?: number }) {
  const [picks, setPicks]           = useState<any[]>([])
  const [loading, setLoading]       = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  /* Instante em que os minutos deste lote chegaram do servidor · é a âncora do
     relógio de cada card (ver useRelogio). Fica separado de `lastUpdate`
     porque só se move quando a resposta chega de fato: um poll que falhou não
     pode adiantar o cronômetro de todo mundo. */
  const [syncedAt, setSyncedAt] = useState(() => Date.now())

  const load = useCallback(() => {
    setRefreshing(true)
    api.get('/live/my-picks')
      /* Array.isArray e não `r.data` direto: a rota devolve lista, e qualquer
         outra coisa (erro serializado, resposta de proxy) fazia o
         `picks.some` logo abaixo derrubar a aba inteira no boundary. */
      .then(r => { setPicks(Array.isArray(r.data) ? r.data : []); setLastUpdate(new Date()); setSyncedAt(Date.now()) })
      .catch(() => {})
      .finally(() => { setLoading(false); setRefreshing(false) })
  }, [])

  // Fetch ao ativar a aba -- o componente fica sempre montado (só escondido
  // via CSS em Picks.tsx), então buscar incondicionalmente ao montar batia
  // a API pra qualquer usuário que abrisse /picks, mesmo sem nunca clicar
  // em "Minhas Apostas"
  useEffect(() => { if (isActive) load() }, [isActive, load])

  // Polling: 15s quando tem pick ao vivo, 60s quando tem pick pendente
  const hasLive    = picks.some(p => p.is_live)
  const hasPending = picks.some(p => !p.is_live && !FINISHED_SET.has(p.status))
  useEffect(() => {
    if (!isActive || !hasLive) return
    const id = setInterval(load, REFRESH_LIVE)
    return () => clearInterval(id)
  }, [load, isActive, hasLive])
  useEffect(() => {
    if (!isActive || hasLive || !hasPending) return
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [load, isActive, hasLive, hasPending])

  // Atualiza quando o usuário volta ao browser (troca de aba, minimiza, etc.),
  // só se a aba "Minhas Apostas" for a que está ativa
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible' && isActive) load() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [load, isActive])

  if (loading && picks.length === 0) {
    return <LiveSkeleton />
  }

  // DEV MOCK · só injeta em desenvolvimento (import.meta.env.DEV = false em prod)
  const DEV_MOCK: any[] = !import.meta.env.DEV ? [] : [
    // 1. VIP ao vivo · Over perdendo, cashout disponível
    {
      pick_id: 9001, pick_type: 'vip', match_date: '2026-06-26',
      odd: 1.87, actual_odd: 1.87, stake_units: 5, bet_house: 'Bet365', cashout_amount: null,
      is_live: true, status: '2H', elapsed: 67, league_id: 1,
      fixture_id: 1001, home_team: 'Brasil', away_team: 'Argentina',
      home_team_id: 6, away_team_id: 7,
      market: 'Gols Mais/Menos', line: 'Over 2.5',
      home_goals: 1, away_goals: 1,
      stat_label: 'Gols', current_val: 2, line_val: 2.5,
      pick_status: 'losing', is_locked: false, result: null,
    },
    // 2. VIP ao vivo · Under ganhando, cashout disponível
    {
      pick_id: 9002, pick_type: 'vip', match_date: '2026-06-26',
      odd: 2.10, actual_odd: 2.10, stake_units: 3, bet_house: 'Sportingbet', cashout_amount: null,
      is_live: true, status: '1H', elapsed: 38, league_id: null,
      fixture_id: 1002, home_team: 'França', away_team: 'Espanha',
      home_team_id: 2, away_team_id: 9,
      market: 'Gols Mais/Menos', line: 'Under 1.5',
      home_goals: 0, away_goals: 0,
      stat_label: 'Gols', current_val: 0, line_val: 1.5,
      pick_status: 'winning', is_locked: false, result: null,
    },
    // 3. Múltipla ao vivo · 2 legs, uma ganhando, outra em aberto
    {
      pick_id: 9003, pick_type: 'multipla', match_date: '2026-06-26',
      odd: 3.19, actual_odd: 3.19, stake_units: 5, bet_house: 'Bet365', cashout_amount: null,
      is_live: true, result: null,
      legs: [
        {
          fixture_id: 1003, home_team: 'Ecuador', away_team: 'Germany',
          home_team_id: 5, away_team_id: 3,
          market: 'Gols Mais/Menos', line: 'Over 2.5', odd: 1.67,
          status: 'FT', elapsed: null, home_goals: 2, away_goals: 1,
          stat_label: 'Gols', current_val: 3, line_val: 2.5,
          pick_status: 'winning', is_locked: true, is_live: false, result: 'GREEN',
        },
        {
          fixture_id: 1004, home_team: 'Japan', away_team: 'Sweden',
          home_team_id: 12, away_team_id: 13,
          market: 'Gols Mais/Menos', line: 'Over 2.5', odd: 1.91,
          status: '2H', elapsed: 72, home_goals: 1, away_goals: 0,
          stat_label: 'Gols', current_val: 1, line_val: 2.5,
          pick_status: 'losing', is_locked: false, is_live: true, result: null,
        },
      ],
    },
    // 4. Alavancagem aguardando
    {
      pick_id: 9004, pick_type: 'alavancagem', match_date: '2026-06-26',
      odd: 1.50, actual_odd: 1.50, stake_units: 1, bet_house: 'Bet365', cashout_amount: null,
      is_live: false, status: 'NS', result: null,
      legs: [
        {
          fixture_id: 1005, home_team: 'Portugal', away_team: 'Morocco',
          home_team_id: 4, away_team_id: 8,
          market: 'Gols Mais/Menos', line: 'Under 2.5', odd: 1.50,
          status: 'NS', elapsed: null, home_goals: null, away_goals: null,
          stat_label: null, current_val: null, line_val: null,
          pick_status: null, is_locked: false, is_live: false, result: null,
        },
      ],
    },
    // 5. VIP finalizado GREEN
    {
      pick_id: 9005, pick_type: 'vip', match_date: '2026-06-25',
      odd: 1.70, actual_odd: 1.70, stake_units: 10, bet_house: 'Bet365', cashout_amount: null,
      is_live: false, status: 'FT', elapsed: null, league_id: 1,
      fixture_id: 1006, home_team: 'Paraguay', away_team: 'Australia',
      home_team_id: 14, away_team_id: 15,
      market: 'Gols Mais/Menos', line: 'Over 1.5',
      home_goals: 1, away_goals: 1,
      stat_label: 'Gols', current_val: 2, line_val: 1.5,
      pick_status: 'winning', is_locked: true, result: 'GREEN',
    },
    // 6. Múltipla finalizada RED · leg 1 GREEN, leg 2 RED
    {
      pick_id: 9006, pick_type: 'multipla', match_date: '2026-06-25',
      odd: 3.19, actual_odd: 3.19, stake_units: 5, bet_house: 'Bet365', cashout_amount: null,
      is_live: false, status: 'FT', result: 'RED',
      legs: [
        {
          fixture_id: 1007, home_team: 'Ecuador', away_team: 'Germany',
          home_team_id: 5, away_team_id: 3,
          market: 'Gols Mais/Menos', line: 'Over 2.5', odd: 1.67,
          status: 'FT', elapsed: null, home_goals: 2, away_goals: 1,
          stat_label: 'Gols', current_val: 3, line_val: 2.5,
          pick_status: 'winning', is_locked: true, is_live: false, result: 'GREEN',
        },
        {
          fixture_id: 1008, home_team: 'Japan', away_team: 'Sweden',
          home_team_id: 12, away_team_id: 13,
          market: 'Gols Mais/Menos', line: 'Over 2.5', odd: 1.91,
          status: 'FT', elapsed: null, home_goals: 1, away_goals: 0,
          stat_label: 'Gols', current_val: 1, line_val: 2.5,
          pick_status: 'losing', is_locked: true, is_live: false, result: 'RED',
        },
      ],
    },
    // 7. VIP com cashout já registrado
    {
      pick_id: 9007, pick_type: 'vip', match_date: '2026-06-25',
      odd: 1.82, actual_odd: 1.82, stake_units: 10, bet_house: 'Betano', cashout_amount: 85.00,
      is_live: false, status: 'FT', elapsed: null, league_id: null,
      fixture_id: 1009, home_team: 'Turkey', away_team: 'USA',
      home_team_id: 16, away_team_id: 17,
      market: 'Total de Gols Visitante', line: 'Over 1.5',
      home_goals: 2, away_goals: 1,
      stat_label: 'Gols Fora', current_val: 1, line_val: 1.5,
      pick_status: 'losing', is_locked: true, result: null,
    },
  ]

  const allPicks  = [...picks, ...DEV_MOCK]
  const live      = allPicks.filter(p => p.is_live)
  const pending   = allPicks.filter(p => !p.is_live && !FINISHED_SET.has(p.status))
  const finalized = allPicks.filter(p => FINISHED_SET.has(p.status))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {live.length > 0 && (
            <div className="flex items-center gap-1.5 bg-green-500/10 border border-green-500/20 rounded-sm px-3 py-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              <span className="text-xs font-black text-green-400">{live.length} ao vivo</span>
            </div>
          )}
          <p className="text-xs text-ink-3">
            Clique em "Apostar" em qualquer pick para acompanhar aqui.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {refreshing && (
            <span className="flex items-center gap-1 text-[10px] text-accent-ink">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-ping shrink-0" />
              Atualizando...
            </span>
          )}
          <button onClick={load} aria-label="Atualizar" disabled={refreshing}
            className="flex items-center justify-center text-accent-ink hover:text-green-400 border border-green-500/20 hover:border-green-500/40 w-9 h-9 rounded-lg transition-colors disabled:opacity-50">
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {allPicks.length === 0 ? (
        <div className="card p-10 text-center border-dashed">
          <div className="flex justify-center mb-4">
            <div className="w-14 h-14 rounded-full bg-green-500/10 flex items-center justify-center">
              <Radio className="w-6 h-6 text-green-400" />
            </div>
          </div>
          <p className="font-semibold text-ink-2">Nenhum pick sendo acompanhado</p>
          <p className="text-sm text-ink-3 mt-2 max-w-xs mx-auto leading-relaxed">
            Clique em <span className="text-green-400 font-semibold">Apostar</span> em qualquer pick para acompanhar o resultado ao vivo aqui.
          </p>
        </div>
      ) : (
        <>
          {live.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                <span className="text-sm font-black text-green-400">Ao Vivo</span>
                <span className="font-mono text-[10px] text-green-400/60 bg-green-500/10 px-1.5 py-0.5 rounded-sm">{live.length}</span>
              </div>
              <div className="space-y-3">
                {live.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} unitValue={unitValue} onRefresh={load} syncedAt={syncedAt} />)}
              </div>
            </div>
          )}

          {pending.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-ink-4 rounded-full" />
                <span className="text-sm font-black text-ink-2">Aguardando</span>
                <span className="font-mono text-[10px] text-ink-2 bg-surface-2 px-1.5 py-0.5 rounded-sm">{pending.length}</span>
              </div>
              <div className="space-y-3">
                {pending.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} unitValue={unitValue} onRefresh={load} syncedAt={syncedAt} />)}
              </div>
            </div>
          )}

          {finalized.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-surface-3 rounded-full" />
                <span className="text-sm font-black text-ink-3">Finalizados</span>
                <span className="font-mono text-[10px] text-ink-3 bg-surface-2/50 px-1.5 py-0.5 rounded-sm">{finalized.length}</span>
              </div>
              <div className="space-y-3">
                {finalized.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} unitValue={unitValue} onRefresh={load} syncedAt={syncedAt} />)}
              </div>
            </div>
          )}
        </>
      )}

      {lastUpdate && (
        <p className="text-center text-[10px] text-ink-4">
          {hasLive ? 'Atualiza a cada 15s, ' : ''}última atualização: {lastUpdate.toLocaleTimeString('pt-BR')}
        </p>
      )}
    </div>
  )
}
