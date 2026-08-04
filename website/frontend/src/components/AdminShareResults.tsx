import { useEffect, useState } from 'react'
import { Share2 } from 'lucide-react'
import api from '../services/api'
import { winRate as calcWinRate } from '../utils/format'
import { useShareResultsImage, useShareTodayGamesImage, useShareLeagueResultsImage } from '../hooks/useShareStoryImage'

interface DayResult { match_date: string; total: number; greens: number; reds: number; profit: number }
interface LeagueResult {
  league_id: number | null; league_name: string
  total: number; greens: number; reds: number; profit: number; stake_total: number
}

/**
 * Painel de geração das imagens de Story pra divulgação nas redes -- movido
 * pra cá (só admin) porque na página pública de Resultados os botões de
 * compartilhar eram ferramenta interna aparecendo pra qualquer visitante.
 */
export default function AdminShareResults() {
  const [summary, setSummary] = useState<{ total: number; greens: number; reds: number; profit: number } | null>(null)
  const [byDay, setByDay] = useState<DayResult[]>([])
  const [byLeague, setByLeague] = useState<LeagueResult[]>([])
  const [todayGames, setTodayGames] = useState<any[]>([])
  const [tomorrowGames, setTomorrowGames] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const shareResults       = useShareResultsImage()
  const shareCurrentMonth  = useShareResultsImage()
  const shareTodayGames    = useShareTodayGamesImage()
  const shareTomorrowGames = useShareTodayGamesImage()
  const shareLeagueResults = useShareLeagueResultsImage()

  useEffect(() => {
    api.get('/public/results')
      .then(r => {
        setSummary(r.data?.summary ?? null)
        setByDay(r.data?.by_day ?? [])
        setByLeague(r.data?.by_league ?? [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
    api.get('/public/fixtures-today')
      .then(r => setTodayGames(r.data ?? []))
      .catch(() => {})
    api.get('/public/fixtures-today', { params: { days_ahead: 1 } })
      .then(r => setTomorrowGames(r.data ?? []))
      .catch(() => {})
  }, [])

  const now = new Date()
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const todayResult   = byDay.find(d => d.match_date === todayStr)
  const todayWinRate  = todayResult ? calcWinRate(todayResult.greens, todayResult.total) : null

  const currentMonthStr   = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const currentMonthLabel = now.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })

  const winRatePct = summary && summary.total > 0 ? calcWinRate(summary.greens, summary.total) : null
  const profit     = summary ? Number(summary.profit) : null

  const shareThisMonth = async () => {
    const monthSummary = (await api.get('/public/results', { params: { month: currentMonthStr } })).data?.summary
    if (!monthSummary || monthSummary.total === 0) return
    const wr = calcWinRate(monthSummary.greens, monthSummary.total)
    shareCurrentMonth.share({
      winRatePct: wr ?? 0, total: monthSummary.total, greens: monthSummary.greens, reds: monthSummary.reds, profit: Number(monthSummary.profit),
      badgeLabel: `RESULTADOS · ${currentMonthLabel.toUpperCase()}`,
      footerText: `Referente a ${currentMonthLabel}`,
      shareText: `Em ${currentMonthLabel}, a IA da Pick IA fechou ${monthSummary.greens}G / ${monthSummary.reds}R (${Math.round(wr ?? 0)}%). Histórico 100% auditável.`,
    })
  }

  if (loading || !summary || summary.total === 0) return null

  return (
    <div className="card p-4 mb-6">
      <h2 className="text-xs font-semibold text-ink-3 mb-3">Compartilhar resultados</h2>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={shareThisMonth}
          disabled={shareCurrentMonth.sharing}
          className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
        >
          <Share2 className="w-3.5 h-3.5" />
          {shareCurrentMonth.shared ? 'Compartilhado!' : shareCurrentMonth.sharing ? 'Gerando...' : `Resultado de ${currentMonthLabel}`}
        </button>
        <button
          onClick={() => shareResults.share({
            winRatePct: winRatePct ?? 0, total: summary.total, greens: summary.greens, reds: summary.reds, profit: profit ?? 0,
          })}
          disabled={shareResults.sharing}
          className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
        >
          <Share2 className="w-3.5 h-3.5" />
          {shareResults.shared ? 'Compartilhado!' : shareResults.sharing ? 'Gerando...' : 'Compartilhar resultado geral'}
        </button>
        {todayResult && todayResult.total > 0 && (
          <button
            onClick={() => shareResults.share({
              winRatePct: todayWinRate ?? 0,
              total: todayResult.total,
              greens: todayResult.greens,
              reds: todayResult.reds,
              profit: Number(todayResult.profit),
              badgeLabel: 'RESULTADO DE HOJE',
              footerText: new Date(todayStr + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' }),
              shareText: `Hoje a IA da Pick IA fechou ${todayResult.greens}G / ${todayResult.reds}R (${Math.round(todayWinRate ?? 0)}%). Histórico 100% auditável.`,
            })}
            disabled={shareResults.sharing}
            className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
          >
            <Share2 className="w-3.5 h-3.5" />
            {shareResults.shared ? 'Compartilhado!' : shareResults.sharing ? 'Gerando...' : 'Compartilhar resultado de hoje'}
          </button>
        )}
        {byLeague.length > 0 && (
          <button
            onClick={() => shareLeagueResults.share(
              [...byLeague]
                .sort((a, b) => b.total - a.total)
                .map(lg => ({
                  leagueId: lg.league_id, leagueName: lg.league_name,
                  total: lg.total, winRatePct: calcWinRate(lg.greens, lg.total) ?? 0,
                  profit: Number(lg.profit),
                })),
            )}
            disabled={shareLeagueResults.sharing}
            className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
          >
            <Share2 className="w-3.5 h-3.5" />
            {shareLeagueResults.shared ? 'Compartilhado!' : shareLeagueResults.sharing ? 'Gerando...' : 'Compartilhar por liga'}
          </button>
        )}
        {todayGames.length > 0 && (
          <button
            onClick={() => shareTodayGames.share(todayGames.map(g => ({
              homeTeamName: g.home_team, awayTeamName: g.away_team,
              homeTeamId: g.home_team_id, awayTeamId: g.away_team_id,
              leagueName: g.league_name,
            })), 'hoje')}
            disabled={shareTodayGames.sharing}
            className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
          >
            <Share2 className="w-3.5 h-3.5" />
            {shareTodayGames.shared ? 'Compartilhado!' : shareTodayGames.sharing ? 'Gerando...' : 'Compartilhar jogos de hoje'}
          </button>
        )}
        {tomorrowGames.length > 0 && (
          <button
            onClick={() => shareTomorrowGames.share(tomorrowGames.map(g => ({
              homeTeamName: g.home_team, awayTeamName: g.away_team,
              homeTeamId: g.home_team_id, awayTeamId: g.away_team_id,
              leagueName: g.league_name,
            })), 'amanha')}
            disabled={shareTomorrowGames.sharing}
            className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
          >
            <Share2 className="w-3.5 h-3.5" />
            {shareTomorrowGames.shared ? 'Compartilhado!' : shareTomorrowGames.sharing ? 'Gerando...' : 'Compartilhar jogos de amanhã'}
          </button>
        )}
      </div>
    </div>
  )
}
