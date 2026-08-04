import { useEffect, useState } from 'react'
import { Spinner } from './ui'
import { CalendarClock, BrainCircuit } from 'lucide-react'
import api from '../services/api'
import { TeamLogo, LeagueLogo } from './TeamLogo'

/**
 * Estado da aba de picks quando ainda não há pick publicado hoje.
 *
 * Era uma contagem regressiva ("Picks chegam até às 12h · Brasília" com
 * relógio tiquetaqueando). Removida em 2026-08-01: o pipeline deixou de rodar
 * em horário fixo (o scheduler foi removido, o usuário gera e publica na hora
 * que quiser), então prometer horário na tela seria mentira.
 *
 * O que ficou é o que continua verdadeiro sem depender de horário: quais jogos
 * estão sendo analisados hoje, ou -- se não tem jogo nenhum nas ligas cobertas
 * -- quais são os próximos.
 */
interface Fixture {
  fixture_id: number
  home_team: string; away_team: string
  home_team_id?: number; away_team_id?: number
  league_id?: number; league_name: string
  match_datetime: string
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Mesmo endpoint que a aba "Jogos" usa (busca ao vivo na API-Football pelas
// ligas cadastradas, não só a tabela local) -- tenta os próximos dias até
// achar algum com jogo, em vez de só checar hoje. Busca os 7 dias em
// paralelo (não um de cada vez) pra não somar a latência de cada chamada
// quando os primeiros dias vêm vazios.
async function findNextGames(): Promise<Fixture[]> {
  const today = new Date()
  const dates = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(today)
    d.setDate(d.getDate() + i + 1)
    return isoDate(d)
  })
  const perDay = await Promise.all(
    dates.map(date =>
      api.get('/fixtures/today', { params: { date } })
        .then(r => (r.data ?? []) as Fixture[])
        .catch(() => [] as Fixture[])
    )
  )
  for (const games of perDay) {
    if (games.length > 0) return games
  }
  return []
}

function groupByDate(games: Fixture[]): { dateLabel: string; games: Fixture[] }[] {
  const groups = new Map<string, Fixture[]>()
  for (const g of games) {
    const key = g.match_datetime.slice(0, 10)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(g)
  }
  return Array.from(groups.entries()).map(([key, games]) => ({
    dateLabel: new Date(`${key}T12:00:00`).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' }),
    games,
  }))
}

export default function PicksPendingCard() {
  // null = ainda carregando, 0 = confirmado sem jogo hoje, >0 = tem jogo
  const [todayCount, setTodayCount] = useState<number | null>(null)
  // Erro de rede não deve travar o componente em branco pra sempre --
  // sem isso, "carregando" e "falhou" ficavam com o mesmo estado (null) e
  // qualquer falha passageira escondia o card permanentemente.
  const [todayCheckFailed, setTodayCheckFailed] = useState(false)
  const [todayGames, setTodayGames] = useState<Fixture[]>([])
  const [nextGames, setNextGames] = useState<Fixture[] | null>(null)
  const [leagueNames, setLeagueNames] = useState<string | null>(null)

  useEffect(() => {
    api.get('/fixtures/today')
      .then(r => {
        const games = (r.data ?? []) as Fixture[]
        setTodayGames(games)
        setTodayCount(games.length)
      })
      .catch(() => setTodayCheckFailed(true))
  }, [])

  useEffect(() => {
    if (todayCount !== 0) return
    api.get('/public/leagues')
      .then(r => setLeagueNames((r.data ?? []).map((l: any) => l.name).join(', ')))
      .catch(() => setLeagueNames(''))
    findNextGames().then(setNextGames).catch(() => setNextGames([]))
  }, [todayCount])

  // Ainda checando se há jogo hoje (e não falhou) -- mostra nada por um instante,
  // não a vida toda: se der erro, cai pro estado normal.
  if (todayCount === null && !todayCheckFailed) return null

  // Sem jogo nenhum hoje nas ligas cobertas -- mostra os próximos.
  // Se a checagem falhou, não sabemos se há jogo ou não -- assume que sim
  // (comportamento normal) em vez de esconder o card sem motivo aparente.
  if (todayCount === 0 && !todayCheckFailed) {
    const groups = nextGames ? groupByDate(nextGames.slice(0, 8)) : []
    return (
      <div className="card p-6 text-center border-line">
        <div className="w-11 h-11 rounded-full bg-surface-2/80 flex items-center justify-center mx-auto mb-3">
          <CalendarClock className="w-5 h-5 text-ink-2" />
        </div>
        <p className="text-sm text-ink-2 font-bold mb-1">Sem jogos hoje nas ligas que cobrimos</p>
        {leagueNames && <p className="text-ink-4 text-xs mb-5">{leagueNames}</p>}
        {nextGames === null ? (
          <div className="flex justify-center py-3">
            <Spinner size="sm" tone="ink" />
          </div>
        ) : groups.length === 0 ? (
          <p className="text-ink-4 text-xs">Nenhum próximo jogo agendado ainda.</p>
        ) : (
          <div className="text-left space-y-4">
            <p className="text-[10px] text-ink-4 font-semibold">Próximos jogos</p>
            {groups.map(group => (
              <div key={group.dateLabel}>
                <p className="text-[11px] text-ink-3 font-semibold capitalize mb-1.5">{group.dateLabel}</p>
                <div className="space-y-1.5">
                  {group.games.map(g => (
                    <div key={g.fixture_id}
                      className="flex items-center gap-2.5 bg-surface-1/70 border border-line rounded-md px-3 py-2.5 hover:border-line-strong transition-colors">
                      <span className="font-mono text-[11px] text-ink-3 font-semibold tabular-nums shrink-0 w-9">
                        {new Date(g.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })}
                      </span>
                      <div className="flex items-center gap-1.5 flex-1 min-w-0">
                        <TeamLogo id={g.home_team_id} name={g.home_team} size={18} />
                        <span className="text-xs text-ink-2 font-medium truncate">{g.home_team}</span>
                        <span className="text-ink-4 text-[11px] shrink-0">x</span>
                        <TeamLogo id={g.away_team_id} name={g.away_team} size={18} />
                        <span className="text-xs text-ink-2 font-medium truncate">{g.away_team}</span>
                      </div>
                      <LeagueLogo id={g.league_id} name={g.league_name} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="card p-8 text-center border-line">
      <div className="w-11 h-11 rounded-full bg-surface-2/80 flex items-center justify-center mx-auto mb-3">
        <BrainCircuit className="w-5 h-5 text-ink-2" />
      </div>
      <p className="text-sm text-ink-2 font-bold mb-1">Os picks de hoje ainda não saíram</p>
      <p className="text-ink-3 text-sm">Assim que forem publicados você recebe um aviso.</p>
      {todayGames.length > 0 && (
        <div className="text-left mt-6">
          <p className="text-[10px] text-ink-4 font-semibold mb-2">
            {todayGames.length} jogo{todayGames.length > 1 ? 's' : ''} sendo analisado{todayGames.length > 1 ? 's' : ''} hoje
          </p>
          <div className="space-y-1.5">
            {todayGames.map(g => (
              <div key={g.fixture_id}
                className="flex items-center gap-2.5 bg-surface-1/70 border border-line rounded-md px-3 py-2.5">
                <span className="font-mono text-[11px] text-ink-3 font-semibold tabular-nums shrink-0 w-9">
                  {new Date(g.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })}
                </span>
                <div className="flex items-center gap-1.5 flex-1 min-w-0">
                  <TeamLogo id={g.home_team_id} name={g.home_team} size={18} />
                  <span className="text-xs text-ink-2 font-medium truncate">{g.home_team}</span>
                  <span className="text-ink-4 text-[11px] shrink-0">x</span>
                  <TeamLogo id={g.away_team_id} name={g.away_team} size={18} />
                  <span className="text-xs text-ink-2 font-medium truncate">{g.away_team}</span>
                </div>
                <LeagueLogo id={g.league_id} name={g.league_name} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
