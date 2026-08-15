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
 * 2. Virou carrossel horizontal. A lista vertical de cinco linhas empurrava os
 *    indicadores para fora da primeira tela no celular, e cada linha só cabia
 *    horário e nomes espremidos. Deitada, o mesmo espaço leva escudo, os dois
 *    times em linhas próprias e a liga.
 *
 * Ela anda sozinha (components/ui/Marquee), e cada jogo entra UMA vez · quem
 * encostar o cursor ou o dedo pausa. Se os jogos couberem na largura, a fita
 * não anda: fica parada e centralizada, sem repetir card para fingir volume.
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
      className="shrink-0 w-[196px] sm:w-[212px] bg-surface-0 border border-line rounded-lg p-3
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
            <Check className="w-3 h-3 text-accent shrink-0" />
            <span className="text-[10px] font-semibold text-accent">
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

  useEffect(() => {
    api.get('/public/next-fixtures', { params: { limit: 8 } })
      .then(r => setGames(r.data ?? []))
      .catch(() => setGames([]))
      .finally(() => { setLoading(false); onCarregou?.() })
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

      {/* Sangria até a borda da tela no celular: o esmaecido das pontas é do
          próprio Marquee, e com a fita parando 16px antes da borda ele
          deixaria um naco de card nítido do lado de fora do degradê. */}
      <div className="-mx-4 sm:mx-0">
        <Marquee
          spacing="pr-3"
          /* Devagar de propósito: o card tem cinco informações e some da
             tela em ~6s neste ritmo. Na velocidade da fita de ligas · que
             são duas palavras e um escudo · não daria para ler nenhuma. */
          speed={28}
          items={games.map(g => (
            <GameCard key={g.fixture_id} game={g} hoje={hoje} />
          ))}
        />
      </div>
    </motion.section>
  )
}
