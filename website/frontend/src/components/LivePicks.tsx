import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, m as motion } from 'framer-motion'
import {
  Radio, ChevronDown, RefreshCw, CornerUpRight, RectangleVertical,
  Footprints, Hand, Crosshair, Target, Flag, Goal, User, CalendarDays, Clock,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import api from '../services/api'
import { plural } from '../utils/format'
import { rotuloDoMercado } from '../utils/marketTranslate'
import { backdropFade, sheetUp } from '../lib/motion'
import { AO_VIVO as LIVE_SET, ENCERRADO as FINISHED_SET, STATUS_LABEL } from '../lib/aoVivo'
import { TeamLogo } from './TeamLogo'
import { ehCartela } from '../utils/cartela'
import { PICK_TYPE_CLS, PICK_TYPE_LABEL } from '../utils/resultStyle'

// Régua de status e escudo saíram daqui pra `lib/aoVivo.ts` em 02/09: as
// mesmas listas viviam copiadas em Fixtures, FixtureStatsModal e no feed de
// Picks Ao Vivo, divergindo entre si. Ver o cabeçalho de lá.
//
// Selo do produto (07/10): sai do mapa do site inteiro. A cópia local só
// conhecia cinco tipos, e Bingo, Boost e o bilhete pessoal apareciam aqui com
// o id cru ("bingo", "pessoal") num selo cinza.
const rotuloDoTipo = (t: string) =>
  t === 'pessoal' ? 'Meu bilhete' : (PICK_TYPE_LABEL[t] ?? t)

/* Bilhete com pernas: as cartelas da IA, a alavancagem e o bilhete montado
   pelo próprio usuário. */
const temPernas = (t: string) => ehCartela(t) || t === 'alavancagem' || t === 'pessoal'

/* "Hoje 21:30", "Amanhã 16:00" ou "12/10 19:00" · o que falta pro jogo é a
   primeira pergunta de quem abre uma aposta que ainda não começou. */
function quandoJoga(ts?: number | null): string | null {
  if (!ts) return null
  const d = new Date(ts * 1000)
  const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0)
  const dia = new Date(d); dia.setHours(0, 0, 0, 0)
  const diff = Math.round((dia.getTime() - hoje.getTime()) / 86_400_000)
  if (diff === 0) return `Hoje ${hora}`
  if (diff === 1) return `Amanhã ${hora}`
  return `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} ${hora}`
}

/* O primeiro apito que ainda vai acontecer na aposta. */
function proximoApito(pick: any): number | null {
  const tss = temPernas(pick.pick_type)
    ? (pick.legs ?? []).filter((l: any) => l.status === 'NS').map((l: any) => l.kickoff_ts)
    : pick.status === 'NS' ? [pick.kickoff_ts] : []
  const validos = tss.filter((t: any) => typeof t === 'number')
  return validos.length ? Math.min(...validos) : null
}

/* Estado de cada perna pra trilha do bilhete: o que já fechou, o que está
   em jogo e o que ainda vai começar. */
function estadoDaPerna(leg: any): 'green' | 'red' | 'void' | 'live' | 'wait' {
  if (leg.resultado === 'VOID') return 'void'
  if (leg.is_locked || FINISHED_SET.has(leg.status)) {
    if (leg.pick_status === 'winning') return 'green'
    if (leg.pick_status === 'losing') return 'red'
    return 'void'
  }
  return LIVE_SET.has(leg.status) ? 'live' : 'wait'
}

const COR_DA_TRILHA = {
  green: 'bg-green-500', red: 'bg-red-500', void: 'bg-ink-4',
  live: 'bg-green-400/50 animate-pulse', wait: 'bg-surface-3',
} as const

/* A trilha do bilhete: um segmento por seleção, visível com o card FECHADO.
   Na casa de aposta é preciso abrir o bilhete pra saber quantas pernas já
   bateram; aqui a resposta está na lista. */
function TrilhaDoBilhete({ legs }: { legs: any[] }) {
  if (legs.length < 2) return null
  const estados = legs.map(estadoDaPerna)
  const bateram = estados.filter(e => e === 'green').length
  return (
    <div className="flex items-center gap-2 mt-2">
      <div className="flex flex-1 gap-0.5" aria-hidden>
        {estados.map((e, i) => <span key={i} className={`h-1.5 flex-1 rounded-full ${COR_DA_TRILHA[e]}`} />)}
      </div>
      <span className="font-mono text-[10px] text-ink-3 tabular-nums shrink-0">
        {bateram}/{legs.length}
      </span>
    </div>
  )
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
          {leg.resultado === 'VOID' && (
            <span className="text-[9px] font-black text-ink-2 bg-surface-3 border border-line-strong px-1.5 py-0.5 rounded">ANULADA</span>
          )}
          {leg.status === 'NS' && quandoJoga(leg.kickoff_ts) && (
            <span className="font-mono text-[10px] text-ink-3 tabular-nums">{quandoJoga(leg.kickoff_ts)}</span>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between text-xs">
        {/* O bilhete pessoal manda o texto que o próprio usuário escolheu no
            Raio-X · é ele que bate com o que está escrito na casa. */}
        <span className="text-ink-3 truncate flex items-center gap-1">
          {leg.market_type === 'player' && <User className="w-3 h-3 shrink-0" />}
          {leg.descricao || rotuloDoMercado(leg.market, leg.line)}
        </span>
        {leg.current_val != null && (
          <StatChip label={leg.stat_label} value={leg.current_val} cls={stColor} compact />
        )}
      </div>
      {leg.motivo && <p className="text-[10px] text-ink-4 mt-1">Anulada: {leg.motivo}</p>}
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
    /* `Number.isFinite` e nao so' `<= 1`: perna sem odd no payload virava NaN,
       que passa batido pelo `<= 1` (toda comparacao com NaN e' falsa), se
       propaga pela multiplicacao e o bilhete inteiro aparecia com "NaN%" no
       lugar da probabilidade. Sem odd nao ha' probabilidade implicita, entao o
       certo e' nao exibir numero nenhum. */
    if (!Number.isFinite(legOdd) || legOdd <= 1) return null
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
  /* Bilhete é bilhete: múltipla, Bingo e alavancagem. O Bingo estava fora
     desta régua e era tratado como pick de um jogo só, inclusive no
     travamento antecipado. Ver utils/cartela. */
  const isMulti     = temPernas(pick.pick_type)
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
      ) : pick.result === 'PUSH' ? (
        <span className="text-xs font-bold text-ink-2">Devolvida</span>
      ) : (
        <span className="text-xs text-ink-3">{STATUS_LABEL[pick.status] ?? pick.status}</span>
      )}
    </div>
  ) : displayProb != null ? (
    <span className={`font-mono text-xs font-black border px-1.5 py-0.5 rounded ${probCls}`}>{displayProb}%</span>
  ) : isLive ? (
    /* Indigo, como no resto do site. Este selo era VERDE enquanto o mesmo
       "AO VIVO" em Picks.tsx era VERMELHO -- o mesmo estado com duas cores
       em dois componentes do mesmo produto. Verde tambem nao servia aqui:
       ele e' GREEN, e um selo verde em cima de um pick em andamento sugere
       resultado. Ver a tabela de cores em ui/Badge.tsx. */
    <span className="flex items-center gap-1 text-[9px] font-black text-indigo-300">
      <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
      AO VIVO
    </span>
  ) : quandoJoga(proximoApito(pick)) ? (
    <span className="font-mono flex items-center gap-1 text-[10px] text-ink-3 tabular-nums">
      <Clock className="w-3 h-3" />{quandoJoga(proximoApito(pick))}
    </span>
  ) : (
    <span className="text-[10px] text-ink-4">{STATUS_LABEL[pick.status] ?? 'Aguardando'}</span>
  )

  // Sub-label do header
  const headerSub = isMulti
    ? plural((pick.legs ?? []).length, 'seleção', 'seleções')
    : rotuloDoMercado(pick.market, pick.line)

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
            <span className={`text-[10px] font-black uppercase tracking-wide px-1.5 py-0.5 rounded border ${PICK_TYPE_CLS[pick.pick_type] ?? 'text-ink-2 bg-surface-3/50 border-line'}`}>
              {rotuloDoTipo(pick.pick_type)}
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
          {isMulti && <TrilhaDoBilhete legs={pick.legs ?? []} />}
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
                  <span className="text-ink-2 truncate">{rotuloDoMercado(pick.market, pick.line)}</span>
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
            {pick.observacao && (
              <p className="text-[11px] text-ink-3 leading-relaxed">{pick.observacao}</p>
            )}
            {pick.pick_type === 'pessoal' && (
              <p className="text-[10px] text-ink-4">Bilhete montado por você no Raio-X. Não é pick da IA e não entra no placar público.</p>
            )}
            {canCashout && (
              /* Alvo de toque cheio no celular; no desktop encolhe e vai pra
                 direita, onde moram os valores · registrar cashout é exceção,
                 não a ação principal do card, e uma faixa verde de 1100px
                 dizia o contrário. O alinhamento sai do wrapper e não de um
                 `ml-auto` no botão, que dependia do modo de layout do pai. */
              <div className="flex sm:justify-end mt-1">
                {/* Era `bg-green-700` com texto branco, e green-700 não existe
                    na paleta (ver tailwind.config.js): caía no verde-garrafa
                    padrão do Tailwind, o mesmo tom que foi reprovado quando o
                    tema claro nasceu, e ficava igual nos dois temas. O
                    preenchimento tingido diz o que o comentário acima já dizia,
                    esta não é a ação principal do card, e é o mesmo vocabulário
                    do variante `vip` do Button. */}
                <button
                  onClick={() => setShowCashout(true)}
                  className="w-full sm:w-auto sm:px-6 text-sm font-bold text-accent-ink bg-accent/10 hover:bg-accent/20 border border-accent/40 rounded-md py-2.5 transition-colors"
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

type Filtro = 'todas' | 'vivo' | 'aguardando' | 'encerradas'

/* Valor em reais de uma aposta, pela mesma regra do card: o valor pronto do
   servidor (alavancagem) vence a conta por unidades. */
function stakeEmReais(p: any, unitValue?: number): number | null {
  if (p.stake_amount != null) return Number(p.stake_amount)
  return unitValue != null ? Number(p.stake_units) * unitValue : null
}

/* Os três números do topo da aba. Nulo sem valor de unidade: sem ele não há
   reais pra mostrar, e "R$0,00" em jogo seria mentira. */
export function resumoDoDia(picks: any[], unitValue?: number) {
  if (unitValue == null) return null
  let emJogo = 0, potencial = 0, resultado = 0
  for (const p of picks) {
    const stake = stakeEmReais(p, unitValue)
    if (stake == null) continue
    const odd = Number(p.actual_odd ?? p.odd) || 1
    if (p.cashout_amount != null) { resultado += Number(p.cashout_amount) - stake; continue }
    if (p.result === 'GREEN') resultado += stake * (odd - 1)
    else if (p.result === 'RED') resultado -= stake
    else if (p.result === 'HALF-WIN') resultado += stake * (odd - 1) / 2
    else if (p.result === 'HALF-LOSS') resultado -= stake / 2
    else if (!p.result) { emJogo += stake; potencial += stake * odd }
  }
  return { emJogo, potencial, resultado }
}

function ResumoCelula({ rotulo, valor, cls = 'text-ink-1' }: { rotulo: string; valor: string; cls?: string }) {
  return (
    <div className="px-3 py-3 min-w-0">
      <p className="text-[10px] uppercase tracking-wide text-ink-4 truncate">{rotulo}</p>
      <p className={`font-mono text-sm sm:text-base font-black tabular-nums truncate ${cls}`}>{valor}</p>
    </div>
  )
}

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
  const [filtro, setFiltro]         = useState<Filtro>('todas')

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
  const resumo    = resumoDoDia(allPicks, unitValue)
  const mostrar   = (g: Filtro) => filtro === 'todas' || filtro === g

  return (
    <div className="space-y-5">
      {/* ── Resumo do dia ──
          O que a pessoa quer saber ao abrir a aba, antes de qualquer card:
          quanto está em jogo, quanto pode voltar e como o dia está indo. */}
      {allPicks.length > 0 && resumo && (
        <div className="grid grid-cols-3 rounded-lg border border-line bg-surface-1 divide-x divide-line">
          <ResumoCelula rotulo="Em jogo" valor={`R$${resumo.emJogo.toFixed(2)}`} />
          <ResumoCelula rotulo="Pode voltar" valor={`R$${resumo.potencial.toFixed(2)}`} cls="text-ink-1" />
          <ResumoCelula
            rotulo="Resultado hoje"
            valor={`${resumo.resultado >= 0 ? '+' : '-'}R$${Math.abs(resumo.resultado).toFixed(2)}`}
            cls={resumo.resultado > 0 ? 'text-green-400' : resumo.resultado < 0 ? 'text-red-400' : 'text-ink-2'}
          />
        </div>
      )}

      {/* Header: filtros + atualizar */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-1.5 overflow-x-auto scrollbar-none -mx-1 px-1" role="tablist">
          {([
            ['todas', 'Todas', allPicks.length],
            ['vivo', 'Ao vivo', live.length],
            ['aguardando', 'Aguardando', pending.length],
            ['encerradas', 'Encerradas', finalized.length],
          ] as [Filtro, string, number][]).map(([id, rotulo, n]) => (
            <button key={id} role="tab" aria-selected={filtro === id} onClick={() => setFiltro(id)}
              className={`shrink-0 flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors ${
                filtro === id ? 'bg-accent/15 border-accent/40 text-accent-ink' : 'border-line text-ink-3 hover:text-ink-1'
              }`}>
              {id === 'vivo' && n > 0 && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
              {rotulo}
              <span className="font-mono text-[10px] opacity-70 tabular-nums">{n}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 shrink-0">
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
          <p className="font-semibold text-ink-2">Nenhuma aposta sendo acompanhada</p>
          <p className="text-sm text-ink-3 mt-2 max-w-xs mx-auto leading-relaxed">
            Toque em <span className="text-green-400 font-semibold">Pegar bilhete</span> num pick, ou monte o seu bilhete no Raio-X de um jogo. Ele aparece aqui com o placar e a estatística ao vivo.
          </p>
          <div className="flex flex-col sm:flex-row gap-2 justify-center mt-5">
            <Link to="/picks" className="flex items-center justify-center gap-1.5 text-sm font-semibold text-accent-ink bg-accent/10 border border-accent/40 rounded-md px-4 py-2.5 hover:bg-accent/20 transition-colors">
              <Target className="w-4 h-4" /> Ver os picks de hoje
            </Link>
            <Link to="/jogos" className="flex items-center justify-center gap-1.5 text-sm font-semibold text-ink-2 border border-line-strong rounded-md px-4 py-2.5 hover:bg-surface-2 transition-colors">
              <CalendarDays className="w-4 h-4" /> Montar meu bilhete
            </Link>
          </div>
        </div>
      ) : (
        <>
          {[live, pending, finalized].every((g, i) => !mostrar((['vivo', 'aguardando', 'encerradas'] as Filtro[])[i]) || g.length === 0) && (
            <p className="text-sm text-ink-3 text-center py-8">Nada nesse filtro agora.</p>
          )}
          {mostrar('vivo') && live.length > 0 && (
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

          {mostrar('aguardando') && pending.length > 0 && (
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

          {mostrar('encerradas') && finalized.length > 0 && (
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
