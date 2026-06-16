import { useState, useEffect, useCallback } from 'react'
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

function PickCard({ pick }: { pick: any }) {
  const isLive     = pick.is_live
  const isFinished = FINISHED_SET.has(pick.status)
  const isMulti    = pick.pick_type === 'multipla' || pick.pick_type === 'alavancagem'
  const lineLc     = pick.line?.toLowerCase() ?? ''
  const hasBar     = !isMulti && pick.current_val != null && pick.line_val != null &&
    (lineLc.startsWith('over') || lineLc.startsWith('mais') ||
     lineLc.startsWith('under') || lineLc.startsWith('menos'))
  const direction: 'over' | 'under' = (pick.line || '').toLowerCase().startsWith('under') ||
    (pick.line || '').toLowerCase().startsWith('menos') ? 'under' : 'over'
  const stColor = pick.pick_status === 'winning' ? 'text-green-400'
    : pick.pick_status === 'losing' ? 'text-red-400' : 'text-zinc-400'

  const resultBadge = pick.is_locked
    ? pick.pick_status === 'winning'
      ? <span className="text-[10px] font-black text-green-400 bg-green-400/10 border border-green-500/30 px-2 py-0.5 rounded-full">GREEN ✓</span>
      : <span className="text-[10px] font-black text-red-400 bg-red-400/10 border border-red-500/30 px-2 py-0.5 rounded-full">RED ✗</span>
    : null

  return (
    <div className={`rounded-2xl border p-4 transition-colors ${
      isLive    ? 'border-green-500/25 bg-zinc-900' :
      isFinished ? 'border-zinc-800/50 bg-zinc-900/40' :
                   'border-zinc-800 bg-zinc-900/60'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded ${TYPE_CLS[pick.pick_type] ?? 'text-zinc-400 bg-zinc-700/50'}`}>
            {TYPE_LABEL[pick.pick_type] ?? pick.pick_type}
          </span>
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
    </div>
  )
}

const REFRESH_INTERVAL = 5_000

export default function LivePicks() {
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

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_INTERVAL)
    return () => clearInterval(id)
  }, [load])

  if (loading && picks.length === 0) {
    return <div className="flex justify-center py-16"><div className="w-8 h-8 border-2 border-zinc-700 border-t-red-500 rounded-full animate-spin" /></div>
  }

  const live      = picks.filter(p => p.is_live)
  const pending   = picks.filter(p => !p.is_live && !FINISHED_SET.has(p.status))
  const finalized = picks.filter(p => FINISHED_SET.has(p.status))

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
            Clique em "+ Apostei" em qualquer pick para acompanhar aqui.
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
            Clique em <span className="text-green-400 font-semibold">+ Apostei</span> em qualquer pick para acompanhar o resultado ao vivo aqui.
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
                {live.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} />)}
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
                {pending.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} />)}
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
                {finalized.map(p => <PickCard key={`${p.pick_type}-${p.pick_id}`} pick={p} />)}
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
