import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import { Check } from 'lucide-react'
import { LiveDot, Marquee, Skeleton } from '../components/ui'
import { TeamLogo, LeagueLogo } from '../components/TeamLogo'

/*
 * Na fila da IA · os próximos jogos que ainda vão ser analisados.
 *
 * Fica entre o card da Dica do Dia e a faixa de indicadores, e não é enfeite
 * de posição: o card acima é UM pick, os números abaixo são o histórico
 * inteiro. No meio falta justamente o presente · o que está para acontecer.
 *
 * Duas coisas mudaram em relação à versão anterior (home/LivePreview):
 *
 * 1. A lista é "daqui pra frente", não "hoje". A rota antiga pedia o dia
 *    inteiro e listava partida que já tinha rolado; quando os jogos do dia
 *    acabavam, a faixa sumia da Home em vez de andar para os de amanhã. Agora
 *    o corte é por horário e a lista atravessa a virada do dia sozinha · por
 *    isso cada card carrega o dia dele.
 *
 * 2. É uma fita horizontal que anda E se deixa empurrar.
 *
 *    Passou por uma grade empilhada no meio do caminho, e ela resolvia o
 *    problema errado: com a lista inteira à mostra, uma rodada cheia virava
 *    quinze linhas de card no celular e empurrava o resto da Home pra baixo.
 *
 *    De volta à fita, com o que faltava nela: dá pra arrastar. O motivo da
 *    grade era não precisar ESPERAR o jogo chegar; empurrar com o dedo resolve
 *    isso sem custar altura de página. A mecânica mora em components/ui/Marquee
 *    e vale também para a fita de ligas.
 *
 * 3. A lista ENCOLHE sozinha conforme os jogos começam.
 *
 *    O corte do servidor só vale no instante da resposta. Numa aba deixada
 *    aberta, a faixa continuava anunciando como "na fila" partida que já tinha
 *    começado há horas. Agora um relógio local tira cada jogo no minuto do
 *    apito, e uma rebuscada a cada 5 minutos traz os que entraram na janela.
 *    Quando não sobra nenhum, a seção some inteira.
 */

interface UpcomingFixture {
  fixture_id: number
  home_team: string
  away_team: string
  home_team_id?: number
  away_team_id?: number
  league_id?: number
  league_name: string
  /** Horário de Brasília SEM fuso: "2026-08-07T21:30:00". */
  match_datetime: string
  /** Já saiu pick para esta partida. NUNCA vem o mercado junto. */
  has_pick?: boolean
  pick_type?: 'vip' | 'free' | null
  /** Times sem as partidas de histórico que o motor exige · este jogo não vai
   *  virar pick, e chamar isso de "na fila da IA" seria promessa falsa. */
  sem_historico?: boolean
}

/** Hoje em Brasília, "YYYY-MM-DD". en-CA é o locale que devolve nessa ordem. */
function hojeBR(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
}

/**
 * Rótulo do dia do jogo, relativo a hoje.
 *
 * Compara as datas como texto, sem converter fuso: `match_datetime` já chega
 * em horário de Brasília. Passar por `new Date()` aqui reintroduziria o fuso
 * do navegador e faria um jogo das 21h virar "amanhã" para quem estivesse
 * fora do Brasil.
 */
function rotuloDia(iso: string, hoje: string): { texto: string; ehHoje: boolean } {
  const dia = iso.slice(0, 10)
  if (dia === hoje) return { texto: 'Hoje', ehHoje: true }

  const amanha = new Date(`${hoje}T12:00:00`)
  amanha.setDate(amanha.getDate() + 1)
  if (dia === amanha.toLocaleDateString('en-CA')) return { texto: 'Amanhã', ehHoje: false }

  const d = new Date(`${dia}T12:00:00`)
  const semana = d.toLocaleDateString('pt-BR', { weekday: 'short' }).replace('.', '')
  return {
    texto: `${semana.charAt(0).toUpperCase()}${semana.slice(1)} ${dia.slice(8, 10)}/${dia.slice(5, 7)}`,
    ehHoje: false,
  }
}

/** "21:30". Fatiado da string, não formatado por Date · ver rotuloDia. */
const horaBR = (iso: string) => iso.slice(11, 16)

/**
 * Agora em Brasília, "YYYY-MM-DDTHH:mm", para comparar com `match_datetime`.
 *
 * Comparação de TEXTO, e não de Date, pelo mesmo motivo de `rotuloDia`:
 * `match_datetime` chega em horário de Brasília SEM fuso, então virar Date faz
 * o navegador aplicar o fuso DELE num valor que já está em Brasília, e o corte
 * erra por horas para quem não está no Brasil. Nesse formato o texto ordena
 * igual à data, então `<` já responde "esse jogo já começou?".
 */
function agoraBR(): string {
  const d = new Date()
  const dia = d.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
  /* `hourCycle: 'h23'` e não `hour12: false`. Os dois pedem relógio de 24
     horas, mas `hour12: false` deixa a escolha entre h23 e h24 pro motor, e o
     WebKit já devolveu "24:30" pra meia-noite e meia. Nesse formato de texto,
     "24:30" é maior que QUALQUER horário de jogo · a faixa inteira sumiria da
     Home entre 00h e 01h no iPhone, sem erro nenhum no console. */
  const hora = d.toLocaleTimeString('pt-BR', {
    timeZone: 'America/Sao_Paulo', hourCycle: 'h23', hour: '2-digit', minute: '2-digit',
  })
  return `${dia}T${hora}`
}

/** "2026-08-22 16:00:00" e "2026-08-22T16:00:00" viram a mesma chave. */
const quando = (iso: string) => (iso ?? '').replace(' ', 'T').slice(0, 16)

function GameCard({ game, hoje }: { game: UpcomingFixture; hoje: string }) {
  const dia = rotuloDia(game.match_datetime, hoje)

  return (
    <article
      className="shrink-0 w-[196px] sm:w-[212px] bg-surface-0 border border-line rounded-lg p-3
                 hover:border-line-strong transition-colors duration-1 ease-smooth"
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <span
          className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
            dia.ehHoje ? 'bg-accent/15 text-accent-ink' : 'bg-surface-2 text-ink-3'
          }`}
        >
          {dia.texto}
        </span>
        <span className="font-mono text-[11px] font-bold text-ink-2 tabular-nums shrink-0">
          {horaBR(game.match_datetime)}
        </span>
      </div>

      <div className="space-y-1.5">
        {[
          { id: game.home_team_id, nome: game.home_team },
          { id: game.away_team_id, nome: game.away_team },
        ].map(({ id, nome }) => (
          <div key={nome} className="flex items-center gap-2 min-w-0">
            <TeamLogo id={id} name={nome} size={20} />
            <span className="text-sm text-ink-1 font-medium truncate">{nome}</span>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-1.5 mt-3 pt-2.5 border-t border-line/60 min-w-0">
        <LeagueLogo id={game.league_id} name={game.league_name} />
        <span className="text-[10px] text-ink-4 truncate">{game.league_name}</span>
      </div>

      {/*
        Estado da análise.
        
        Diz SE saiu pick, nunca QUAL · o mercado é o que a Dica do Dia esconde
        atrás de cadastro três blocos acima nesta mesma página, e entregá-lo
        aqui de graça esvaziaria os dois.

        Sem pick, o rótulo é "na fila" e o card já mostra o dia do jogo logo
        acima. Nenhum horário de publicação é prometido: não existe um fixo, e
        prometer o que não se cumpre custa mais caro que não avisar.
      */}
      <div className="mt-2 flex items-center gap-1.5">
        {game.has_pick ? (
          <>
            <Check className="w-3 h-3 text-accent-ink shrink-0" />
            <span className="text-[10px] font-semibold text-accent-ink">
              {game.pick_type === 'free' ? 'Pick grátis publicado' : 'Pick publicado'}
            </span>
          </>
        ) : (
          <>
            <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-ink-4 shrink-0" />
            <span className="text-[10px] text-ink-4">Análise na fila</span>
          </>
        )}
      </div>
    </article>
  )
}

/** `revelar`/`onCarregou`: revelação coletiva do topo da Home · ver FreePickHero. */
export default function NextGames({ revelar = true, onCarregou }: {
  revelar?: boolean
  onCarregou?: () => void
}) {
  const [games, setGames] = useState<UpcomingFixture[] | null>(null)
  const [loading, setLoading] = useState(true)
  /* Relógio de Brasília, redesenhado de minuto em minuto. É ele que tira o
     jogo da lista no apito · ver `porVir` abaixo. */
  const [agora, setAgora] = useState(agoraBR)

  /*
   * 30 é o teto da rota, e é o que a janela dela comporta: o coletor mantém
   * hoje + 2 dias (fixture_collector_service.DIAS_BR = 3). Pedir "os
   * próximos 8" cortava jogo que ia acontecer hoje mesmo.
   */
  useEffect(() => {
    let vivo = true
    const buscar = (primeira: boolean) => {
      api.get('/public/next-fixtures', { params: { limit: 30 } })
        .then(r => { if (vivo) setGames(Array.isArray(r.data) ? r.data : []) })
        .catch(() => { if (vivo && primeira) setGames([]) })
        .finally(() => { if (vivo && primeira) { setLoading(false); onCarregou?.() } })
    }
    buscar(true)

    /* Duas cadências, com papéis diferentes.
     *
     * O relógio (1 min) só TIRA, e não custa rede nenhuma: é o que faz a lista
     * encolher no apito de cada jogo. A rebuscada (5 min) é a única que pode
     * ACRESCENTAR · jogo que entrou na janela, pick que saiu · e é rara de
     * propósito, porque a Home é a página mais visitada do site.
     *
     * Aba escondida não pesquisa: Home aberta num pano de fundo a tarde
     * inteira somaria dezenas de consultas que ninguém leu. */
    const relogio = setInterval(() => setAgora(agoraBR()), 60_000)
    const rebusca = setInterval(() => { if (!document.hidden) buscar(false) }, 300_000)
    const aoVoltar = () => { if (!document.hidden) { setAgora(agoraBR()); buscar(false) } }
    document.addEventListener('visibilitychange', aoVoltar)
    return () => {
      vivo = false
      clearInterval(relogio); clearInterval(rebusca)
      document.removeEventListener('visibilitychange', aoVoltar)
    }
  }, [])

  if (loading || !revelar) {
    return (
      <div className="-mx-4 sm:mx-0">
        <div className="flex gap-3 overflow-hidden px-4 sm:px-0">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[148px] w-[196px] sm:w-[212px] shrink-0" />
          ))}
        </div>
      </div>
    )
  }

  /*
   * Só o que ainda não começou.
   *
   * O servidor corta com 10 minutos de tolerância (ver public_next_fixtures) e
   * esse corte vale no instante da resposta. Aqui o corte é no apito e é
   * refeito a cada minuto: quem deixou a aba aberta vê a lista encolher em vez
   * de continuar lendo "análise na fila" sobre um jogo do primeiro tempo.
   *
   * `>` e não `>=`: o jogo sai no minuto em que começa. Com `>=` ele ficava
   * pendurado o minuto inteiro do apito, que é justamente quando "na fila" já
   * virou mentira.
   */
  const porVir = (games ?? []).filter(g => quando(g.match_datetime) > agora)

  // Sem jogo na janela, some inteira · a Home não ganha um painel vazio
  // avisando que não tem nada para avisar.
  if (porVir.length === 0) return null

  /*
   * "Na fila da IA" é uma promessa, e em começo de temporada ela era falsa: os
   * times ainda não têm histórico, o motor já sabe que não vai gerar pick pra
   * nenhum daqueles jogos, e a faixa seguia dizendo que estavam na fila.
   *
   * A faixa continua · ela é o presente da Home, entre a Dica do Dia e os
   * números · mas com o nome do que ela é de fato quando nada ali pode virar
   * pick. Quem quiser o motivo encontra na aba de picks, que explica.
   */
  const naFila = porVir.some(g => !g.sem_historico)

  const hoje = hojeBR()

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.45, ease: [0.16, 1, 0.3, 1] }}
      aria-labelledby="fila-ia"
    >
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 id="fila-ia" className="flex items-center gap-2 text-xs font-bold text-ink-2">
          {naFila && <LiveDot />}
          {naFila ? 'Na fila da IA' : 'Próximos jogos'}
        </h2>
        <span className="text-[10px] text-ink-4 shrink-0">
          {porVir.length === 1 ? 'próximo jogo' : `próximos ${porVir.length} jogos`}
        </span>
      </div>

      {/* Sangria até a borda da tela no celular: o esmaecido das pontas é do
          próprio Marquee, e com a fita parando 16px antes da borda ele
          deixaria um naco de card nítido do lado de fora do degradê. */}
      <div className="-mx-4 sm:mx-0">
        <Marquee
          spacing="pr-3"
          /* Um pouco abaixo da fita de ligas (50), e não os 28 de antes: o
             card tem cinco informações, mas naquele ritmo ele levava seis
             segundos pra atravessar e a fita parecia travada. */
          speed={44}
          items={porVir.map(g => (
            <GameCard key={g.fixture_id} game={g} hoje={hoje} />
          ))}
        />
      </div>
    </motion.section>
  )
}
