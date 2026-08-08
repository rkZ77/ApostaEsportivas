import { useEffect, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import api from '../services/api'
import { Badge, EmptyState, IconButton, Panel, PanelHead, Spinner, StatTile } from './ui'
import { TeamLogo, LeagueLogo } from './TeamLogo'

/*
 * Agenda dos jogos por dia, marcando o que a IA já analisou.
 *
 * O dado é o mesmo de /fixtures/today (que aceita ?date): cada jogo traz
 * `has_pick`. "Analisado" aqui significa "virou pick", que não é a mesma coisa
 * que "foi lido pela IA": o motor lê todos os jogos da liga e a maioria não
 * passa no corte de valor. O texto da tela diz isso, pra ninguém interpretar
 * um jogo sem pick como jogo ignorado.
 */

interface Fixture {
  fixture_id: number
  match_datetime: string
  home_team: string
  away_team: string
  home_team_id?: number
  away_team_id?: number
  league_id: number
  league_name: string
  has_pick?: boolean
}

const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

function shiftDate(d: string, days: number): string {
  const [y, m, dd] = d.split('-').map(Number)
  return new Date(y, m - 1, dd + days).toLocaleDateString('en-CA')
}

export default function AgendaInteligente() {
  const [date, setDate] = useState(TODAY)
  const [fixtures, setFixtures] = useState<Fixture[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.get('/fixtures/today', { params: { date } })
      .then(r => setFixtures(r.data ?? []))
      .catch(() => setFixtures([]))
      .finally(() => setLoading(false))
  }, [date])

  const visible = fixtures ?? []

  const comPick = visible.filter(f => f.has_pick).length
  const label = date === TODAY
    ? 'Hoje'
    : new Date(date + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit' })

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <StatTile label="Jogos no dia" value={String(visible.length)} />
        <StatTile label="Com pick" value={String(comPick)} tone={comPick > 0 ? 'green' : 'muted'} />
        <StatTile label="Sem valor" value={String(visible.length - comPick)} tone="muted" />
      </div>

      <Panel>
        <PanelHead
          label={<span className="flex items-center gap-2"><CalendarDays className="w-3.5 h-3.5" />Agenda</span>}
          meta={<span className="capitalize">{label}</span>}
        >
          <div className="flex items-center gap-1">
            <IconButton Icon={ChevronLeft} label="Dia anterior" size="sm" onClick={() => setDate(d => shiftDate(d, -1))} />
            <IconButton Icon={ChevronRight} label="Próximo dia" size="sm" onClick={() => setDate(d => shiftDate(d, 1))} />
          </div>
        </PanelHead>


        {loading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : visible.length === 0 ? (
          <EmptyState
            Icon={CalendarDays}
            title="Nenhum jogo nas ligas cobertas"
            description="Data FIFA e intervalo de temporada deixam a agenda vazia. Tente outro dia."
            compact
          />
        ) : (
          <div className="divide-y divide-line/50">
            {visible.map(f => (
              <div key={f.fixture_id} className="flex items-center gap-2.5 px-4 py-3">
                <span className="font-mono text-[11px] text-ink-4 tabular-nums shrink-0 w-9">
                  {new Date(f.match_datetime).toLocaleTimeString('pt-BR', {
                    hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo',
                  })}
                </span>
                <LeagueLogo id={f.league_id} name={f.league_name} />
                <div className="flex items-center gap-1.5 flex-1 min-w-0 text-xs text-ink-2">
                  <TeamLogo id={f.home_team_id} name={f.home_team} size={16} />
                  <span className="truncate">{f.home_team}</span>
                  <span className="text-ink-4 shrink-0">x</span>
                  <TeamLogo id={f.away_team_id} name={f.away_team} size={16} />
                  <span className="truncate">{f.away_team}</span>
                </div>
                {f.has_pick
                  ? <Badge tone="green">Pick</Badge>
                  : <span className="text-[10px] text-ink-4 shrink-0">sem valor</span>}
              </div>
            ))}
          </div>
        )}

        <p className="px-4 py-3 border-t border-line text-[11px] text-ink-4 leading-relaxed">
          A IA lê todos os jogos das ligas cobertas. "Sem valor" quer dizer que o jogo foi
          analisado e nenhum mercado passou no corte de valor esperado, não que ele foi ignorado.
        </p>
      </Panel>
    </div>
  )
}
