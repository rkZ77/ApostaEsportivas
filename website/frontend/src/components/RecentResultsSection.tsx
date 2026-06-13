import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import SuggestionDetail from './SuggestionDetail'

const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.',
}
const SOURCE_CLS: Record<string, string> = {
  vip:         'text-yellow-400 bg-yellow-400/10 border border-yellow-400/20',
  free:        'text-green-400 bg-green-500/10 border border-green-500/20',
  multipla:    'text-blue-400 bg-blue-400/10 border border-blue-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border border-orange-400/20',
}
const RESULT_CLS: Record<string, string> = {
  GREEN:       'bg-green-500/15 text-green-400 border border-green-500/30',
  RED:         'bg-red-500/15 text-red-400 border border-red-500/30',
  PUSH:        'bg-zinc-700/50 text-zinc-400 border border-zinc-700',
  'HALF-WIN':  'bg-teal-500/15 text-teal-400 border border-teal-500/30',
  'HALF-LOSS': 'bg-orange-500/15 text-orange-400 border border-orange-500/30',
}
const RESULT_LBL: Record<string, string> = {
  GREEN: 'GREEN', RED: 'RED', PUSH: 'PUSH', 'HALF-WIN': '½ WIN', 'HALF-LOSS': '½ LOSS',
}

interface Props {
  limit?: number
  title?: string
}

export default function RecentResultsSection({ limit = 6, title = 'Últimos Resultados' }: Props) {
  const navigate = useNavigate()
  const [rows, setRows]           = useState<any[]>([])
  const [loading, setLoading]     = useState(true)
  const [detailPick, setDetailPick] = useState<{ id: number; pick_type: string } | null>(null)

  useEffect(() => {
    api.get('/suggestions/recent-results', { params: { limit: limit + 10 } })
      .then(r => setRows((r.data as any[]).filter((x: any) => x.result).slice(0, limit)))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [limit])

  if (loading) return null
  if (!rows.length) return null

  return (
    <section className="mt-6">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-0.5 h-4 bg-zinc-400 rounded-full block" />
        <h3 className="text-xs font-black text-zinc-400 uppercase tracking-wider">{title}</h3>
      </div>

      <div className="card overflow-hidden p-0">
        <div className="divide-y divide-zinc-800/60">
          {rows.map((row: any) => {
            const pt       = row.pick_type ?? 'vip'
            const homeId   = row.home_team_id ?? row.home_team_id_1
            const awayId   = row.away_team_id ?? row.away_team_id_1
            const homeName = row.home_team_name ?? row.home_team_1 ?? row.home_team ?? ''
            const awayName = row.away_team_name ?? row.away_team_1 ?? row.away_team ?? ''
            const market   = row.market ?? row.market_1 ?? ''
            const line     = row.line ?? row.line_1 ?? ''
            const odd      = Number(row.odd ?? row.total_odd ?? row.odd_combined ?? 0)
            const stake    = Number(row.stake ?? 1)
            const profit   = row.profit != null ? Number(row.profit) * stake : null
            const matchDate = row.match_date ?? ''
            const isMonetary = pt === 'alavancagem'

            return (
              <button
                key={`${pt}-${row.id}`}
                onClick={() => setDetailPick({ id: row.id, pick_type: pt })}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/40 transition-colors text-left"
              >
                <div className="w-12 shrink-0 text-center">
                  <span className="text-xs text-zinc-500">
                    {matchDate ? new Date(matchDate + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) : '—'}
                  </span>
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                    <span className={`text-[10px] font-black px-1.5 py-0.5 rounded shrink-0 ${SOURCE_CLS[pt] ?? ''}`}>
                      {SOURCE_LBL[pt] ?? pt}
                    </span>
                    {homeId && (
                      <img src={`/api/proxy/team/${homeId}.png`}
                        alt="" className="w-4 h-4 object-contain shrink-0"
                        onError={e => (e.currentTarget.style.display = 'none')} />
                    )}
                    <span className="text-sm font-semibold text-white truncate">{homeName}</span>
                    {awayName && pt !== 'multipla' && (
                      <>
                        <span className="text-zinc-600 text-xs shrink-0">vs</span>
                        <span className="text-sm font-semibold text-white truncate">{awayName}</span>
                        {awayId && (
                          <img src={`/api/proxy/team/${awayId}.png`}
                            alt="" className="w-4 h-4 object-contain shrink-0"
                            onError={e => (e.currentTarget.style.display = 'none')} />
                        )}
                      </>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 truncate">
                    {market}{line ? <> · <span className="text-zinc-400">{line}</span></> : ''}
                    {odd > 0 ? ` · Odd ${odd.toFixed(2)}` : ''}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {row.result ? (
                    <span className={`text-xs font-black px-2 py-0.5 rounded-lg ${RESULT_CLS[row.result] ?? 'text-zinc-500'}`}>
                      {RESULT_LBL[row.result] ?? row.result}
                    </span>
                  ) : null}
                  {profit != null ? (
                    <span className={`text-sm font-black w-14 text-right ${profit >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                      {profit >= 0 ? '+' : ''}{isMonetary ? 'R$' : ''}{Math.abs(profit).toFixed(2)}{!isMonetary ? 'u' : ''}
                    </span>
                  ) : (
                    <span className="text-sm font-black w-14 text-right text-zinc-700">—</span>
                  )}
                </div>
              </button>
            )
          })}
        </div>
        <div className="px-4 py-3 border-t border-zinc-800 text-center">
          <button
            onClick={() => navigate('/results')}
            className="text-xs text-green-500 hover:text-green-400 font-semibold transition-colors"
          >
            Ver histórico completo →
          </button>
        </div>
      </div>

      {detailPick && (
        <SuggestionDetail
          id={detailPick.id}
          pickType={detailPick.pick_type}
          onClose={() => setDetailPick(null)}
        />
      )}
    </section>
  )
}
