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
  /* Quantos picks ao vivo JA' liquidaram, no total. Serve pra duas coisas:
     decidir se os botoes do Live aparecem, e evitar oferecer um card que nao
     vai gerar imagem nenhuma. */
  const [liveResolvidos, setLiveResolvidos] = useState(0)
  const [tomorrowGames, setTomorrowGames] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const shareResults       = useShareResultsImage()
  const shareCurrentMonth  = useShareResultsImage()
  /* Hooks PROPRIOS pro Ao Vivo, e nao os de cima reaproveitados: cada hook
     carrega o proprio estado de "gerando/compartilhado", e dois botoes no
     mesmo hook acendem juntos -- quem clicou em "hoje" via o de "mes" dizer
     "Compartilhado!" sem ter feito nada. */
  const shareLiveHoje      = useShareResultsImage()
  const shareLiveMes       = useShareResultsImage()
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
    /* Falha em silencio: onde o motor Live nunca rodou a tabela nem existe, e
       isso e' ambiente, nao defeito -- os botoes dele simplesmente nao
       aparecem. */
    api.get('/live-picks/stats')
      .then(r => setLiveResolvidos(Number(r.data?.resolvidos ?? 0)))
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

  /* O PLACAR DO AO VIVO E' MEDIDO A PARTE (ver live_picks.estatisticas).
   *
   * `/public/results`, que alimenta todos os botoes acima, soma os pipelines
   * de pre-jogo. Somar o Live ali rotularia de "resultado da IA" um conjunto
   * que mistura duas medicoes com regras diferentes -- juntar os dois e'
   * decisao de produto que ainda nao foi tomada, e um card de divulgacao nao
   * e' o lugar de toma-la.
   *
   * Entao estes dois botoes leem a fonte do proprio produto, com o recorte de
   * periodo que ela passou a aceitar em 30/08.
   *
   * `resolvidos` e nao `total_gerados`: pick pendente nao tem resultado pra
   * anunciar, e contar ele no denominador afundaria a taxa do card.
   */
  const compartilharLive = async (
    hook: typeof shareLiveHoje,
    params: Record<string, string>,
    badgeLabel: string,
    rodape: string,
    frase: (g: number, r: number, wr: number) => string,
  ) => {
    const d = (await api.get('/live-picks/stats', { params })).data
    if (!d?.disponivel || !d.resolvidos) return
    const wr = calcWinRate(d.greens, d.resolvidos) ?? 0
    hook.share({
      winRatePct: wr, total: d.resolvidos, greens: d.greens, reds: d.reds,
      profit: Number(d.profit ?? 0),
      badgeLabel, footerText: rodape,
      shareText: frase(d.greens, d.reds, Math.round(wr)),
    })
  }

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

  /* O PAINEL NAO PERTENCE SO' AO PRE-JOGO (30/08).
   *
   * A guarda era `summary.total === 0`, ou seja: sem resultado de pre-jogo o
   * painel inteiro sumia -- e com ele os botoes do Ao Vivo, que leem outra
   * fonte e nao tem nada a ver com aquele numero. Na pratica quase nunca
   * acontece, mas e' o tipo de acoplamento que vira "sumiu e ninguem sabe por
   * que" no dia em que acontece. */
  if (loading) return null
  const temPreJogo = !!summary && summary.total > 0
  if (!temPreJogo && liveResolvidos === 0) return null

  return (
    <div className="card p-4 mb-6">
      <h2 className="text-xs font-semibold text-ink-3 mb-3">Compartilhar resultados</h2>
      <div className="flex flex-wrap gap-2">
        {temPreJogo && (<>
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
            winRatePct: winRatePct ?? 0, total: summary?.total ?? 0,
            greens: summary?.greens ?? 0, reds: summary?.reds ?? 0, profit: profit ?? 0,
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
        </>)}
        {/* AO VIVO · dia e mes (30/08, pedido do usuário).
          *
          * Ficam por último de propósito: são de outro produto e de outra
          * medição, e a fila acima toda fala do pré-jogo. Não somem quando não
          * há pick no período · o clique simplesmente não gera imagem, porque
          * gerar um card de "0 de 0" seria publicar um dia vazio. */}
        {liveResolvidos > 0 && (<>
        <button
          onClick={() => compartilharLive(
            shareLiveHoje,
            { date: todayStr },
            'AO VIVO · HOJE',
            new Date(todayStr + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' }),
            (g, r, wr) => `Hoje o motor Ao Vivo da Pick IA fechou ${g}G / ${r}R (${wr}%), lendo a partida em andamento. Histórico 100% auditável.`,
          )}
          disabled={shareLiveHoje.sharing}
          className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-accent/10 border border-accent/30 text-accent-ink hover:bg-accent/20 transition-colors disabled:opacity-50"
        >
          <Share2 className="w-3.5 h-3.5" />
          {shareLiveHoje.shared ? 'Compartilhado!' : shareLiveHoje.sharing ? 'Gerando...' : 'Ao Vivo de hoje'}
        </button>
        <button
          onClick={() => compartilharLive(
            shareLiveMes,
            { month: currentMonthStr },
            `AO VIVO · ${currentMonthLabel.toUpperCase()}`,
            `Referente a ${currentMonthLabel}`,
            (g, r, wr) => `Em ${currentMonthLabel}, o motor Ao Vivo da Pick IA fechou ${g}G / ${r}R (${wr}%), lendo a partida em andamento. Histórico 100% auditável.`,
          )}
          disabled={shareLiveMes.sharing}
          className="flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-md bg-accent/10 border border-accent/30 text-accent-ink hover:bg-accent/20 transition-colors disabled:opacity-50"
        >
          <Share2 className="w-3.5 h-3.5" />
          {shareLiveMes.shared ? 'Compartilhado!' : shareLiveMes.sharing ? 'Gerando...' : `Ao Vivo de ${currentMonthLabel}`}
        </button>
        </>)}
      </div>
    </div>
  )
}
