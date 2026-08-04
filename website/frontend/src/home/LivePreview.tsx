import { useEffect, useState } from 'react'
import { ArrowRight, Gift } from 'lucide-react'
import api from '../services/api'
import { Badge, Button, LiveDot, Panel, PanelHead, ResultBadge } from '../components/ui'
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

interface FreePick {
  id: number
  home_team_name: string
  away_team_name: string
  home_team_id?: number | null
  away_team_id?: number | null
  odd: number
  result: string | null
}

function useFreePick() {
  const [pick, setPick] = useState<FreePick | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get('/public/free-pick-today')
      .then(r => setPick(r.data ?? null))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return { pick, loading }
}

function FreePickCard({ pick }: { pick: FreePick }) {
  return (
    <div className="relative bg-surface-0 border border-accent/30 rounded-lg p-6 text-center">
      <div className="flex items-center justify-center gap-2 flex-wrap mb-4">
        <Badge tone="green" Icon={Gift}>Dica do dia</Badge>
        <span className="text-[11px] text-ink-3">grátis, sem precisar de conta</span>
        {pick.result && <ResultBadge result={pick.result} />}
      </div>

      <p className="font-display text-base sm:text-lg font-semibold text-ink-1 mb-1.5 flex items-center justify-center gap-2 flex-wrap">
        <TeamLogo id={pick.home_team_id ?? undefined} name={pick.home_team_name} size={18} />
        {pick.home_team_name}
        <span className="text-ink-4">x</span>
        {pick.away_team_name}
        <TeamLogo id={pick.away_team_id ?? undefined} name={pick.away_team_name} size={18} />
      </p>

      <p className="font-mono text-xs text-ink-3 mb-5">
        Gerado pela IA hoje · odd {Number(pick.odd).toFixed(2)}
      </p>

      <Button to={`/p/free/${pick.id}`} IconRight={ArrowRight}>
        Ver a análise completa
      </Button>
    </div>
  )
}

/**
 * A faixa inteira, decidindo se existe.
 *
 * Antes cada card sumia por conta própria devolvendo null, e a <section> em
 * volta continuava lá com o padding: em dia sem jogo e sem pick free, a Home
 * ganhava um vão vazio de umas cem alturas de linha entre o hero e os
 * resultados. Quem decide agora é a seção, que só renderiza se tiver o que pôr
 * dentro.
 */
export default function LivePreviewSection() {
  const { games, dateLabel } = useNextGames()
  const { pick, loading } = useFreePick()

  const hasGames = !!games && games.length > 0
  const hasPick = !loading && !!pick

  // `games === null` é "ainda buscando": segurar a seção nesse estado evita
  // que ela apareça e suma na cara do usuário.
  if (games === null || loading) return null
  if (!hasGames && !hasPick) return null

  return (
    <section className="section-tight">
      <div className="shell">
        <div className={`grid gap-5 items-start ${hasGames && hasPick ? 'md:grid-cols-2' : 'max-w-xl mx-auto'}`}>
          {hasGames && <NextGames games={games} dateLabel={dateLabel} />}
          {hasPick && <FreePickCard pick={pick} />}
        </div>
      </div>
    </section>
  )
}
