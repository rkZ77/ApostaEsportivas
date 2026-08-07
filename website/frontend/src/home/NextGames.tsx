import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import { LiveDot, Skeleton } from '../components/ui'
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
 * 2. Virou esteira horizontal. A lista vertical de cinco linhas empurrava os
 *    indicadores para fora da primeira tela no celular, e cada linha só cabia
 *    horário e nomes espremidos. Deitada, o mesmo espaço leva escudo, os dois
 *    times em linhas próprias e a liga · e sobra o gesto de arrastar, que já é
 *    o que o dedo faz numa fila de jogos.
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

function GameCard({ game, hoje }: { game: UpcomingFixture; hoje: string }) {
  const dia = rotuloDia(game.match_datetime, hoje)

  return (
    <article
      className="snap-start shrink-0 w-[164px] sm:w-[176px] bg-surface-0 border border-line rounded-lg p-3
                 hover:border-line-strong transition-colors duration-1 ease-smooth"
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <span
          className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
            dia.ehHoje ? 'bg-accent/15 text-accent' : 'bg-surface-2 text-ink-3'
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
            <TeamLogo id={id} name={nome} size={18} />
            <span className="text-xs text-ink-1 font-medium truncate">{nome}</span>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-1.5 mt-3 pt-2.5 border-t border-line/60 min-w-0">
        <LeagueLogo id={game.league_id} name={game.league_name} />
        <span className="text-[10px] text-ink-4 truncate">{game.league_name}</span>
      </div>
    </article>
  )
}

export default function NextGames() {
  const [games, setGames] = useState<UpcomingFixture[] | null>(null)
  const [loading, setLoading] = useState(true)
  const rolador = useRef<HTMLDivElement>(null)
  const [temMais, setTemMais] = useState(false)

  useEffect(() => {
    api.get('/public/next-fixtures', { params: { limit: 8 } })
      .then(r => setGames(r.data ?? []))
      .catch(() => setGames([]))
      .finally(() => setLoading(false))
  }, [])

  /*
   * O esmaecido da direita só existe se houver mesmo card escondido lá.
   * Fixo, ele virava uma mancha sem explicação sempre que os jogos do dia
   * coubessem na largura da tela · o degradê é uma dica de que dá para
   * arrastar, e dica que mente é pior do que dica nenhuma.
   */
  useEffect(() => {
    const el = rolador.current
    if (!el) return
    const medir = () => setTemMais(el.scrollWidth - el.clientWidth > 8)
    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(el)
    return () => ro.disconnect()
  }, [games])

  if (loading) {
    return (
      <div className="-mx-4 sm:mx-0">
        <div className="flex gap-3 overflow-hidden px-4 sm:px-0">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[148px] w-[164px] sm:w-[176px] shrink-0" />
          ))}
        </div>
      </div>
    )
  }

  // Sem jogo na janela, some inteira · a Home não ganha um painel vazio
  // avisando que não tem nada para avisar.
  if (!games || games.length === 0) return null

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
          <LiveDot />
          Na fila da IA
        </h2>
        <span className="text-[10px] text-ink-4 shrink-0">
          {games.length === 1 ? 'próximo jogo' : `próximos ${games.length} jogos`}
        </span>
      </div>

      {/* A sangria negativa fica no invólucro, não no rolador: é ela que
          alinha o esmaecido com a borda real da tela no celular. Com a
          margem no rolador, a faixa parava 16px antes e deixava um naco de
          card nítido do lado de fora do degradê. */}
      <div className="relative -mx-4 sm:mx-0">
        <div
          ref={rolador}
          className="flex gap-3 overflow-x-auto scrollbar-none snap-x snap-mandatory px-4 sm:px-0"
        >
          {games.map(g => (
            <GameCard key={g.fixture_id} game={g} hoje={hoje} />
          ))}
        </div>

        {/* pointer-events-none para não roubar o arrasto de quem começa o
            gesto justamente em cima do degradê. */}
        {temMais && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-surface-0 to-transparent"
          />
        )}
      </div>
    </motion.section>
  )
}
