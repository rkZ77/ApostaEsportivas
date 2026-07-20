import { useEffect, useState } from 'react'
import api from '../services/api'
import { TeamLogo, LeagueLogo } from './TeamLogo'

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
// achar algum com jogo, em vez de só checar hoje.
async function findNextGames(): Promise<Fixture[]> {
  const today = new Date()
  for (let i = 1; i <= 7; i++) {
    const d = new Date(today)
    d.setDate(d.getDate() + i)
    try {
      const r = await api.get('/fixtures/today', { params: { date: isoDate(d) } })
      if (r.data && r.data.length > 0) return r.data
    } catch { /* tenta o próximo dia */ }
  }
  return []
}

export default function CountdownTo7AM() {
  const [timeLeft, setTimeLeft] = useState<string | null>(null)
  // null = ainda carregando, 0 = confirmado sem jogo hoje, >0 = tem jogo
  const [todayCount, setTodayCount] = useState<number | null>(null)
  // Erro de rede não deve travar o componente em branco pra sempre --
  // sem isso, "carregando" e "falhou" ficavam com o mesmo estado (null) e
  // qualquer falha passageira escondia o card permanentemente.
  const [todayCheckFailed, setTodayCheckFailed] = useState(false)
  const [nextGames, setNextGames] = useState<Fixture[] | null>(null)
  const [leagueNames, setLeagueNames] = useState<string | null>(null)

  useEffect(() => {
    const update = () => {
      const brNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }))
      if (brNow.getHours() >= 12) { setTimeLeft(null); return }
      const target = new Date(brNow)
      target.setHours(12, 0, 0, 0)
      if (brNow >= target) target.setDate(target.getDate() + 1)
      const diff = target.getTime() - brNow.getTime()
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setTimeLeft(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`)
    }
    update()
    const t = setInterval(update, 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    api.get('/fixtures/today')
      .then(r => setTodayCount((r.data ?? []).length))
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
  // não a vida toda: se der erro, cai pro comportamento normal do contador.
  if (todayCount === null && !todayCheckFailed) return null

  // Sem jogo nenhum hoje nas ligas cobertas -- mostra os próximos em vez de
  // uma contagem regressiva enganosa (nada vai chegar até as 12h nesse caso).
  // Se a checagem falhou, não sabemos se há jogo ou não -- assume que sim
  // (comportamento normal) em vez de esconder o card sem motivo aparente.
  if (todayCount === 0 && !todayCheckFailed) {
    return (
      <div className="card p-6 text-center border-zinc-800">
        <p className="text-sm text-zinc-300 font-bold mb-1">Sem jogos hoje nas ligas que cobrimos</p>
        {leagueNames && <p className="text-zinc-600 text-xs mb-4">{leagueNames}</p>}
        {nextGames === null ? (
          <div className="h-8" />
        ) : nextGames.length === 0 ? (
          <p className="text-zinc-600 text-xs">Nenhum próximo jogo agendado ainda.</p>
        ) : (
          <div className="text-left">
            <p className="text-[10px] text-zinc-600 uppercase tracking-wider font-semibold mb-2">Próximos jogos</p>
            <div className="space-y-1.5">
              {nextGames.slice(0, 4).map(g => (
                <div key={g.fixture_id} className="flex items-center gap-2 bg-zinc-900/60 border border-zinc-800 rounded-lg px-3 py-2">
                  <span className="text-[10px] text-zinc-500 shrink-0 w-12">
                    {new Date(g.match_datetime).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                  </span>
                  <TeamLogo id={g.home_team_id} name={g.home_team} size={16} />
                  <span className="text-xs text-zinc-300 truncate flex-1">{g.home_team} x {g.away_team}</span>
                  <LeagueLogo id={g.league_id} name={g.league_name} />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  if (timeLeft === null) return null

  return (
    <div className="card p-8 text-center border-zinc-800">
      <p className="text-sm text-zinc-500 font-bold mb-4">Picks chegam até às 12h · Brasília</p>
      <div className="text-4xl font-black text-green-400 tabular-nums tracking-tight mb-3">{timeLeft}</div>
      <p className="text-zinc-500 text-sm">A IA está analisando os jogos de hoje...</p>
    </div>
  )
}
