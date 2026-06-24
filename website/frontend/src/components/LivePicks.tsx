import { useState, useEffect, useCallback, useRef } from 'react'
import { Radio } from 'lucide-react'
import api from '../services/api'

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
}
const TYPE_LABEL: Record<string, string> = {
  vip: 'VIP', free: 'FREE', multipla: 'MÚLT.', alavancagem: 'ALAV.',
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
    if (poissonGe(mid, minGoals) < targetProb) hi = mid
    else lo = mid
  }
  return (lo + hi) / 2
}
function calcLiveProb(pick: any): number | null {
  const odd = Number(pick.odd)
  if (!odd || odd <= 1 || pick.is_locked) return null
  const baseProb = 1 / odd
  const lineLc = (pick.line || '').toLowerCase()
  const isOver  = lineLc.startsWith('over') || lineLc.startsWith('mais')
  const isUnder = lineLc.startsWith('under') || lineLc.startsWith('menos')

  if ((isOver || isUnder) && pick.current_val != null && pick.line_val != null && pick.elapsed) {
    const totalMins   = pick.status === 'ET' ? 120 : 90
    const elapsed     = Math.min(Number(pick.elapsed), totalMins)
    const remaining   = Math.max(0, totalMins - elapsed)
    const remainRatio = remaining / totalMins

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
  // Fallback: implied probability from odd
  return Math.round(baseProb * 100)
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

function StatBar({ currentVal, lineVal, direction }: {
  currentVal: number; lineVal: number; direction: 'over' | 'under'
}) {
  const maxVal  = Math.max(lineVal * 1.7, currentVal * 1.1 + 1)
  const linePos = Math.min((lineVal / maxVal) * 100, 98)
  const fillPos = Math.min((currentVal / maxVal) * 100, 100)
  const winning = direction === 'over' ? currentVal > lineVal : currentVal < lineVal
  const fillColor = winning ? '#22c55e' : '#ef4444'
  return (
    <div className="relative h-2 bg-zinc-700/60 rounded-full mt-3 mb-4">
      <div className="absolute left-0 top-0 h-full rounded-full transition-all duration-700"
        style={{ width: `${fillPos}%`, backgroundColor: fillColor }} />
      <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-white/50 rounded"
        style={{ left: `${linePos}%` }} />
      <div className="absolute -top-5 text-[10px] font-black text-white/70"
        style={{ left: `${linePos}%`, transform: 'translateX(-50%)' }}>
        {lineVal}
      </div>
      <div className="absolute -bottom-5 text-[10px] font-black"
        style={{ left: `${Math.min(fillPos, 95)}%`, transform: 'translateX(-50%)', color: fillColor }}>
        {currentVal}
      </div>
    </div>
  )
}

function LiveLeg({ leg }: { leg: any }) {
  const isLive  = LIVE_SET.has(leg.status)
  const legLineLc = leg.line?.toLowerCase() ?? ''
  const hasBar  = leg.current_val != null && leg.line_val != null &&
    (legLineLc.startsWith('over') || legLineLc.startsWith('mais') ||
     legLineLc.startsWith('under') || legLineLc.startsWith('menos'))
  const direction: 'over' | 'under' = (leg.line || '').toLowerCase().startsWith('under') ||
    (leg.line || '').toLowerCase().startsWith('menos') ? 'under' : 'over'
  const stColor = leg.pick_status === 'winning' ? 'text-green-400'
    : leg.pick_status === 'losing' ? 'text-red-400' : 'text-zinc-400'

  return (
    <div className="bg-zinc-800/60 rounded-lg p-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <TeamLogo id={leg.home_team_id} name={leg.home_team || ''} size={14} />
          <span className="text-xs text-zinc-300 truncate">{leg.home_team}</span>
          {leg.status !== 'NS' && (
            <span className="text-xs font-black text-white tabular-nums mx-1 shrink-0">
              {leg.home_goals} – {leg.away_goals}
            </span>
          )}
          <span className="text-zinc-600 text-xs shrink-0">vs</span>
          <span className="text-xs text-zinc-300 truncate">{leg.away_team}</span>
          <TeamLogo id={leg.away_team_id} name={leg.away_team || ''} size={14} />
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-2">
          {isLive && leg.elapsed && (
            <span className="text-[9px] font-black text-green-400 animate-pulse">{leg.elapsed}'</span>
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
        <span className="text-zinc-500 truncate">{leg.market} · {leg.line}</span>
        {leg.current_val != null && (
          <span className={`font-black shrink-0 ml-2 ${stColor}`}>
            {leg.stat_label}: {leg.current_val}
          </span>
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

  const stakeR = unitValue ? Number(pick.stake_units) * unitValue : null
  const received = parseFloat(amount)
  const pnlR = stakeR != null && !isNaN(received) ? received - stakeR : null
  const pnlColor = pnlR == null ? 'text-zinc-400' : pnlR >= 0 ? 'text-green-400' : 'text-red-400'

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
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm px-4" onClick={onClose}>
      <div className="w-full max-w-sm bg-zinc-900 border border-zinc-700 rounded-2xl p-5 space-y-4" onClick={e => e.stopPropagation()}>
        <div>
          <p className="font-bold text-white text-sm">Registrar Cashout</p>
          <p className="text-xs text-zinc-500 mt-0.5">
            Quanto você recebeu de volta (R$)?
          </p>
        </div>

        {stakeR != null && (
          <div className="bg-zinc-800/60 rounded-xl px-3 py-2 flex justify-between text-xs">
            <span className="text-zinc-500">Apostado</span>
            <span className="text-white font-semibold">{pick.stake_units}u · R$ {stakeR.toFixed(2)}</span>
          </div>
        )}

        <div className="space-y-1">
          <label className="text-xs text-zinc-400">Valor recebido (R$)</label>
          <input
            ref={inputRef}
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={e => { setAmount(e.target.value); setError('') }}
            onKeyDown={e => e.key === 'Enter' && confirm()}
            placeholder="0.00"
            className="w-full bg-zinc-800 border border-zinc-700 focus:border-green-500/50 rounded-xl px-3 py-2.5 text-white text-sm outline-none transition-colors"
          />
        </div>

        {pnlR != null && (
          <div className={`text-sm font-bold text-center ${pnlColor}`}>
            {pnlR >= 0 ? '+' : ''}R$ {pnlR.toFixed(2)}
            {stakeR != null && stakeR > 0 && (
              <span className="text-xs font-normal text-zinc-500 ml-1">
                ({(pnlR / stakeR * 100).toFixed(0)}%)
              </span>
            )}
          </div>
        )}

        {error && <p className="text-xs text-red-400 text-center">{error}</p>}

        <div className="flex gap-2">
          <button onClick={onClose} disabled={loading}
            className="flex-1 text-sm text-zinc-400 border border-zinc-700 rounded-xl py-2.5 hover:bg-zinc-800 transition-colors">
            Cancelar
          </button>
          <button onClick={confirm} disabled={loading || amount === ''}
            className="flex-1 text-sm font-semibold bg-green-500/20 text-green-400 border border-green-500/30 rounded-xl py-2.5 hover:bg-green-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {loading ? 'Salvando...' : 'Confirmar'}
          </button>
        </div>
      </div>
    </div>
  )
}

function PickCard({ pick, unitValue, onRefresh }: { pick: any; unitValue?: number; onRefresh: () => void }) {
  const [showCashout, setShowCashout] = useState(false)
  const isLive     = pick.is_live
  const isFinished = FINISHED_SET.has(pick.status)
  const isMulti    = pick.pick_type === 'multipla' || pick.pick_type === 'alavancagem'
  const hasCashout = pick.cashout_amount != null
  const canCashout = !isFinished && !hasCashout && !pick.is_locked
  const lineLc     = pick.line?.toLowerCase() ?? ''
  const hasBar     = !isMulti && pick.current_val != null && pick.line_val != null &&
    (lineLc.startsWith('over') || lineLc.startsWith('mais') ||
     lineLc.startsWith('under') || lineLc.startsWith('menos'))
  const direction: 'over' | 'under' = (pick.line || '').toLowerCase().startsWith('under') ||
    (pick.line || '').toLowerCase().startsWith('menos') ? 'under' : 'over'
  const stColor = pick.pick_status === 'winning' ? 'text-green-400'
    : pick.pick_status === 'losing' ? 'text-red-400' : 'text-zinc-400'
  const liveProb = isLive && !pick.is_locked && pick.elapsed ? calcLiveProb(pick) : null
  const probCls  = liveProb == null ? '' : liveProb >= 60
    ? 'text-green-400 bg-green-400/10 border-green-500/25'
    : liveProb >= 35
    ? 'text-yellow-400 bg-yellow-400/10 border-yellow-500/25'
    : 'text-red-400 bg-red-400/10 border-red-500/25'
  const isCopa = pick.league_id === 1

  const resultBadge = hasCashout
    ? <span className="text-[10px] font-black text-orange-400 bg-orange-400/10 border border-orange-500/30 px-2 py-0.5 rounded-full">CASHOUT</span>
    : pick.is_locked
    ? pick.pick_status === 'winning'
      ? <span className="text-[10px] font-black text-green-400 bg-green-400/10 border border-green-500/30 px-2 py-0.5 rounded-full">GREEN ✓</span>
      : <span className="text-[10px] font-black text-red-400 bg-red-400/10 border border-red-500/30 px-2 py-0.5 rounded-full">RED ✗</span>
    : null

  return (
    <div className={`relative rounded-2xl border p-4 transition-colors ${
      isCopa && isLive ? 'border-yellow-500/30 bg-zinc-900' :
      isCopa           ? 'border-yellow-500/20 bg-zinc-900/60' :
      isLive           ? 'border-green-500/25 bg-zinc-900' :
      isFinished       ? 'border-zinc-800/50 bg-zinc-900/40' :
                         'border-zinc-800 bg-zinc-900/60'
    }`}>
      {isCopa && <div className="absolute top-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-yellow-500/60 to-transparent -mt-px rounded-t-2xl" />}
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded ${TYPE_CLS[pick.pick_type] ?? 'text-zinc-400 bg-zinc-700/50'}`}>
            {TYPE_LABEL[pick.pick_type] ?? pick.pick_type}
          </span>
          {isCopa && (
            <span className="flex items-center gap-1 text-[9px] font-black text-yellow-400 bg-yellow-400/10 border border-yellow-500/30 px-1.5 py-0.5 rounded-full">
              <img src="/logo-copa-mundo.png" alt="Copa" width={10} height={10} className="object-contain opacity-90" onError={e => (e.currentTarget.style.display = 'none')} />
              Copa do Mundo
            </span>
          )}
          <span className="text-xs text-zinc-500">Odd {Number(pick.odd).toFixed(2)}</span>
          <span className="text-xs text-zinc-700">· {pick.stake_units}u</span>
        </div>
        <div className="flex items-center gap-2">
          {resultBadge}
          {!pick.is_locked && isLive && (
            <span className="flex items-center gap-1 text-[9px] font-black text-red-400 bg-red-400/10 border border-red-500/20 px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse shrink-0" />
              AO VIVO{pick.elapsed ? ` ${pick.elapsed}'` : ''}
            </span>
          )}
          {liveProb != null && (
            <span className={`text-[9px] font-black border px-1.5 py-0.5 rounded ${probCls}`} title="Probabilidade estimada via Poisson">
              {liveProb}%
            </span>
          )}
          {!pick.is_locked && !isLive && (
            <span className="text-[10px] text-zinc-600 uppercase tracking-wide">
              {STATUS_LABEL[pick.status] ?? pick.status ?? 'Aguardando'}
            </span>
          )}
        </div>
      </div>

      {/* Conteúdo */}
      {isMulti ? (
        <div className="space-y-2">
          {(pick.legs ?? []).map((leg: any, i: number) => <LiveLeg key={i} leg={leg} />)}
        </div>
      ) : (
        <>
          {/* Times + Placar — layout inline igual ao LiveLeg */}
          <div className="flex items-center gap-1.5 min-w-0 mb-2 flex-wrap">
            <TeamLogo id={pick.home_team_id} name={pick.home_team || ''} size={16} />
            <span className="text-xs font-bold text-white truncate">{pick.home_team}</span>
            {pick.status !== 'NS' && (
              <span className={`text-xs font-black tabular-nums mx-1 shrink-0 ${isLive ? 'text-green-400' : 'text-zinc-300'}`}>
                {pick.home_goals} – {pick.away_goals}
              </span>
            )}
            <span className="text-zinc-600 text-xs shrink-0">vs</span>
            <span className="text-xs font-bold text-white truncate">{pick.away_team}</span>
            <TeamLogo id={pick.away_team_id} name={pick.away_team || ''} size={16} />
            {isLive && pick.elapsed && (
              <span className="text-[10px] font-black text-green-400 animate-pulse ml-1">{pick.elapsed}'</span>
            )}
            {pick.status === 'NS' && pick.match_time && (
              <span className="text-[10px] text-zinc-500 ml-1">{pick.match_time}</span>
            )}
          </div>
          {/* Mercado + stat */}
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-zinc-500 truncate">{pick.market} · {pick.line}</span>
            {pick.current_val != null && (
              <span className={`font-black shrink-0 ml-2 ${stColor}`}>
                {pick.stat_label}: {pick.current_val}
              </span>
            )}
          </div>
          {hasBar && !pick.is_locked && (
            <StatBar currentVal={pick.current_val} lineVal={pick.line_val} direction={direction} />
          )}
        </>
      )}

      {canCashout && (
        <div className="mt-3 pt-3 border-t border-zinc-800/60">
          <button
            onClick={() => setShowCashout(true)}
            className="w-full text-xs font-semibold text-orange-400 border border-orange-500/25 bg-orange-500/5 hover:bg-orange-500/15 rounded-xl py-2 transition-colors">
            Registrar Cashout
          </button>
        </div>
      )}

      {hasCashout && (
        <div className="mt-3 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs">
          <span className="text-zinc-500">Cashout recebido</span>
          <span className="font-semibold text-orange-400">R$ {Number(pick.cashout_amount).toFixed(2)}</span>
        </div>
      )}

      {showCashout && (
        <CashoutModal
          pick={pick}
          unitValue={unitValue}
          onClose={() => setShowCashout(false)}
          onDone={() => { setShowCashout(false); onRefresh() }}
        />
      )}
    </div>
  )
}

const REFRESH_INTERVAL = 5_000

function LiveSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-4 w-10 bg-zinc-800 rounded" />
              <div className="h-4 w-16 bg-zinc-800 rounded" />
            </div>
            <div className="h-4 w-14 bg-zinc-800 rounded-full" />
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-zinc-800 rounded-full" />
            <div className="h-4 w-24 bg-zinc-800 rounded" />
            <div className="h-4 w-8 bg-zinc-700 rounded" />
            <div className="h-4 w-24 bg-zinc-800 rounded" />
          </div>
          <div className="h-3 w-32 bg-zinc-800 rounded" />
          <div className="h-1.5 bg-zinc-800 rounded-full" />
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

  const load = useCallback(() => {
    setRefreshing(true)
    api.get('/live/my-picks')
      .then(r => { setPicks(r.data); setLastUpdate(new Date()) })
      .catch(() => {})
      .finally(() => { setLoading(false); setRefreshing(false) })
  }, [])

  // Primeiro fetch sempre (ao montar, antes de clicar na aba)
  useEffect(() => { load() }, [load])

  // Polling só quando a aba está visível
  useEffect(() => {
    if (!isActive) return
    const id = setInterval(load, REFRESH_INTERVAL)
    return () => clearInterval(id)
  }, [load, isActive])

  // Atualiza quando o usuário volta ao browser (troca de aba, minimiza, etc.)
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') load() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [load])

  if (loading && picks.length === 0) {
    return <LiveSkeleton />
  }

  // DEV MOCK — só injeta em desenvolvimento (import.meta.env.DEV = false em prod)
  const DEV_MOCK: any[] = !import.meta.env.DEV ? [] : [
    {
      pick_id: 9001, pick_type: 'vip', match_date: '2026-06-23',
      odd: 1.87, stake_units: 3, cashout_amount: null,
      is_live: true, status: '2H', elapsed: 67, league_id: null,
      fixture_id: 1001, home_team: 'Brasil', away_team: 'Argentina',
      home_team_id: 6, away_team_id: 7,
      market: 'Total de Gols', line: 'Over 2.5',
      home_goals: 1, away_goals: 1,
      stat_label: 'Gols', current_val: 2, line_val: 2.5,
      pick_status: 'losing', is_locked: false,
    },
    {
      pick_id: 9002, pick_type: 'free', match_date: '2026-06-23',
      odd: 2.10, stake_units: 2, cashout_amount: null,
      is_live: false, status: 'NS', elapsed: null, league_id: null,
      fixture_id: 1002, home_team: 'França', away_team: 'Espanha',
      home_team_id: 2, away_team_id: 9,
      market: 'Resultado Final', line: 'França',
      home_goals: 0, away_goals: 0,
      stat_label: null, current_val: null, line_val: null,
      pick_status: null, is_locked: false,
    },
    {
      pick_id: 9003, pick_type: 'multipla', match_date: '2026-06-22',
      odd: 3.45, stake_units: 1, cashout_amount: 28.50,
      is_live: false, status: 'FT', elapsed: null, league_id: null,
      legs: [
        {
          fixture_id: 1003, home_team: 'Alemanha', away_team: 'Holanda',
          home_team_id: 3, away_team_id: 5,
          market: 'Resultado', line: 'Alemanha', odd: 1.85,
          status: 'FT', elapsed: null, home_goals: 2, away_goals: 1,
          stat_label: null, current_val: null, line_val: null,
          pick_status: 'winning', is_locked: true, is_live: false,
        },
        {
          fixture_id: 1004, home_team: 'Portugal', away_team: 'Marrocos',
          home_team_id: 4, away_team_id: 8,
          market: 'Total de Gols', line: 'Under 2.5', odd: 1.87,
          status: 'FT', elapsed: null, home_goals: 1, away_goals: 2,
          stat_label: 'Gols', current_val: 3, line_val: 2.5,
          pick_status: 'losing', is_locked: true, is_live: false,
        },
      ],
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
            <div className="flex items-center gap-1.5 bg-red-500/10 border border-red-500/20 rounded-full px-3 py-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-xs font-black text-red-400">{live.length} ao vivo</span>
            </div>
          )}
          <p className="text-xs text-zinc-500">
            Clique em "Apostar" em qualquer pick para acompanhar aqui.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {refreshing && (
            <span className="flex items-center gap-1 text-[10px] text-green-500">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-ping shrink-0" />
              Atualizando...
            </span>
          )}
          <button onClick={load}
            className="text-xs text-green-500 hover:text-green-400 border border-green-500/20 hover:border-green-500/40 px-2 py-1 rounded-lg transition-colors">
            ↻
          </button>
        </div>
      </div>

      {picks.length === 0 ? (
        <div className="card p-10 text-center border-dashed">
          <div className="flex justify-center mb-4">
            <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center">
              <Radio className="w-6 h-6 text-red-400" />
            </div>
          </div>
          <p className="font-semibold text-zinc-300">Nenhum pick sendo acompanhado</p>
          <p className="text-sm text-zinc-500 mt-2 max-w-xs mx-auto leading-relaxed">
            Clique em <span className="text-green-400 font-semibold">Apostar</span> em qualquer pick para acompanhar o resultado ao vivo aqui.
          </p>
        </div>
      ) : (
        <>
          {live.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                <span className="text-xs font-black text-red-400 uppercase tracking-widest">Ao Vivo</span>
                <span className="text-[10px] text-red-400/60 bg-red-500/10 px-1.5 py-0.5 rounded-full">{live.length}</span>
              </div>
              <div className="space-y-3">
                {live.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} unitValue={unitValue} onRefresh={load} />)}
              </div>
            </div>
          )}

          {pending.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-zinc-600 rounded-full" />
                <span className="text-xs font-black text-zinc-500 uppercase tracking-widest">Aguardando</span>
                <span className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded-full">{pending.length}</span>
              </div>
              <div className="space-y-3">
                {pending.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} unitValue={unitValue} onRefresh={load} />)}
              </div>
            </div>
          )}

          {finalized.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 bg-zinc-700 rounded-full" />
                <span className="text-xs font-black text-zinc-600 uppercase tracking-widest">Finalizados</span>
                <span className="text-[10px] text-zinc-700 bg-zinc-800/50 px-1.5 py-0.5 rounded-full">{finalized.length}</span>
              </div>
              <div className="space-y-3">
                {finalized.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} unitValue={unitValue} onRefresh={load} />)}
              </div>
            </div>
          )}
        </>
      )}

      {lastUpdate && (
        <p className="text-center text-[10px] text-zinc-700">
          Atualiza a cada 5s · última: {lastUpdate.toLocaleTimeString('pt-BR')}
        </p>
      )}
    </div>
  )
}
