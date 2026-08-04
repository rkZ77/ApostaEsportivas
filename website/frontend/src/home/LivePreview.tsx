import { useEffect, useState } from 'react'
import api from '../services/api'
import { LiveDot, Panel, PanelHead } from '../components/ui'
import { TeamLogo } from '../components/TeamLogo'

/*
 * Prova ao vivo, ao lado do hero: os próximos jogos que a IA vai analisar e o
 * pick gratuito de hoje.
 *
 * Ambos vêm de endpoint público, sem login. É o que separa a Home de uma
 * página de vendas qualquer: o visitante vê dado real antes de criar conta.
 */

interface UpcomingFixture {
  fixture_id: number
  home_team: string
  away_team: string
  home_team_id?: number
  away_team_id?: number
  league_name: string
  match_datetime: string
}

function useNextGames() {
  const [games, setGames] = useState<UpcomingFixture[] | null>(null)
  const [dateLabel, setDateLabel] = useState('')

  useEffect(() => {
    const isoDate = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

    const fetchDay = (offset: number): Promise<UpcomingFixture[]> => {
      const d = new Date()
      d.setDate(d.getDate() + offset)
      return api
        .get('/fixtures/today', { params: offset === 0 ? {} : { date: isoDate(d) } })
        .then(r => (r.data ?? []) as UpcomingFixture[])
        .catch(() => [] as UpcomingFixture[])
    }

    // Hoje primeiro; se não houver jogo, anda até 3 dias pra frente. Sem isso a
    // Home ficava com um buraco em dia de data FIFA ou intervalo de temporada.
    ;(async () => {
      for (let offset = 0; offset <= 3; offset++) {
        const found = await fetchDay(offset)
        if (found.length > 0) {
          const d = new Date()
          d.setDate(d.getDate() + offset)
          setDateLabel(
            offset === 0
              ? 'Hoje'
              : d.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit' }),
          )
          setGames(found.slice(0, 5))
          return
        }
      }
      setGames([])
    })()
  }, [])

  return { games, dateLabel }
}

function NextGames({ games, dateLabel }: { games: UpcomingFixture[]; dateLabel: string }) {
  return (
    <Panel>
      <PanelHead
        label={
          <span className="flex items-center gap-2">
            <LiveDot />
            Na fila da IA
          </span>
        }
        meta={dateLabel}
      />
      <div className="divide-y divide-line/50">
        {games.map(g => (
          <div key={g.fixture_id} className="flex items-center gap-2.5 px-4 py-2.5">
            <span className="font-mono text-[11px] text-ink-4 tabular-nums shrink-0 w-9">
              {new Date(g.match_datetime).toLocaleTimeString('pt-BR', {
                hour: '2-digit',
                minute: '2-digit',
                timeZone: 'America/Sao_Paulo',
              })}
            </span>
            <div className="flex items-center gap-1.5 flex-1 min-w-0 text-xs text-ink-2">
              <TeamLogo id={g.home_team_id} name={g.home_team} size={16} />
              <span className="truncate">{g.home_team}</span>
              <span className="text-ink-4 shrink-0">x</span>
              <TeamLogo id={g.away_team_id} name={g.away_team} size={16} />
              <span className="truncate">{g.away_team}</span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

/**
 * A faixa inteira, decidindo se existe.
 *
 * Quem decide é a seção, e não o card: quando o card sumia sozinho devolvendo
 * null, a <section> em volta ficava com o padding e a Home ganhava um vão
 * vazio entre o hero e os resultados em dia sem jogo.
 */
export default function LivePreviewSection() {
  const { games, dateLabel } = useNextGames()

  // Só a fila de jogos. A Dica do Dia subiu pro hero (home/FreePickHero) e
  // mostrar o mesmo pick duas vezes na mesma tela só diluía os dois.
  if (games === null) return null
  if (games.length === 0) return null

  return (
    <section className="section-tight">
      <div className="shell-narrow">
        <NextGames games={games} dateLabel={dateLabel} />
      </div>
    </section>
  )
}
