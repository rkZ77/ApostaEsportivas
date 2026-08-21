import { useEffect, useState } from 'react'
import { Spinner } from './ui'
import { CalendarClock, BrainCircuit, DatabaseZap } from 'lucide-react'
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
 *
 * TRÊS ESTADOS, não dois. O card nasceu com "tem jogo" e "não tem jogo", e
 * faltava o que mais acontece em começo de temporada: TEM jogo, o motor já
 * analisou todos e nenhum pode virar pick porque os times não têm histórico.
 * Nesse caso a tela dizia "sendo analisados" e o usuário esperava um pick já
 * decidido que não vinha. Agora ela diz que não sai, e diz por quê.
 */
interface Fixture {
  fixture_id: number
  home_team: string; away_team: string
  home_team_id?: number; away_team_id?: number
  league_id?: number; league_name: string
  match_datetime: string
  /** Partidas de histórico de cada lado e o mínimo que o motor exige.
   *  `sem_historico` é conclusivo: com menos que o mínimo, não existe amostra
   *  pra estimar taxa e o jogo não vira pick de jeito nenhum. */
  jogos_casa?: number; jogos_fora?: number; min_jogos?: number
  sem_historico?: boolean
}

/** Hoje em Brasília, "YYYY-MM-DD". en-CA é o locale que devolve nessa ordem. */
function hojeBR(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
}

/**
 * "21:30" · fatiado da string, nunca por `new Date`.
 *
 * `match_datetime` chega em horário de Brasília SEM fuso ("2026-08-15T16:30:00").
 * Passar isso por `new Date` faz o navegador interpretar no fuso DELE e depois
 * reconverter, então um jogo das 16:30 virava outro horário para quem não
 * estivesse no Brasil. Mesma leitura de home/NextGames.
 */
const horaBR = (iso: string) => (iso ?? '').slice(11, 16)

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

  /*
   * A LISTA SAI DA TABELA LOCAL, não de uma varredura na API-Football.
   *
   * Antes vinha de GET /api/fixtures/today, que consulta a API liga por liga,
   * duas datas cada. Com as 10 ligas cadastradas são 20 requisições numa
   * rajada só, e as que passam do teto do plano voltam vazias em silêncio: na
   * tela apareciam apenas as primeiras ligas da ordem por league_id. Em
   * 15/08/2026 o banco tinha 12 jogos em 4 ligas e o card mostrava 3, todos da
   * Série A -- as outras três ligas tinham sido comidas pelo limite.
   *
   * `fixtures` é a resposta certa para esta pergunta de qualquer forma: o motor
   * analisa o que está nessa tabela, então "o que vai ser analisado hoje" é
   * exatamente uma consulta nela. Uma ida ao banco, zero chamada externa.
   */
  useEffect(() => {
    api.get('/public/next-fixtures', { params: { date: hojeBR(), limit: 30 } })
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
    // Sem `date`, a rota já é "daqui pra frente" e atravessa a virada do dia
    // sozinha · dispensa as sete chamadas em paralelo que procuravam, dia a
    // dia, o próximo com jogo.
    api.get('/public/next-fixtures', { params: { limit: 12 } })
      .then(r => setNextGames((r.data ?? []) as Fixture[]))
      .catch(() => setNextGames([]))
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
                        {horaBR(g.match_datetime)}
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

  /*
   * O jogo estar na tela nunca quis dizer que ele podia virar pick.
   *
   * O motor exige um mínimo de partidas de histórico por time pra ter amostra;
   * abaixo disso ele analisa, descarta e segue. Só que a tela dizia "N jogos
   * sendo analisados hoje" pros dois casos, e no começo de temporada isso vira
   * mentira em cima de trinta jogos: o usuário fica esperando um pick que já
   * foi decidido que não vem, sem nada explicando por quê.
   *
   * `sem_historico` vem do backend e é conclusivo · a conta de lá é sempre
   * mais frouxa que a do motor, então quando ela condena, está condenado.
   */
  const analisaveis   = todayGames.filter(g => !g.sem_historico)
  const semHistorico  = todayGames.filter(g => g.sem_historico)
  const minJogos      = todayGames.find(g => g.min_jogos)?.min_jogos ?? 5
  const nadaHojePorHistorico = todayGames.length > 0 && analisaveis.length === 0

  const linhaJogo = (g: Fixture, apagado = false) => (
    <div key={g.fixture_id}
      className={`flex items-center gap-2.5 border rounded-md px-3 py-2.5 ${
        apagado ? 'bg-surface-1/30 border-line/60' : 'bg-surface-1/70 border-line'}`}>
      <span className={`font-mono text-[11px] font-semibold tabular-nums shrink-0 w-9 ${
        apagado ? 'text-ink-4' : 'text-ink-3'}`}>
        {horaBR(g.match_datetime)}
      </span>
      <div className="flex items-center gap-1.5 flex-1 min-w-0">
        <TeamLogo id={g.home_team_id} name={g.home_team} size={18} />
        <span className={`text-xs font-medium truncate ${apagado ? 'text-ink-3' : 'text-ink-2'}`}>{g.home_team}</span>
        <span className="text-ink-4 text-[11px] shrink-0">x</span>
        <TeamLogo id={g.away_team_id} name={g.away_team} size={18} />
        <span className={`text-xs font-medium truncate ${apagado ? 'text-ink-3' : 'text-ink-2'}`}>{g.away_team}</span>
      </div>
      {apagado && (
        <span className="text-[10px] text-ink-4 shrink-0 tabular-nums hidden xs:inline">
          {Math.min(g.jogos_casa ?? 0, g.jogos_fora ?? 0)}/{minJogos}
        </span>
      )}
      <LeagueLogo id={g.league_id} name={g.league_name} />
    </div>
  )

  return (
    <div className="card p-8 text-center border-line">
      <div className="w-11 h-11 rounded-full bg-surface-2/80 flex items-center justify-center mx-auto mb-3">
        {nadaHojePorHistorico
          ? <DatabaseZap className="w-5 h-5 text-ink-2" />
          : <BrainCircuit className="w-5 h-5 text-ink-2" />}
      </div>

      {nadaHojePorHistorico ? (
        <>
          <p className="text-sm text-ink-2 font-bold mb-1">Hoje não sai pick</p>
          <p className="text-ink-3 text-sm max-w-md mx-auto leading-relaxed">
            Os {todayGames.length} jogos de hoje já foram analisados e nenhum passou. Os times ainda
            não têm as <b className="text-ink-2">{minJogos} partidas</b> de histórico que o motor
            precisa para estimar um mercado. É começo de temporada, e sem amostra ele não inventa
            número.
          </p>
          <p className="text-ink-4 text-xs mt-3">
            Conforme as rodadas acontecem o histórico enche sozinho e os picks voltam.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-2 font-bold mb-1">Os picks de hoje ainda não saíram</p>
          <p className="text-ink-3 text-sm">Assim que forem publicados você recebe um aviso.</p>
        </>
      )}

      {analisaveis.length > 0 && (
        <div className="text-left mt-6">
          <p className="text-[10px] text-ink-4 font-semibold mb-2">
            {analisaveis.length} jogo{analisaveis.length > 1 ? 's' : ''} com histórico
            {' '}sendo analisado{analisaveis.length > 1 ? 's' : ''} hoje
          </p>
          <div className="space-y-1.5">{analisaveis.map(g => linhaJogo(g))}</div>
        </div>
      )}

      {semHistorico.length > 0 && (
        <div className="text-left mt-6">
          <p className="text-[10px] text-ink-4 font-semibold mb-2">
            {nadaHojePorHistorico
              ? 'Jogos de hoje, sem histórico suficiente'
              : `${semHistorico.length} fora da análise, sem histórico suficiente`}
            <span className="font-normal"> (partidas do time com menos jogos / mínimo)</span>
          </p>
          <div className="space-y-1.5">{semHistorico.map(g => linhaJogo(g, true))}</div>
        </div>
      )}
    </div>
  )
}
