import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import api from '../services/api'

const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null

function TeamLogo({ id, name, size = 40 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size}
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

function StatRow({ label, home, away, higherIsBetter = true }: {
  label: string; home?: number | null; away?: number | null; higherIsBetter?: boolean
}) {
  const h = home ?? 0
  const a = away ?? 0
  const homeWins = higherIsBetter ? h > a : h < a
  const awayWins = higherIsBetter ? a > h : a < h
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 py-1">
      <span className={`text-right text-xs font-semibold tabular-nums ${homeWins ? 'text-white' : 'text-zinc-500'}`}>
        {home != null ? Number(home).toFixed(1) : '—'}
      </span>
      <span className="text-[10px] text-zinc-600 text-center min-w-[90px] truncate">{label}</span>
      <span className={`text-left text-xs font-semibold tabular-nums ${awayWins ? 'text-white' : 'text-zinc-500'}`}>
        {away != null ? Number(away).toFixed(1) : '—'}
      </span>
    </div>
  )
}

function RecentList({ matches, teamId, label }: { matches: any[]; teamId?: number; label: string }) {
  if (!matches.length) return (
    <div className="text-center text-xs text-zinc-600 py-4">Sem dados recentes</div>
  )
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-black text-zinc-600 uppercase tracking-wider mb-2">{label}</p>
      {matches.map((m, i) => {
        const isHome  = m.home_team_id === teamId
        const scored  = isHome ? m.home_goals : m.away_goals
        const conceded= isHome ? m.away_goals : m.home_goals
        const won  = scored > conceded
        const drew = scored === conceded
        return (
          <div key={i} className="flex items-center gap-2">
            <span className={`w-5 h-5 flex items-center justify-center rounded text-[10px] font-black shrink-0 ${won ? 'bg-green-500/20 text-green-400' : drew ? 'bg-zinc-700 text-zinc-400' : 'bg-red-500/20 text-red-400'}`}>
              {won ? 'V' : drew ? 'E' : 'D'}
            </span>
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <TeamLogo id={m.home_team_id} name={m.home_team_name ?? ''} size={16} />
              <span className="text-[11px] text-zinc-400 truncate">{m.home_team_name ?? `#${m.home_team_id}`}</span>
              <span className="text-[10px] text-zinc-600 font-bold shrink-0">{m.home_goals ?? 0}×{m.away_goals ?? 0}</span>
              <span className="text-[11px] text-zinc-400 truncate">{m.away_team_name ?? `#${m.away_team_id}`}</span>
              <TeamLogo id={m.away_team_id} name={m.away_team_name ?? ''} size={16} />
            </div>
            <span className="text-[10px] text-zinc-700 shrink-0">
              {m.match_date ? new Date(m.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }) : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}

interface FixtureStatsModalProps {
  fixture: {
    fixture_id: number
    home_team: string
    away_team: string
    home_team_id?: number
    away_team_id?: number
    match_datetime: string
    league_name: string
  }
  onClose: () => void
}

export default function FixtureStatsModal({ fixture, onClose }: FixtureStatsModalProps) {
  const [data, setData]     = useState<any | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/fixtures/${fixture.fixture_id}/stats`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [fixture.fixture_id])

  const time = fixture.match_datetime
    ? new Date(fixture.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : '--:--'

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />
      <div className="relative z-10 w-full sm:max-w-lg bg-zinc-900 border border-zinc-800 rounded-t-2xl sm:rounded-2xl overflow-hidden max-h-[90vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800 shrink-0">
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wider">{fixture.league_name}</p>
            <p className="text-xs text-zinc-400">{time}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-zinc-300 transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Teams */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-zinc-800/60 shrink-0">
          <div className="flex flex-col items-center gap-2 flex-1">
            <TeamLogo id={fixture.home_team_id} name={fixture.home_team} size={48} />
            <span className="text-sm font-bold text-white text-center leading-tight">{fixture.home_team}</span>
            <span className="text-[10px] text-zinc-500">Casa</span>
          </div>
          <span className="text-zinc-600 font-bold text-lg px-4">vs</span>
          <div className="flex flex-col items-center gap-2 flex-1">
            <TeamLogo id={fixture.away_team_id} name={fixture.away_team} size={48} />
            <span className="text-sm font-bold text-white text-center leading-tight">{fixture.away_team}</span>
            <span className="text-[10px] text-zinc-500">Fora</span>
          </div>
        </div>

        <div className="overflow-y-auto flex-1">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-6 h-6 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
            </div>
          ) : !data ? (
            <div className="text-center text-zinc-600 text-sm py-12">Estatísticas não disponíveis.</div>
          ) : (
            <div className="px-5 py-4 space-y-6">

              {/* Médias */}
              {(Object.keys(data.home_stats).length > 0 || Object.keys(data.away_stats).length > 0) && (
                <div>
                  <p className="text-[10px] font-black text-zinc-600 uppercase tracking-wider mb-3">
                    Médias — Casa (últimos {data.home_stats.games_count ?? '?'} jg) · Fora ({data.away_stats.games_count ?? '?'} jg)
                  </p>
                  <div className="space-y-0.5">
                    <StatRow label="Gols marcados" home={data.home_stats.avg_goals_for} away={data.away_stats.avg_goals_for} />
                    <StatRow label="Gols sofridos" home={data.home_stats.avg_goals_against} away={data.away_stats.avg_goals_against} higherIsBetter={false} />
                    <StatRow label="Total de gols" home={data.home_stats.avg_total_goals} away={data.away_stats.avg_total_goals} />
                    <StatRow label="Escanteios marcados" home={data.home_stats.avg_corners_for} away={data.away_stats.avg_corners_for} />
                    <StatRow label="Chutes no gol" home={data.home_stats.avg_shots_on_for} away={data.away_stats.avg_shots_on_for} />
                    <StatRow label="Posse de bola %" home={data.home_stats.avg_possession_for} away={data.away_stats.avg_possession_for} />
                    <StatRow label="Cartões amarelos" home={data.home_stats.avg_yellow_for} away={data.away_stats.avg_yellow_for} higherIsBetter={false} />
                  </div>
                </div>
              )}

              {/* Forma recente */}
              <div className="grid grid-cols-2 gap-4">
                <RecentList
                  matches={data.home_recent}
                  teamId={fixture.home_team_id}
                  label={`Forma — ${fixture.home_team}`}
                />
                <RecentList
                  matches={data.away_recent}
                  teamId={fixture.away_team_id}
                  label={`Forma — ${fixture.away_team}`}
                />
              </div>

            </div>
          )}
        </div>
      </div>
    </div>
  )
}
