import { useEffect, useState } from 'react'
import { Spinner } from './ui'
import { CalendarClock, BrainCircuit, ChevronDown, DatabaseZap, CircleCheck,
         CircleSlash } from 'lucide-react'
import api from '../services/api'
import { sinalizarNavegacao } from '../services/progressBus'
import { TeamLogo, LeagueLogo } from './TeamLogo'

/** Quantos jogos a lista mostra antes de pedir pra expandir.
 *
 * Cinco porque é o que cabe numa tela de celular sem empurrar pra fora o que
 * vem depois · e o que vem depois é a explicação de por que não saiu pick,
 * que é a razão de a pessoa estar nesta tela.
 */
const JOGOS_VISIVEIS = 5

/**
 * Lista de jogos que não vira parede.
 *
 * Numa manhã de sábado o card despejava as trinta e poucas partidas do dia,
 * uma linha cada, e o rodapé do site ficava a três telas de rolagem do topo ·
 * no celular, pior. E a lista inteira responde a mesma pergunta que as cinco
 * primeiras já respondem ("tem jogo, e o motor olhou"): quem quer conferir
 * time por time abre; quem só queria saber por que não tem pick, não rola.
 *
 * Expandida, o botão vira "Mostrar menos" e fica NO FIM da lista: sem isso,
 * recolher exigia rolar de volta os trinta jogos que a pessoa acabou de abrir.
 */
function ListaDeJogos({ jogos, render, rotulo }: {
  jogos: Fixture[]
  render: (g: Fixture) => React.ReactNode
  /** Plural do que está sendo listado, pro rótulo do botão ("jogos"). */
  rotulo: string
}) {
  const [aberta, setAberta] = useState(false)
  const cabeInteira = jogos.length <= JOGOS_VISIVEIS
  const visiveis = aberta || cabeInteira ? jogos : jogos.slice(0, JOGOS_VISIVEIS)
  const ocultos = jogos.length - JOGOS_VISIVEIS
  const porLiga = agruparPorLiga(visiveis)

  return (
    <>
      {/* SEPARADO POR LIGA (2026-09-05, pedido do usuario). Aberta, a lista
          passa de quarenta linhas num sabado, e "Preston x Blackburn" no meio
          de trinta e nove outras nao diz de que competicao e' -- o escudo no
          fim da linha e' pequeno demais pra servir de indice. O cabecalho de
          liga transforma a parede numa lista de competicoes com poucos jogos
          cada, que e' como o dia realmente e'. */}
      <div className="space-y-3">
        {porLiga.map(grupo => (
          <div key={grupo.chave}>
            <p className="flex items-center gap-1.5 mb-1.5">
              <LeagueLogo id={grupo.league_id} name={grupo.league_name} />
              <span className="text-[11px] font-semibold text-ink-3 truncate">{grupo.league_name}</span>
              <span className="text-[10px] text-ink-4 tabular-nums shrink-0">{grupo.jogos.length}</span>
            </p>
            <div className="space-y-1.5">{grupo.jogos.map(render)}</div>
          </div>
        ))}
      </div>
      {!cabeInteira && (
        <button
          /* A barra do topo responde a esta espera igual às outras do site
             (ver services/progressBus): abrir a lista inteira é a mesma troca
             de contexto que trocar de aba, e desde 29/08 o site inteiro
             responde a esse tipo de espera do mesmo jeito. */
          onClick={() => { sinalizarNavegacao(); setAberta(a => !a) }}
          className="mt-2 w-full flex items-center justify-center gap-1.5 text-[11px] font-semibold
                     text-ink-3 hover:text-ink-1 border border-line hover:border-line-strong
                     rounded-md py-2.5 min-h-[36px] transition-colors"
        >
          <ChevronDown className={`w-3.5 h-3.5 shrink-0 transition-transform ${aberta ? 'rotate-180' : ''}`} />
          {aberta ? 'Mostrar menos' : `Ver os outros ${ocultos} ${rotulo}`}
        </button>
      )}
    </>
  )
}

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

/** O dia de um jogo, "YYYY-MM-DD", nos dois formatos que o backend usa. */
const diaDoJogo = (iso: string) => (iso ?? '').slice(0, 10)

/**
 * "21:30" · fatiado da string, nunca por `new Date`.
 *
 * `match_datetime` chega em horário de Brasília SEM fuso ("2026-08-15T16:30:00").
 * Passar isso por `new Date` faz o navegador interpretar no fuso DELE e depois
 * reconverter, então um jogo das 16:30 virava outro horário para quem não
 * estivesse no Brasil. Mesma leitura de home/NextGames.
 */
const horaBR = (iso: string) => (iso ?? '').slice(11, 16)

/** Jogos agrupados por competicao, na ordem em que a liga aparece na lista
 *  (que ja' chega ordenada por horario), e por horario dentro de cada uma. */
function agruparPorLiga(jogos: Fixture[]): {
  chave: string; league_id?: number; league_name: string; jogos: Fixture[]
}[] {
  const grupos = new Map<string, { chave: string; league_id?: number; league_name: string; jogos: Fixture[] }>()
  for (const g of jogos) {
    const chave = String(g.league_id ?? g.league_name)
    const grupo = grupos.get(chave)
      ?? { chave, league_id: g.league_id, league_name: g.league_name, jogos: [] }
    grupo.jogos.push(g)
    grupos.set(chave, grupo)
  }
  return Array.from(grupos.values())
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
    // TODOS os jogos do dia, nao os 30 primeiros: num sabado as ligas cobertas
    // passam de 40 partidas, e o corte antigo era mudo -- a tela anunciava "30
    // jogos podem virar pick hoje" num dia de 44. A lista continua colapsada em
    // cinco (ver ListaDeJogos), entao mostrar tudo nao vira parede.
    api.get('/public/next-fixtures', { params: { date: hojeBR(), limit: 200 } })
      .then(r => {
        /* `Array.isArray`, e não `r.data ?? []`: a rota devolve lista, e
           qualquer outra coisa (erro serializado, resposta de proxy, HTML de
           uma página de erro) passa pelo `??` e chega inteira no `.filter` lá
           embaixo. Um `filter is not a function` ali não estraga este card: ele
           sobe pro ErrorBoundary e derruba a PÁGINA DE PICKS inteira, com um
           "Algo deu errado" no lugar dos picks.
           Mesma trava que LivePicks já tem em /live/my-picks. */
        const games = (Array.isArray(r.data) ? r.data : []) as Fixture[]
        setTodayGames(games)
        setTodayCount(games.length)
      })
      .catch(() => setTodayCheckFailed(true))
  }, [])

  /*
   * DUAS consultas, e é de propósito.
   *
   * A de cima pede o DIA INTEIRO, e é dela que sai a explicação ("os N jogos de
   * hoje já foram analisados e nenhum passou") -- essa conta é sobre o dia,
   * não sobre a hora.
   *
   * Esta aqui pede "daqui pra frente", que é o padrão da rota, e é dela que sai
   * o que a tela LISTA. Antes a lista saía do dia inteiro e por isso continuava
   * anunciando às 22h os jogos das 15h como "sendo analisados hoje".
   *
   * QUEM CORTA É O SERVIDOR. Dava pra comparar `match_datetime` com o relógio
   * do navegador, mas aí o corte dependeria do fuso de quem está lendo: o campo
   * vem em horário de Brasília SEM fuso, e um usuário em Lisboa esconderia
   * jogo que ainda não começou. A rota já faz esse corte contra o relógio de
   * Brasília (ver public_next_fixtures), então a resposta dela é a definição de
   * "ainda vai acontecer".
   */
  useEffect(() => {
    api.get('/public/next-fixtures', { params: { limit: 200 } })
      .then(r => setNextGames((Array.isArray(r.data) ? r.data : []) as Fixture[]))
      .catch(() => setNextGames([]))
  }, [])

  useEffect(() => {
    if (todayCount !== 0) return
    api.get('/public/leagues')
      // `ativa !== false` porque a rota devolve o histórico junto: sem o
      // filtro, o card diz que está esperando jogo da Copa do Mundo, que
      // acabou.
      .then(r => setLeagueNames((r.data ?? [])
        .filter((l: any) => l.ativa !== false)
        .map((l: any) => l.name).join(', ')))
      .catch(() => setLeagueNames(''))
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
  /* O que a rota "daqui pra frente" devolveu, separado por dia. `porComecar`
     são os de HOJE que ainda não começaram; `outrosDias` é o que vem depois. */
  const hoje          = hojeBR()
  const aindaVem      = nextGames ?? []
  const porComecar    = aindaVem.filter(g => diaDoJogo(g.match_datetime) === hoje)
  const outrosDias    = aindaVem.filter(g => diaDoJogo(g.match_datetime) !== hoje)
  const todosJaComecaram = todayGames.length > 0 && nextGames !== null && porComecar.length === 0

  /*
   * Duas perguntas diferentes, duas contas diferentes.
   *
   * O TÍTULO ("hoje não sai pick") é sobre o DIA: ele só vale se nenhum jogo do
   * dia tinha histórico, tendo começado ou não. Contar só o que falta começar
   * fazia a tela virar "hoje não sai pick" no meio da tarde só porque os jogos
   * com amostra já tinham entrado em campo.
   *
   * As LISTAS são sobre o que ainda vai acontecer, que é onde a pessoa ainda
   * pode agir.
   */
  const comHistoricoHoje = todayGames.filter(g => !g.sem_historico)
  const analisaveis   = porComecar.filter(g => !g.sem_historico)
  const semHistorico  = porComecar.filter(g => g.sem_historico)
  const minJogos      = todayGames.find(g => g.min_jogos)?.min_jogos ?? 5
  const nadaHojePorHistorico = todayGames.length > 0 && comHistoricoHoje.length === 0
  /** Tinha candidato hoje, mas todos já entraram em campo. */
  const candidatosJaComecaram = comHistoricoHoje.length > 0 && analisaveis.length === 0

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
      {/* `xs:` NAO EXISTE nesta config do Tailwind (nao ha' `screens.xs`), e
          classe inexistente nao gera CSS: `hidden xs:inline` escondia a
          contagem em TODA largura, inclusive no desktop. O numero de jogos que
          faltam pro time ter amostra e' o que a legenda logo acima promete
          explicar, entao ele nunca aparecia. `sm:` e' o breakpoint que
          existe (640px). */}
      {apagado && (
        <span className="text-[10px] text-ink-4 shrink-0 tabular-nums hidden sm:inline">
          {Math.min(g.jogos_casa ?? 0, g.jogos_fora ?? 0)}/{minJogos}
        </span>
      )}
      {/* Sem escudo no fim da linha: ele agora encabeca o grupo, e repetir a
          mesma marca em todas as linhas da competicao e' ruido. */}
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

      {/*
        DE ONDE PODE SAIR PICK, e de onde não pode.

        Os dois grupos já existiam, mas os rótulos falavam de processo ("sendo
        analisados") em vez de resultado, e a única diferença visual era o tom
        apagado do segundo. Quem olhava a tela não conseguia responder a única
        pergunta que interessa ali: destes jogos, quais ainda podem virar pick
        hoje?

        Agora o rótulo responde isso em palavras, e o ícone repete a resposta
        sem depender de cor · o grupo de baixo continua apagado, mas não é o
        apagamento que carrega o significado.
      */}
      {analisaveis.length > 0 && (
        <div className="text-left mt-6">
          {/* Título e legenda em LINHAS separadas, não lado a lado: num
              celular de 390px os dois na mesma linha viravam duas colunas
              estreitas, cada uma quebrando no meio da frase. */}
          <p className="text-[11px] text-accent-ink font-semibold flex items-center gap-1.5">
            <CircleCheck className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
            {analisaveis.length === 1
              ? '1 jogo pode virar pick hoje'
              : `${analisaveis.length} jogos podem virar pick hoje`}
          </p>
          <p className="text-[10px] text-ink-4 mt-0.5 mb-2 ml-5">
            Têm o histórico que o motor precisa.
          </p>
          <ListaDeJogos jogos={analisaveis} rotulo="jogos" render={g => linhaJogo(g)} />
        </div>
      )}

      {/* Tinha candidato hoje e todos já entraram em campo. Dizer isso evita a
          leitura de que o dia inteiro estava condenado desde cedo. */}
      {candidatosJaComecaram && !nadaHojePorHistorico && (
        <p className="text-[11px] text-ink-4 mt-6 text-left">
          {comHistoricoHoje.length === 1
            ? 'O jogo com histórico de hoje já começou.'
            : `Os ${comHistoricoHoje.length} jogos com histórico de hoje já começaram.`}
        </p>
      )}

      {semHistorico.length > 0 && (
        <div className="text-left mt-6">
          <p className="text-[11px] text-ink-3 font-semibold flex items-center gap-1.5">
            <CircleSlash className="w-3.5 h-3.5 shrink-0 text-ink-4" aria-hidden="true" />
            {semHistorico.length === 1
              ? '1 jogo não vira pick hoje'
              : `${semHistorico.length} jogos não viram pick hoje`}
          </p>
          <p className="text-[10px] text-ink-4 mt-0.5 mb-2 ml-5">
            O número à direita é do time com menos jogos, sobre as {minJogos} exigidas.
          </p>
          <ListaDeJogos jogos={semHistorico} rotulo="jogos" render={g => linhaJogo(g, true)} />
        </div>
      )}

      {/*
        Acabaram os jogos de hoje · mostra o que vem.

        O rótulo diz "entram na análise no dia" de propósito: a janela do motor
        é HOJE, então listar os jogos de amanhã como "sendo analisados" seria
        prometer um pick que não vai sair antes de amanhecer.
      */}
      {todosJaComecaram && (
        <div className="text-left mt-6">
          <p className="text-[10px] text-ink-4 font-semibold mb-2">
            Os jogos de hoje já começaram.
            <span className="font-normal"> Estes entram na análise no dia deles.</span>
          </p>
          {outrosDias.length === 0 ? (
            <p className="text-ink-4 text-xs">Nenhum próximo jogo agendado ainda.</p>
          ) : (
            <div className="space-y-3">
              {groupByDate(outrosDias.slice(0, 8)).map(({ dateLabel, games }) => (
                <div key={dateLabel}>
                  <p className="text-[10px] text-ink-4 mb-1.5 capitalize">{dateLabel}</p>
                  {/* Por liga tambem aqui: o escudo saiu da linha, entao sem o
                      cabecalho estes jogos ficariam sem competicao nenhuma. */}
                  <div className="space-y-2">
                    {agruparPorLiga(games).map(grupo => (
                      <div key={grupo.chave}>
                        <p className="flex items-center gap-1.5 mb-1">
                          <LeagueLogo id={grupo.league_id} name={grupo.league_name} />
                          <span className="text-[11px] font-semibold text-ink-3 truncate">{grupo.league_name}</span>
                        </p>
                        <div className="space-y-1.5">{grupo.jogos.map(g => linhaJogo(g))}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
