import { useEffect, useState } from 'react'
import { Spinner } from './ui'
import { motion } from 'framer-motion'
import { X } from 'lucide-react'
import api from '../services/api'
import { backdropFade, sheetUp } from '../lib/motion'

type Tab = 'geral' | 'gols' | 'escanteios' | 'cartoes'
type Ctx = 'all' | 'home' | 'away'

interface Match {
  fixture_id: number
  match_date: string
  home_team_id: number
  away_team_id: number
  home_team_name: string
  away_team_name: string
  home_goals: number | null
  away_goals: number | null
  total_goals: number | null
  home_corners: number | null
  away_corners: number | null
  total_corners: number | null
  home_yellow_cards: number | null
  away_yellow_cards: number | null
  total_yellow_cards: number | null
  home_red_cards: number | null
  away_red_cards: number | null
  home_fouls: number | null
  away_fouls: number | null
  home_shots_on: number | null
  away_shots_on: number | null
  is_home: boolean
  status: string
}

interface TeamStats {
  games_count?: number
  avg_goals_for?: number | null
  avg_goals_against?: number | null
  avg_total_goals?: number | null
  avg_corners_for?: number | null
  avg_corners_against?: number | null
  avg_shots_on_for?: number | null
  avg_shots_on_against?: number | null
  avg_yellow_for?: number | null
  avg_red_for?: number | null
  avg_possession_for?: number | null
}

// --- Helpers ---
function getTeamStat(m: Match, teamId: number, homeKey: keyof Match, awayKey: keyof Match): number {
  return ((m.home_team_id === teamId ? m[homeKey] : m[awayKey]) ?? 0) as number
}

function overPct(matches: Match[], teamId: number, homeKey: keyof Match, awayKey: keyof Match, threshold: number): number {
  if (!matches.length) return 0
  const count = matches.filter(m => getTeamStat(m, teamId, homeKey, awayKey) > threshold).length
  return Math.round((count / matches.length) * 100)
}

function avgStat(matches: Match[], teamId: number, homeKey: keyof Match, awayKey: keyof Match): number {
  if (!matches.length) return 0
  const sum = matches.reduce((acc, m) => acc + getTeamStat(m, teamId, homeKey, awayKey), 0)
  return Math.round((sum / matches.length) * 10) / 10
}

function totalOverPct(matches: Match[], field: keyof Match, threshold: number): number {
  if (!matches.length) return 0
  const count = matches.filter(m => ((m[field] ?? 0) as number) > threshold).length
  return Math.round((count / matches.length) * 100)
}

function avgPct(a: number, b: number): number {
  if (!a && !b) return 0
  if (!a) return b
  if (!b) return a
  return Math.round((a + b) / 2)
}

// --- Donut chart ---
function Donut({ pct, label, size = 56 }: { pct: number; label: string; size?: number }) {
  const r = (size / 2) * 0.72
  const circ = 2 * Math.PI * r
  const dash = Math.min(pct / 100, 1) * circ
  const color = pct >= 70 ? '#22c55e' : pct >= 40 ? '#f59e0b' : '#ef4444'
  const cx = size / 2
  const cy = size / 2
  return (
    <div className="flex flex-col items-center gap-1.5 min-w-0">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#27272a" strokeWidth={5} />
        {pct > 0 && (
          <circle
            cx={cx} cy={cy} r={r}
            fill="none" stroke={color} strokeWidth={5}
            strokeDasharray={`${dash} ${circ - dash}`}
            strokeLinecap="round"
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        )}
        <text x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="central"
          fill={color} fontSize={size * 0.21} fontWeight="700" fontFamily="system-ui,sans-serif">
          {pct}%
        </text>
      </svg>
      <span className="text-[10px] text-ink-3 text-center whitespace-nowrap">{label}</span>
    </div>
  )
}

// --- Comparison bar ---
function StatRow({ label, home, away, higherIsBetter = true }: {
  label: string; home?: number | null; away?: number | null; higherIsBetter?: boolean
}) {
  const h = home ?? 0
  const a = away ?? 0
  const max = Math.max(h, a, 0.1)
  const homeWins = higherIsBetter ? h > a : h < a
  const awayWins = higherIsBetter ? a > h : a < h
  return (
    <div className="py-2">
      <div className="text-[10px] text-ink-4 text-center mb-1.5 uppercase font-semibold">{label}</div>
      <div className="font-mono flex items-center gap-2">
        <span className={`text-sm font-bold tabular-nums w-10 text-right ${homeWins ? 'text-blue-400' : 'text-ink-2'}`}>
          {home != null ? Number(home).toFixed(1) : ''}
        </span>
        <div className="flex-1 flex gap-0.5 items-center">
          <div className="flex-1 flex justify-end">
            <div className={`h-2 rounded-l-full transition-all ${homeWins ? 'bg-blue-500' : 'bg-surface-3'}`}
              style={{ width: `${(h / max) * 100}%`, minWidth: h > 0 ? '4px' : '0' }} />
          </div>
          <div className="w-px h-3 bg-surface-3 shrink-0" />
          <div className="flex-1">
            <div className={`h-2 rounded-r-full transition-all ${awayWins ? 'bg-rose-500' : 'bg-surface-3'}`}
              style={{ width: `${(a / max) * 100}%`, minWidth: a > 0 ? '4px' : '0' }} />
          </div>
        </div>
        <span className={`text-sm font-bold tabular-nums w-10 text-left ${awayWins ? 'text-rose-400' : 'text-ink-2'}`}>
          {away != null ? Number(away).toFixed(1) : ''}
        </span>
      </div>
    </div>
  )
}

// --- Team donut row ---
interface CircleDef {
  label: string
  homeKey: keyof Match
  awayKey: keyof Match
  threshold: number
}

function TeamDonutRow({ matches, teamId, name, logoSrc, circles }: {
  matches: Match[]
  teamId: number
  name: string
  logoSrc: string
  circles: CircleDef[]
}) {
  const feitos  = avgStat(matches, teamId, circles[0].homeKey, circles[0].awayKey)
  const cedidos = avgStat(matches, teamId, circles[0].awayKey, circles[0].homeKey)

  return (
    <div className="py-3 border-b border-line/50">
      <div className="flex items-center gap-2 mb-1.5">
        <img src={logoSrc} alt={name} width={20} height={20} className="w-5 h-5 object-contain shrink-0"
          onError={e => (e.currentTarget.style.display = 'none')} />
        <span className="text-xs font-semibold text-ink-2 truncate flex-1">{name}</span>
        <span className="text-[10px] text-ink-4 shrink-0">{matches.length}J</span>
      </div>
      {matches.length > 0 && (
        <p className="text-[11px] text-ink-3 mb-3">
          Média: <span className="text-blue-400 font-bold">{feitos.toFixed(1)}</span> feitos
          {' · '}
          <span className="text-rose-400 font-bold">{cedidos.toFixed(1)}</span> cedidos
        </p>
      )}
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${circles.length}, 1fr)` }}>
        {circles.map(c => (
          <Donut key={c.label}
            pct={overPct(matches, teamId, c.homeKey, c.awayKey, c.threshold)}
            label={c.label} />
        ))}
      </div>
    </div>
  )
}

// --- Total donut row ---
interface TotalCircleDef {
  label: string
  field: keyof Match
  threshold: number
}

function TotalDonutRow({ homeMatches, awayMatches, circles }: {
  homeMatches: Match[]
  awayMatches: Match[]
  circles: TotalCircleDef[]
}) {
  return (
    <div className="py-3">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-semibold text-ink-2">Total no Jogo</span>
      </div>
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${circles.length}, 1fr)` }}>
        {circles.map(c => (
          <Donut key={c.label}
            pct={avgPct(
              totalOverPct(homeMatches, c.field, c.threshold),
              totalOverPct(awayMatches, c.field, c.threshold)
            )}
            label={c.label} />
        ))}
      </div>
    </div>
  )
}

// --- Recent form ---
function FormRow({ matches, teamId, name }: { matches: Match[]; teamId: number; name: string }) {
  if (!matches.length) return null
  return (
    <div>
      <p className="text-[10px] text-ink-4 uppercase font-semibold mb-2 truncate">{name}</p>
      <div className="flex gap-1.5 flex-wrap">
        {matches.slice(0, 8).map((m, i) => {
          const scored   = m.home_team_id === teamId ? (m.home_goals ?? 0) : (m.away_goals ?? 0)
          const conceded = m.home_team_id === teamId ? (m.away_goals ?? 0) : (m.home_goals ?? 0)
          const won  = scored > conceded
          const drew = scored === conceded
          return (
            <div key={i} className="flex flex-col items-center gap-0.5">
              <span className={`w-6 h-6 flex items-center justify-center rounded text-[10px] font-black ${
                won ? 'bg-green-500/20 text-green-400' : drew ? 'bg-surface-3 text-ink-2' : 'bg-red-500/20 text-red-400'
              }`}>
                {won ? 'V' : drew ? 'E' : 'D'}
              </span>
              <span className="text-[9px] text-ink-4">{scored}-{conceded}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// --- Prop types ---
export interface FixtureStatsModalProps {
  fixture: {
    fixture_id: number
    home_team: string
    away_team: string
    home_team_id?: number
    away_team_id?: number
    match_datetime: string
    league_name: string
    league_flag?: string
    league_id?: number
    status?: string
    home_goals?: number | null
    away_goals?: number | null
    elapsed?: number | null
  }
  onClose: () => void
}

// --- Threshold definitions ---
const GOAL_CIRCLES: CircleDef[] = [
  { label: '+0.5', homeKey: 'home_goals', awayKey: 'away_goals', threshold: 0.5 },
  { label: '+1.5', homeKey: 'home_goals', awayKey: 'away_goals', threshold: 1.5 },
  { label: '+2.5', homeKey: 'home_goals', awayKey: 'away_goals', threshold: 2.5 },
  { label: '+3.5', homeKey: 'home_goals', awayKey: 'away_goals', threshold: 3.5 },
]
const TOTAL_GOAL_CIRCLES: TotalCircleDef[] = [
  { label: '+1.5 JI', field: 'total_goals', threshold: 1.5 },
  { label: '+2.5 JI', field: 'total_goals', threshold: 2.5 },
  { label: '+3.5 JI', field: 'total_goals', threshold: 3.5 },
  { label: '+4.5 JI', field: 'total_goals', threshold: 4.5 },
]
const CORNER_CIRCLES: CircleDef[] = [
  { label: '+3.5', homeKey: 'home_corners', awayKey: 'away_corners', threshold: 3.5 },
  { label: '+4.5', homeKey: 'home_corners', awayKey: 'away_corners', threshold: 4.5 },
  { label: '+5.5', homeKey: 'home_corners', awayKey: 'away_corners', threshold: 5.5 },
  { label: '+6.5', homeKey: 'home_corners', awayKey: 'away_corners', threshold: 6.5 },
]
const TOTAL_CORNER_CIRCLES: TotalCircleDef[] = [
  { label: '+6.5 JI', field: 'total_corners', threshold: 6.5 },
  { label: '+7.5 JI', field: 'total_corners', threshold: 7.5 },
  { label: '+8.5 JI', field: 'total_corners', threshold: 8.5 },
  { label: '+9.5 JI', field: 'total_corners', threshold: 9.5 },
]
const CARD_CIRCLES: CircleDef[] = [
  { label: '+0.5', homeKey: 'home_yellow_cards', awayKey: 'away_yellow_cards', threshold: 0.5 },
  { label: '+1.5', homeKey: 'home_yellow_cards', awayKey: 'away_yellow_cards', threshold: 1.5 },
  { label: '+2.5', homeKey: 'home_yellow_cards', awayKey: 'away_yellow_cards', threshold: 2.5 },
  { label: '+3.5', homeKey: 'home_yellow_cards', awayKey: 'away_yellow_cards', threshold: 3.5 },
]
const TOTAL_CARD_CIRCLES: TotalCircleDef[] = [
  { label: '+1.5 JI', field: 'total_yellow_cards', threshold: 1.5 },
  { label: '+2.5 JI', field: 'total_yellow_cards', threshold: 2.5 },
  { label: '+3.5 JI', field: 'total_yellow_cards', threshold: 3.5 },
  { label: '+4.5 JI', field: 'total_yellow_cards', threshold: 4.5 },
]

export default function FixtureStatsModal({ fixture, onClose }: FixtureStatsModalProps) {
  const [data, setData]     = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab]       = useState<Tab>('geral')
  const [ctx, setCtx]       = useState<Ctx>('all')
  const [n, setN]           = useState(10)

  useEffect(() => {
    setLoading(true)
    setData(null)
    api.get(`/fixtures/${fixture.fixture_id}/stats`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [fixture.fixture_id])

  const homeId = fixture.home_team_id ?? 0
  const awayId = fixture.away_team_id ?? 0

  const filterMatches = (matches: Match[] | undefined, teamId: number): Match[] => {
    let filtered = matches ?? []
    if (ctx === 'home') filtered = filtered.filter(m => m.home_team_id === teamId)
    if (ctx === 'away') filtered = filtered.filter(m => m.away_team_id === teamId)
    return filtered.slice(0, n)
  }

  const homeMatches = filterMatches(data?.home_recent, homeId)
  const awayMatches = filterMatches(data?.away_recent, awayId)
  const homeStats: TeamStats = data?.home_stats ?? {}
  const awayStats: TeamStats = data?.away_stats ?? {}

  const homeLogo = `/api/proxy/team/${homeId}.png`
  const awayLogo = `/api/proxy/team/${awayId}.png`

  const status   = fixture.status ?? 'NS'
  const live     = ['1H', 'HT', '2H', 'ET', 'BT', 'P'].includes(status)
  const finished = ['FT', 'AET', 'PEN'].includes(status)
  const scoreStr = (finished || live) && fixture.home_goals != null
    ? `${fixture.home_goals} - ${fixture.away_goals ?? 0}`
    : 'vs'

  const TABS: { key: Tab; label: string }[] = [
    { key: 'geral',      label: 'Geral' },
    { key: 'gols',       label: 'Gols' },
    { key: 'escanteios', label: 'Escanteios' },
    { key: 'cartoes',    label: 'Cartões' },
  ]

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center" onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/70" />
      <motion.div
        variants={sheetUp}
        className="relative z-10 w-full sm:max-w-md bg-surface-1 rounded-t-lg sm:rounded-lg overflow-hidden max-h-[92vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Fixed header */}
        <div className="bg-surface-2 px-4 pt-4 pb-0 shrink-0">
          {/* League + close */}
          <div className="flex justify-between items-center mb-3">
            <div className="flex items-center gap-2">
              {fixture.league_flag && (
                <img src={fixture.league_flag} alt="" width={16} height={12} className="w-4 h-3 object-cover rounded-sm"
                  onError={e => (e.currentTarget.style.display = 'none')} />
              )}
              <span className="text-xs text-ink-2 font-semibold">{fixture.league_name}</span>
            </div>
            <button onClick={onClose} className="text-ink-3 hover:text-ink-1 transition-colors p-1">
              <X size={16} />
            </button>
          </div>

          {/* Teams + score */}
          <div className="flex items-center px-2 mb-4 gap-3">
            <div className="flex flex-col items-center gap-1.5 flex-1">
              <img src={homeLogo} alt={fixture.home_team} width={40} height={40} className="w-10 h-10 object-contain"
                onError={e => (e.currentTarget.style.display = 'none')} />
              <span className="text-[11px] text-ink-1 font-semibold text-center leading-tight line-clamp-2 max-w-[80px]">
                {fixture.home_team}
              </span>
            </div>
            <div className="font-mono flex flex-col items-center shrink-0 gap-0.5">
              <span className={`text-2xl font-black tabular-nums ${live ? 'text-green-400' : 'text-ink-1'}`}>
                {scoreStr}
              </span>
              {live && fixture.elapsed != null && (
                <span className="text-[10px] text-green-400 font-bold">{fixture.elapsed}′</span>
              )}
              {finished && (
                <span className="text-[10px] text-ink-3">Encerrado</span>
              )}
            </div>
            <div className="flex flex-col items-center gap-1.5 flex-1">
              <img src={awayLogo} alt={fixture.away_team} width={40} height={40} className="w-10 h-10 object-contain"
                onError={e => (e.currentTarget.style.display = 'none')} />
              <span className="text-[11px] text-ink-1 font-semibold text-center leading-tight line-clamp-2 max-w-[80px]">
                {fixture.away_team}
              </span>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-line-strong">
            {TABS.map(t => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`tab flex-1 py-2.5 text-xs font-semibold ${
                  tab === t.key ? 'tab-active' : ''
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 px-4 py-2.5 bg-surface-1 border-b border-line shrink-0">
          <div className="flex gap-1">
            {(['all', 'home', 'away'] as Ctx[]).map((c, i) => (
              <button key={c} onClick={() => setCtx(c)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  ctx === c ? 'bg-blue-600 text-ink-1' : 'bg-surface-2 text-ink-2 hover:text-ink-2'
                }`}>
                {['Todos', 'Casa', 'Fora'][i]}
              </button>
            ))}
          </div>
          <div className="flex gap-1 ml-auto">
            {[5, 10, 15].map(count => (
              <button key={count} onClick={() => setN(count)}
                className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                  n === count ? 'bg-blue-600 text-ink-1' : 'bg-surface-2 text-ink-2 hover:text-ink-2'
                }`}>
                {count}J
              </button>
            ))}
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Spinner size="lg" tone="blue" />
            </div>
          ) : !data ? (
            <div className="text-center text-ink-4 text-sm py-16">Estatísticas não disponíveis.</div>
          ) : (
            <div className="px-4 py-4">

              {tab === 'geral' && (
                <div>
                  <div className="mb-1">
                    <div className="flex justify-between text-[10px] text-ink-4 font-semibold px-10 mb-2">
                      <span className="text-blue-500">{fixture.home_team.split(' ')[0]}</span>
                      <span className="text-rose-500">{fixture.away_team.split(' ')[0]}</span>
                    </div>
                    <StatRow label="Gols marcados"
                      home={avgStat(homeMatches, homeId, 'home_goals', 'away_goals')}
                      away={avgStat(awayMatches, awayId, 'home_goals', 'away_goals')} />
                    <StatRow label="Gols sofridos"
                      home={avgStat(homeMatches, homeId, 'away_goals', 'home_goals')}
                      away={avgStat(awayMatches, awayId, 'away_goals', 'home_goals')} higherIsBetter={false} />
                    <StatRow label="Escanteios"
                      home={avgStat(homeMatches, homeId, 'home_corners', 'away_corners')}
                      away={avgStat(awayMatches, awayId, 'home_corners', 'away_corners')} />
                    <StatRow label="Chutes no gol"
                      home={avgStat(homeMatches, homeId, 'home_shots_on', 'away_shots_on')}
                      away={avgStat(awayMatches, awayId, 'home_shots_on', 'away_shots_on')} />
                    <StatRow label="Cartões amarelos"
                      home={avgStat(homeMatches, homeId, 'home_yellow_cards', 'away_yellow_cards')}
                      away={avgStat(awayMatches, awayId, 'home_yellow_cards', 'away_yellow_cards')} higherIsBetter={false} />
                    <StatRow label="Posse de bola %"
                      home={homeStats.avg_possession_for}
                      away={awayStats.avg_possession_for} />
                  </div>
                  <div className="pt-4 border-t border-line grid grid-cols-2 gap-4">
                    <FormRow matches={homeMatches} teamId={homeId} name={fixture.home_team} />
                    <FormRow matches={awayMatches} teamId={awayId} name={fixture.away_team} />
                  </div>
                </div>
              )}

              {tab === 'gols' && (
                <div>
                  <TeamDonutRow matches={homeMatches} teamId={homeId} name={fixture.home_team}
                    logoSrc={homeLogo} circles={GOAL_CIRCLES} />
                  <TeamDonutRow matches={awayMatches} teamId={awayId} name={fixture.away_team}
                    logoSrc={awayLogo} circles={GOAL_CIRCLES} />
                  <TotalDonutRow homeMatches={homeMatches} awayMatches={awayMatches} circles={TOTAL_GOAL_CIRCLES} />
                </div>
              )}

              {tab === 'escanteios' && (
                <div>
                  <TeamDonutRow matches={homeMatches} teamId={homeId} name={fixture.home_team}
                    logoSrc={homeLogo} circles={CORNER_CIRCLES} />
                  <TeamDonutRow matches={awayMatches} teamId={awayId} name={fixture.away_team}
                    logoSrc={awayLogo} circles={CORNER_CIRCLES} />
                  <TotalDonutRow homeMatches={homeMatches} awayMatches={awayMatches} circles={TOTAL_CORNER_CIRCLES} />
                </div>
              )}

              {tab === 'cartoes' && (
                <div>
                  <TeamDonutRow matches={homeMatches} teamId={homeId} name={fixture.home_team}
                    logoSrc={homeLogo} circles={CARD_CIRCLES} />
                  <TeamDonutRow matches={awayMatches} teamId={awayId} name={fixture.away_team}
                    logoSrc={awayLogo} circles={CARD_CIRCLES} />
                  <TotalDonutRow homeMatches={homeMatches} awayMatches={awayMatches} circles={TOTAL_CARD_CIRCLES} />
                </div>
              )}

            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
