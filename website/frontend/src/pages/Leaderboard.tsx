import { useEffect, useState } from 'react'
import { Flame, Medal } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import api from '../services/api'
import Avatar from '../components/Avatar'

interface LeaderEntry {
  rank: number
  id: number
  name: string
  avatar_url: string | null
  bankroll_start: number
  unit_value: number
  total_pnl: number
  total_resolved: number
  greens: number
  win_rate: number
  roi: number
  yield_roi: number
  streak: number
  streak_type: 'green' | 'red' | null
  is_hot: boolean
  is_me: boolean
}

type SortKey = 'roi' | 'yield_roi' | 'win_rate' | 'picks' | 'streak'
type Period = 0 | 7 | 30

const SORT_TABS: { key: SortKey; label: string; desc: string }[] = [
  { key: 'yield_roi', label: 'Yield',    desc: 'Lucro/unidades (tipster)' },
  { key: 'roi',       label: 'ROI',      desc: 'Crescimento da banca' },
  { key: 'win_rate',  label: 'Win Rate', desc: 'Maior % de greens' },
  { key: 'picks',     label: 'Picks',    desc: 'Mais picks acompanhados' },
  { key: 'streak',    label: 'Streak',   desc: 'Melhor sequência ativa' },
]

const PERIODS: { key: Period; label: string }[] = [
  { key: 0,  label: 'Tudo' },
  { key: 7,  label: '7 dias' },
  { key: 30, label: '30 dias' },
]

function RankMedal({ rank }: { rank: number }) {
  if (rank === 1) return <Medal className="w-5 h-5 text-yellow-400" />
  if (rank === 2) return <Medal className="w-5 h-5 text-zinc-400" />
  if (rank === 3) return <Medal className="w-5 h-5 text-orange-500" />
  return <span className="text-zinc-500 text-xs font-mono">#{rank}</span>
}

function StreakBadge({ streak, type }: { streak: number; type: 'green' | 'red' | null }) {
  if (!streak || !type) return null
  return (
    <span className={`text-xs font-black px-1.5 py-0.5 rounded ${
      type === 'green' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
    }`}>
      {type === 'green' ? '+' : '-'}{streak}
    </span>
  )
}

export default function Leaderboard() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState<LeaderEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [sort, setSort]       = useState<SortKey>('yield_roi')
  const [period, setPeriod]   = useState<Period>(0)

  useEffect(() => {
    setLoading(true)
    setError('')
    const params: Record<string, string | number> = { sort }
    if (period > 0) params.days = period
    api.get('/leaderboard', { params })
      .then(r => setEntries(r.data))
      .catch(() => setError('Erro ao carregar ranking.'))
      .finally(() => setLoading(false))
  }, [sort, period])

  const activeSortTab = SORT_TABS.find(t => t.key === sort)

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="flex items-center justify-center w-8 h-8 rounded-full border border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-white transition-colors shrink-0"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button>
          <div>
            <h1 className="text-base font-black text-white">Leaderboard de Bancas</h1>
            <p className="text-zinc-500 text-xs mt-0.5">
              {activeSortTab?.desc} · mín. 3 picks · nomes mascarados por privacidade
            </p>
          </div>
        </div>
      </div>

      <main className="max-w-4xl mx-auto px-4 py-6 space-y-4">

        {/* Controles */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Sort tabs */}
          <div className="flex items-center gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
            {SORT_TABS.map(tab => (
              <button
                key={tab.key}
                onClick={() => setSort(tab.key)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  sort === tab.key
                    ? 'bg-green-500 text-black'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Period filter */}
          <div className="flex items-center gap-1">
            {PERIODS.map(p => (
              <button
                key={p.key}
                onClick={() => setPeriod(p.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  period === p.key
                    ? 'bg-zinc-700 border-zinc-600 text-white'
                    : 'border-zinc-800 text-zinc-500 hover:border-zinc-600'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="w-6 h-6 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {error && (
          <div className="card p-4 text-center text-red-400 text-sm">{error}</div>
        )}

        {!loading && !error && entries.length === 0 && (
          <div className="card p-10 text-center">
            <p className="text-zinc-400 text-sm">Nenhuma banca com dados suficientes ainda.</p>
            <p className="text-zinc-600 text-xs mt-1">Acompanhe pelo menos 3 picks na sua Banca para aparecer aqui.</p>
          </div>
        )}

        {!loading && entries.length > 0 && (
          <>
            {/* Pódio top 3 */}
            {entries.length >= 3 && (
              <div className="grid grid-cols-3 gap-3">
                {([entries[1], entries[0], entries[2]] as LeaderEntry[]).map((e, i) => {
                  if (!e) return <div key={i} />
                  const heights   = ['', 'order-first', '']
                  const ringColors = ['border-zinc-600/40', 'border-yellow-500/40', 'border-orange-700/40']
                  const bgColors  = ['bg-zinc-800/30', 'bg-yellow-500/10', 'bg-orange-700/10']
                  const metricVal = sort === 'yield_roi' ? `${e.yield_roi >= 0 ? '+' : ''}${e.yield_roi}%`
                    : sort === 'roi'      ? `${e.roi >= 0 ? '+' : ''}${e.roi}%`
                    : sort === 'win_rate' ? `${e.win_rate}%`
                    : sort === 'picks'    ? `${e.total_resolved}`
                    : e.streak_type === 'green' ? `+${e.streak}` : e.streak > 0 ? `-${e.streak}` : ''
                  const metricColor = sort === 'streak'
                    ? (e.streak_type === 'green' ? 'text-green-400' : 'text-red-400')
                    : (parseFloat(metricVal) >= 0 ? 'text-green-400' : 'text-red-400')

                  return (
                    <div
                      key={e.id}
                      className={`${heights[i]} card ${bgColors[i]} border ${ringColors[i]} p-3 flex flex-col items-center gap-1.5 ${e.is_me ? 'ring-1 ring-green-500/60' : ''}`}
                    >
                      <div className="flex items-center gap-1">
                        <RankMedal rank={e.rank} />
                        {e.is_hot && <Flame className="w-4 h-4 text-orange-400" />}
                      </div>
                      <Avatar name={e.name} imageUrl={e.avatar_url} size="md" />
                      <p className={`text-xs font-semibold text-center truncate w-full ${e.is_me ? 'text-green-400' : 'text-white'}`}>
                        {e.name}
                      </p>
                      <p className={`text-base font-black ${metricColor}`}>{metricVal}</p>
                      <p className="text-zinc-600 text-xs">{e.total_resolved} picks</p>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Tabela */}
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500 text-xs">
                    <th className="px-4 py-3 text-left font-medium w-10">#</th>
                    <th className="px-4 py-3 text-left font-medium">Apostador</th>
                    <th className="px-4 py-3 text-right font-medium">
                      Yield
                      {sort === 'yield_roi' && <span className="ml-1 text-green-500">↓</span>}
                    </th>
                    <th className="px-4 py-3 text-right font-medium hidden sm:table-cell">
                      ROI
                      {sort === 'roi' && <span className="ml-1 text-green-500">↓</span>}
                    </th>
                    <th className="px-4 py-3 text-right font-medium hidden sm:table-cell">
                      Win%
                      {sort === 'win_rate' && <span className="ml-1 text-green-500">↓</span>}
                    </th>
                    <th className="px-4 py-3 text-right font-medium hidden md:table-cell">
                      Picks
                      {sort === 'picks' && <span className="ml-1 text-green-500">↓</span>}
                    </th>
                    <th className="px-4 py-3 text-right font-medium hidden md:table-cell">
                      Streak
                      {sort === 'streak' && <span className="ml-1 text-green-500">↓</span>}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map(e => (
                    <tr
                      key={e.id}
                      className={`border-b border-zinc-800/50 last:border-0 transition-colors hover:bg-zinc-800/30 ${
                        e.is_me ? 'bg-green-500/5 border-l-2 border-l-green-500' : ''
                      }`}
                    >
                      <td className="px-4 py-3 text-zinc-400 font-mono text-xs">
                        <RankMedal rank={e.rank} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Avatar name={e.name} imageUrl={e.avatar_url} size="sm" />
                          <div>
                            <span className={`font-medium text-sm ${e.is_me ? 'text-green-400' : 'text-white'}`}>
                              {e.name}
                              {e.is_me && <span className="ml-1 text-green-500 text-xs">(você)</span>}
                            </span>
                            {e.is_hot && (
                              <span className="ml-1.5 text-xs bg-orange-500/10 text-orange-400 border border-orange-500/20 px-1.5 py-0.5 rounded font-bold">
                                <Flame className="w-3 h-3 inline-block mr-0.5" /> Em Alta
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className={`px-4 py-3 text-right font-black ${e.yield_roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {e.yield_roi >= 0 ? '+' : ''}{e.yield_roi}%
                      </td>
                      <td className={`px-4 py-3 text-right text-sm hidden sm:table-cell ${e.roi >= 0 ? 'text-zinc-300' : 'text-red-400'}`}>
                        {e.roi >= 0 ? '+' : ''}{e.roi}%
                      </td>
                      <td className="px-4 py-3 text-right text-zinc-400 text-sm hidden sm:table-cell">
                        {e.win_rate}%
                      </td>
                      <td className="px-4 py-3 text-right text-zinc-500 text-xs hidden md:table-cell">
                        {e.total_resolved}
                      </td>
                      <td className="px-4 py-3 text-right hidden md:table-cell">
                        <StreakBadge streak={e.streak} type={e.streak_type} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-zinc-700 text-xs text-center">
              Yield = lucro em unidades / unidades apostadas × 100 · ROI = crescimento da banca em R$
            </p>
          </>
        )}
      </main>
    </div>
  )
}
