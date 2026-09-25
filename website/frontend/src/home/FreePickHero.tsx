import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight, Check, Gift, History, Lock } from 'lucide-react'
import api from '../services/api'
import { rotuloDoMercado } from '../utils/marketTranslate'
import { useAuth } from '../context/AuthContext'
import { Badge, Button, LiveDot, ResultBadge, Skeleton } from '../components/ui'
import { escudoDoTime } from '../lib/aoVivo'

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
 * Escudo grande do placar, com as iniciais como reserva.
 *
 * O TeamLogo compartilhado simplesmente some quando o escudo falha · numa
 * linha de texto isso passa, mas aqui o escudo É o layout: sem ele o placar
 * ficaria com um buraco de um lado só.
 */
function Escudo({ id, nome }: { id?: number | null; nome: string }) {
  const src = escudoDoTime(id ?? undefined)
  const [falhou, setFalhou] = useState(false)
  const iniciais = nome.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join('').toUpperCase()
  return (
    <span className="w-14 h-14 rounded-full bg-surface-2 border border-line flex items-center justify-center shrink-0">
      {src && !falhou ? (
        <img src={src} alt="" width={36} height={36} loading="lazy" className="w-9 h-9 object-contain" onError={() => setFalhou(true)} />
      ) : (
        <span className="font-display text-sm font-bold text-ink-2" aria-hidden="true">{iniciais}</span>
      )}
    </span>
  )
}

/** O que o visitante leva ao criar a conta · só o que é verdade hoje. */
const CONFIANCA = ['Jogo e odd reais', 'Conta grátis', 'Resultado no histórico público']

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
      <div className="panel p-5 space-y-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-14 w-full" />
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

        {/* Jogo, em formato de placar: escudo, horário, escudo. */}
        <div className="px-4 pt-4 pb-5">
          {pick.league_name && (
            <p className="text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-4 mb-4 truncate">
              {pick.league_name}
            </p>
          )}

          <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-2">
            <div className="flex flex-col items-center gap-2 min-w-0">
              <Escudo id={pick.home_team_id} nome={pick.home_team_name} />
              <span className="font-display text-sm font-semibold text-ink-1 text-center leading-tight line-clamp-2">{pick.home_team_name}</span>
            </div>

            <div className="pt-3.5 flex flex-col items-center min-w-[64px]">
              {quando
                ? <span className="font-mono text-lg font-bold text-ink-1 tabular-nums leading-none">{quando}</span>
                : <span className="font-display text-sm font-bold text-ink-4">x</span>}
              <span className="mt-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-4">
                {anterior ? 'data' : 'hoje'}
              </span>
            </div>

            <div className="flex flex-col items-center gap-2 min-w-0">
              <Escudo id={pick.away_team_id} nome={pick.away_team_name} />
              <span className="font-display text-sm font-semibold text-ink-1 text-center leading-tight line-clamp-2">{pick.away_team_name}</span>
            </div>
          </div>

          {pick.result && <div className="mt-4 flex justify-center"><ResultBadge result={pick.result} emDestaque /></div>}
        </div>

        {/* Odd e mercado, em dois blocos. */}
        <div className="grid grid-cols-[auto_1fr] gap-2 px-4">
          <div className="rounded-lg bg-surface-2/60 border border-line px-4 py-3 text-center">
            <div className="stat-label !mt-0 mb-1">Odd</div>
            <div className="font-mono text-xl font-bold text-accent-ink tabular-nums leading-none">
              {Number(pick.odd).toFixed(2)}
            </div>
          </div>

          {!revelado ? (
            /* O borrão cobre um texto de enfeite (ISCA), nunca o mercado:
               o servidor nem manda o mercado pra quem não tem conta. */
            <div className="relative rounded-lg border border-dashed border-accent/40 bg-accent/5 px-3 py-3 overflow-hidden min-w-0">
              <span className="block stat-label !mt-0 mb-1 text-center">Mercado</span>
              <span className="block text-center font-mono text-sm font-bold text-ink-2 blur-[6px] select-none" aria-hidden="true">
                {ISCA}
              </span>
              <span className="absolute inset-x-0 bottom-2.5 flex items-center justify-center gap-1.5">
                <span className="w-5 h-5 rounded-full bg-accent/20 flex items-center justify-center">
                  <Lock className="w-3 h-3 text-accent-ink" />
                </span>
                <span className="text-[11px] font-bold text-accent-ink">Libera com conta grátis</span>
              </span>
            </div>
          ) : (
            <div className="rounded-lg bg-surface-2/60 border border-line px-3 py-3 text-center min-w-0">
              <div className="stat-label !mt-0 mb-1">Mercado</div>
              <div className="font-mono text-sm font-bold text-ink-1 leading-snug break-words">
                {rotuloDoMercado(pick.market, pick.line)}
              </div>
            </div>
          )}
        </div>

        {/* Ação */}
        <div className="px-4 pt-4 pb-4">
          {!revelado ? (
            <>
              <Button to="/login?mode=register" block IconRight={ArrowRight}>
                Ver o mercado desta dica
              </Button>
              <ul className="mt-3 flex flex-wrap justify-center gap-x-3 gap-y-1">
                {CONFIANCA.map(t => (
                  <li key={t} className="flex items-center gap-1 text-[11px] text-ink-3">
                    <Check className="w-3 h-3 text-accent-ink shrink-0" aria-hidden="true" />
                    {t}
                  </li>
                ))}
              </ul>
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
