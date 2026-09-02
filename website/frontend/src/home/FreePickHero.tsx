import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight, Gift, History, Lock } from 'lucide-react'
import api from '../services/api'
import { rotuloDoMercado } from '../utils/marketTranslate'
import { useAuth } from '../context/AuthContext'
import { Badge, Button, LiveDot, ResultBadge, Skeleton } from '../components/ui'
import { TeamLogo } from '../components/TeamLogo'

/*
 * Dica do Dia no hero, com o mercado atrás de cadastro.
 *
 * Substituiu um mockup de dashboard com jogo e odd inventados. Aqui é pick
 * real: jogo, horário, liga e odd de verdade, e o MERCADO só aparece pra quem
 * tem conta.
 *
 * O bloqueio é de servidor, não de CSS. O endpoint devolve `locked: true` e
 * simplesmente NÃO manda market/line pro visitante anônimo. O borrão que se vê
 * aqui cobre um texto de enfeite, não o mercado escondido: se o valor viesse
 * no JSON, bastava abrir o DevTools pra ler, e a recompensa por criar conta
 * virava teatro.
 *
 * Sem dica publicada hoje, o card não some: o endpoint devolve a última, com
 * `is_previous`, e aqui ele muda de papel · deixa de ser a oferta do dia e
 * passa a ser prova, com data e resultado à mostra. Um pick RED antigo exposto
 * na Home é menos custoso do que um buraco onde deveria haver produto, e o
 * histórico completo já é público em /resultados de qualquer forma.
 */

interface FreePick {
  id: number
  home_team_name: string
  away_team_name: string
  home_team_id?: number | null
  away_team_id?: number | null
  odd: number
  result: string | null
  league_name?: string | null
  match_date?: string | null
  match_datetime?: string | null
  /** true = não é a dica de hoje, é a última publicada antes dela. */
  is_previous?: boolean
  /** true = visitante anônimo, resposta veio sem market/line.
   *  Opcional porque resposta antiga em cache pode nao trazer o campo. */
  locked?: boolean
  market?: string
  line?: string
}

/** Texto de enfeite sob o borrão. Nunca é o mercado real. */
const ISCA = 'Mercado escondido'

/*
 * `revelar` e `onCarregou` sincronizam este bloco com os vizinhos do topo.
 *
 * Cada bloco da Home tinha o seu próprio request e o seu próprio `loading`,
 * então a tela se montava sozinha na ordem em que o servidor respondesse: a
 * dica aparecia, depois a fila de jogos empurrava tudo para baixo, depois os
 * números. Quem está no celular via a página se reorganizando embaixo do dedo.
 *
 * Agora o request continua saindo na hora (ninguém espera ninguém para pedir),
 * mas a REVELAÇÃO é coletiva: o bloco avisa a Home que terminou e só troca o
 * esqueleto pelo conteúdo quando os três vizinhos do topo terminaram.
 */
export default function FreePickHero({ revelar = true, onCarregou }: {
  revelar?: boolean
  onCarregou?: () => void
}) {
  const { user } = useAuth()
  const [pick, setPick] = useState<FreePick | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/public/free-pick-today')
      .then(r => setPick(r.data ?? null))
      .catch(() => setPick(null))
      .finally(() => { setLoading(false); onCarregou?.() })
  }, [user?.id])

  if (loading || !revelar) {
    return (
      <div className="panel p-6 space-y-4">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }

  // Sem pick do dia o hero fica só com o texto, em vez de um painel vazio.
  if (!pick) return null

  // Falha FECHADO: campo ausente conta como bloqueado.
  //
  // Se um cache antigo ou uma versao anterior da API devolver sem `locked`,
  // o ramo destravado renderizaria uma caixa de mercado vazia -- e, pior,
  // qualquer mudanca futura que passe a mandar o market sem a flag vazaria
  // o dado. Exigir `locked === false` pra revelar inverte o risco.
  const revelado = pick.locked === false && !!pick.market

  const anterior = pick.is_previous === true

  /*
   * Horário do jogo se a dica é de hoje; data se é a anterior.
   *
   * Os dois saem de fatia de string, não de `new Date`: `match_datetime` chega
   * em horário de Brasília sem fuso, então deixar o navegador interpretar
   * jogava o horário para o fuso de quem está lendo.
   */
  const quando = anterior
    ? (pick.match_date ? `${pick.match_date.slice(8, 10)}/${pick.match_date.slice(5, 7)}` : null)
    : (pick.match_datetime ? pick.match_datetime.slice(11, 16) : null)

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.25, ease: [0.16, 1, 0.3, 1] }}
      className="relative"
    >
      <div aria-hidden="true" className="absolute -inset-8 bg-accent/10 blur-3xl rounded-full pointer-events-none" />

      <div className="relative panel shadow-elev">

        <div className="panel-head">
          <span className="flex items-center gap-2">
            {anterior
              ? <History className="w-3.5 h-3.5 text-ink-4 shrink-0" />
              : <LiveDot />}
            <span className="panel-label">{anterior ? 'Última dica publicada' : 'Dica do dia'}</span>
          </span>
          <Badge tone="green" Icon={Gift}>Grátis</Badge>
        </div>

        {/* Jogo */}
        <div className="px-5 py-5 text-center">
          {(pick.league_name || quando) && (
            <p className="text-[11px] text-ink-4 mb-3">
              {pick.league_name}
              {pick.league_name && quando ? '-' : ''}
              {quando}
            </p>
          )}

          <div className="flex items-center justify-center gap-2 flex-wrap mb-1">
            <TeamLogo id={pick.home_team_id ?? undefined} name={pick.home_team_name} size={22} />
            <span className="font-display text-lg font-semibold text-ink-1">{pick.home_team_name}</span>
            <span className="text-ink-4">x</span>
            <span className="font-display text-lg font-semibold text-ink-1">{pick.away_team_name}</span>
            <TeamLogo id={pick.away_team_id ?? undefined} name={pick.away_team_name} size={22} />
          </div>

          {pick.result && <div className="mt-2"><ResultBadge result={pick.result} /></div>}
        </div>

        {/* Odd e mercado */}
        <div className="grid grid-cols-2 divide-x divide-line border-y border-line">
          <div className="px-4 py-4 text-center">
            <div className="stat-label !mt-0 mb-1">Odd</div>
            <div className="font-mono text-2xl font-bold text-accent-ink tabular-nums">
              {Number(pick.odd).toFixed(2)}
            </div>
          </div>

          <div className="px-4 py-4 text-center min-w-0">
            <div className="stat-label !mt-0 mb-1">Mercado</div>
            {!revelado ? (
              <div className="relative">
                <span className="font-mono text-base font-bold text-ink-2 blur-[6px] select-none" aria-hidden="true">
                  {ISCA}
                </span>
                <span className="absolute inset-0 flex items-center justify-center gap-1.5">
                  <Lock className="w-3.5 h-3.5 text-ink-3" />
                  <span className="text-[11px] font-semibold text-ink-3">Criar conta</span>
                </span>
              </div>
            ) : (
              <div className="font-mono text-base font-bold text-ink-1 truncate">
                {rotuloDoMercado(pick.market, pick.line)}
              </div>
            )}
          </div>
        </div>

        {/* Ação */}
        <div className="px-5 py-4">
          {!revelado ? (
            <>
              <Button to="/login?mode=register" block IconRight={ArrowRight}>
                Ver o mercado desta dica
              </Button>
              <p className="text-[11px] text-ink-4 text-center mt-2.5">
                Conta grátis. O jogo e a odd acima são reais.
              </p>
            </>
          ) : (
            <Button to={`/p/free/${pick.id}`} block variant="ghost" IconRight={ArrowRight}>
              Ver a análise completa
            </Button>
          )}

          {/* Sem hora prometida: a publicação não tem horário fixo, e escrever
              um aqui viraria promessa quebrada em todo dia que atrasasse. */}
          {anterior && (
            <p className="text-[11px] text-ink-4 text-center mt-2.5">
              A dica de hoje aparece aqui assim que a análise fechar.
            </p>
          )}
        </div>
      </div>
    </motion.div>
  )
}
