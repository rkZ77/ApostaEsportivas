import { useState, memo } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { toastUp, fadeInUp } from '../lib/motion'
import api from '../services/api'
import { pctProb } from '../utils/format'
import { calcVipStake, calcFreeStake, calcMultiplaStake, calcProfitUnits } from '../utils/stakeUtils'
import { stakeDe, contaEmUnidades } from '../utils/stakePlan'
import ApostaModal from './ApostaModal'
import { translateMarket, translateLine, translateTeamName, explainMarket, linhaDoJogador } from '../utils/marketTranslate'
import { PICK_TYPE_BORDER } from '../utils/resultStyle'
import InfoTip from './InfoTip'
import AnalysisModal from './AnalysisModal'
import { Badge, PickTypeBadge, ResultBadge } from './ui'
import {
  PickCardFooter, PickExplainButton, PickProbability, PickReasoning,
} from './PickCardParts'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { useOddAtualizada } from '../hooks/useOddAtualizada'
import { TeamLogo, LeagueLogo, PlayerPhoto } from './TeamLogo'
import { Clock } from 'lucide-react'

function wcPhase(dateStr?: string): string | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const phases: [string, string, string][] = [
    ['2026-06-11', '2026-07-02', 'Grupos'],
    ['2026-07-04', '2026-07-10', 'Oitavas'],
    ['2026-07-13', '2026-07-17', 'Quartas'],
    ['2026-07-19', '2026-07-22', 'Semi'],
    ['2026-07-25', '2026-07-26', 'Semifinal'],
    ['2026-07-29', '2026-08-01', 'Final'],
  ]
  for (const [start, end, label] of phases) {
    if (d >= new Date(start) && d <= new Date(end)) return label
  }
  return null
}

interface Suggestion {
  id: number
  fixture_id?: number
  home_team_name: string
  away_team_name: string
  home_team_id?: number
  away_team_id?: number
  league_id?: number
  league_name?: string
  market: string
  line?: string
  odd: number
  bet_house: string
  confidence: number
  probability?: number | null
  market_type?: string | null
  ev?: number
  match_date?: string
  match_datetime?: string | null
  reasoning?: string
  result?: string
  profit?: number
  rank_position?: number
  pick_type?: string
  is_followed?: boolean
  user_stake_units?: number | null
  user_actual_odd?: number | null
  user_bet_house?: string | null
  stake_pct?: number | null
  suggested_stake_units?: number | null
  /* PICK DE JOGADOR. Quando `player_name` vem, o card troca a linha única de
     mercado por três campos rotulados (jogador, mercado, linha) e a foto da
     pessoa · o pick é sobre ELA, e "Chutes no alvo, Pedro · 2 ou mais chutes
     no alvo" numa linha só dizia o mercado duas vezes e o jogador no meio. */
  player_id?: number | null
  player_name?: string | null
  player_team?: string | null
  /** `line_value` do banco · o número puro da linha, sem a frase em volta. */
  line_value?: number | null
  /** Pernas de um pick COMBINADO. Hoje só o Pick Boost usa (Over 1.5 FT +
   *  Under 2.5 HT), mas o formato é genérico de propósito: qualquer produto
   *  que junte mais de um mercado numa odd só cai aqui sem card novo. */
  legs?: Array<{
    /** Nome do mercado na linguagem do resto do site. Alimenta o InfoTip. */
    market: string
    line?: string | null
    /** O que a pessoa aposta, escrito como ela leria no bilhete da casa
     *  ("Mais de 1.5 gols"). Sem isto a perna sai como nome técnico de mercado
     *  + linha em duas colunas, e no celular as duas truncam. */
    label?: string
    /** Quando vale: "Jogo inteiro", "1º tempo". É o que diferencia as duas
     *  pernas do Boost -- as duas são de gols, o que muda é o período. */
    periodo?: string
    odd?: number | null
    probability?: number | null
    result?: string | null
  }>
}

/** Extrai só o trecho "FATO: ..." ou as primeiras ~120 chars do reasoning */
function shortReasoning(text?: string): string {
  if (!text) return ''
  const fatoMatch = text.match(/FATO:\s*(.+?)(?=\s*ANÁLISE:|$)/i)
  if (fatoMatch) return fatoMatch[1].trim()
  return text.slice(0, 120)
}

interface BancaSummary { bankroll_current: number; unit_value: number }

/*
 * Teto de unidades por tipo, espelhando STAKE_LIMITS em
 * backend/routers/banca.py. Sem isto o modal deixava escolher mais unidades
 * do que o backend aceita e a aposta so' falhava no POST /banca/follow, com
 * erro genérico depois de o usuário ter confirmado -- faltas e goleiros
 * param em 6 lá, não em 10.
 *
 * VIP fica de fora de propósito: mantém o teto dinâmico que já tinha.
 */
const MAX_UNITS_POR_TIPO: Record<string, number> = {
  free: 6, multipla: 3, faltas: 6, goleiros: 6, player_stats: 6, boost: 5,
}

/* Memoizado no fim do arquivo · este é o card mais repetido do site (lista VIP,
   aba Mercados, histórico), e a tela de Picks repinta a árvore inteira a cada
   resposta que chega. Ver o bloco de memo em pages/Picks.tsx. */
function SuggestionCard({
  s, onClick, banca, isLive = false,
}: { s: Suggestion; onClick?: () => void; banca?: BancaSummary | null; isLive?: boolean }) {
  const navigate = useNavigate()
  const pct = Math.round((s.confidence ?? 0) * 100)
  const [followed, setFollowed]   = useState(s.is_followed ?? false)
  const [following, setFollowing] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [modalOdd, setModalOdd]   = useState(Number(s.odd))
  const [apiError, setApiError]   = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)
  /*
   * O que o usuário ACABOU de registrar, antes de a lista ser recarregada.
   *
   * `handleConfirm` marcava só `followed = true`. O botão virava "Registrado"
   * e todo o resto do card continuava lendo `s.*`, que ainda vinha da resposta
   * anterior do backend, sem os campos de follow. Como o painel só mostra
   * "Apostado" quando `s.user_stake_units != null`, ele caía no ramo de
   * sugestão e seguia exibindo a stake e a odd SUGERIDAS.
   *
   * Caso real (17/08/2026, pick free Internacional x Remo): o usuário
   * registrou 6u a 1.52 e o card continuou mostrando "Apostar 2u" com a odd
   * 1.75 · os dois números que ele mais precisa conferir depois de apostar,
   * ambos errados, e sem nenhum aviso de que aquilo já não descrevia a aposta
   * dele. O banco estava certo o tempo todo (user_followed_picks id=499).
   *
   * Guardar aqui, e não recarregar a lista inteira, é o que mantém a correção
   * dentro do card: ele é usado em Home, Picks, PickPublico e Compartilhar, e
   * nem todos têm um callback de refresh para chamar.
   */
  const [registrado, setRegistrado] = useState<
    { stakeUnits: number; actualOdd: number; betHouse: string } | null
  >(null)

  /*
   * Fonte única do que o card exibe depois de registrado: o que acabou de ser
   * registrado nesta sessão vence, senão o que o backend trouxe.
   *
   * Sem isto, cada lugar do card decidia sozinho entre `s.*` e o estado local,
   * e foi assim que "Registrado" e "Apostar 2u" apareceram na mesma tela.
   */
  const seguido      = registrado != null || (s.is_followed ?? false)
  const stakeSeguida = registrado?.stakeUnits ?? s.user_stake_units ?? null
  const oddSeguida   = registrado?.actualOdd ?? s.user_actual_odd ?? null
  const casaSeguida  = registrado?.betHouse ?? s.user_bet_house ?? null
  const { share: shareStory, sharing, shared } = useShareStoryImage()
  const { odd: buscarOdd, buscando: buscandoOdd } = useOddAtualizada()
  // Prioridade: 1) suggested_stake_units do backend (já usa banca real)
  //             2) função específica por tipo como fallback
  const stakeSuggestion = (() => {
    if (!banca) return null
    if (s.suggested_stake_units != null && s.suggested_stake_units > 0) {
      const units = s.suggested_stake_units
      return {
        units,
        amountR: units * banca.unit_value,
        kellyPct: Math.round(units * banca.unit_value / banca.bankroll_current * 1000) / 10,
      }
    }
    const prob = Number(s.probability ?? s.confidence ?? 0)
    const odd  = Number(s.odd)
    const ev   = Number(s.ev ?? 0)
    const pickType = s.pick_type ?? 'vip'
    if (pickType === 'multipla') {
      return calcMultiplaStake(prob, odd, banca.bankroll_current, banca.unit_value)
    }
    if (pickType === 'free') {
      return calcFreeStake(prob, odd, ev, banca.bankroll_current, banca.unit_value)
    }
    return calcVipStake(prob, odd, ev, banca.bankroll_current, banca.unit_value, s.stake_pct)
  })()

  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation()
    const pickTypeRoute = (s.pick_type ?? 'vip').replace('multiplas', 'multipla')
    shareStory({
      pickId: s.id,
      pickTypeRoute,
      homeTeamName: translateTeamName(s.home_team_name),
      awayTeamName: translateTeamName(s.away_team_name),
      homeTeamId: s.home_team_id,
      awayTeamId: s.away_team_id,
      leagueName: s.league_name,
      pickType: pickTypeRoute,
      market: s.market ? translateMarket(s.market) : undefined,
      line: translateLine(s.line),
      odd: Number(s.odd),
      probabilityPct: pctProb(s.probability ?? s.confidence),
      result: s.result,
      // Mesma regra do card: sem aposta seguida, a imagem mostra o resultado
      // DO PICK na stake do plano publico (stakePlan.ts) · nao o ganho que o
      // usuario teria tido se tivesse entrado. Alavancagem nao entra no plano
      // (peso 0), entao a imagem dela sai sem numero de unidade.
      profit: s.result && (stakeSeguida != null || contaEmUnidades(pickTypeRoute))
        ? calcProfitUnits(s.result, Number(s.odd),
                          stakeSeguida ?? stakeDe(pickTypeRoute),
                          stakeSeguida != null ? oddSeguida : null)
        : null,
    })
  }

  const handleFollow = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (followed) return
    // Múltipla não passa por aqui: bilhete se atualiza perna a perna, no card
    // dele, via /live/ticket-odd.
    const { odd } = s.pick_type === 'multipla'
      ? { odd: Number(s.odd) }
      : await buscarOdd(Number(s.odd), {
          fixture_id: s.fixture_id,
          market_type: s.market_type,
          line: s.line,
        })
    setModalOdd(odd)
    setShowModal(true)
  }

  const handleConfirm = async (actualOdd: number, betHouse: string, stakeUnits: number) => {
    setFollowing(true)
    setApiError(null)
    try {
      await api.post('/banca/follow', {
        pick_id: s.id,
        pick_type: s.pick_type ?? 'vip',
        stake_units: stakeUnits,
        actual_odd: actualOdd,
        bet_house: betHouse,
      })
      setFollowed(true)
      // O card passa a descrever a aposta DELE na mesma hora, sem esperar
      // recarregar a lista -- ver o comentário em `registrado`.
      setRegistrado({ stakeUnits, actualOdd, betHouse })
      setShowModal(false)
      setShowSuccess(true)
      setTimeout(() => setShowSuccess(false), 3000)
    } catch (err: any) {
      setApiError(err?.response?.data?.detail ?? 'Erro ao registrar aposta. Tente novamente.')
    } finally {
      setFollowing(false)
    }
  }

  const fato   = shortReasoning(s.reasoning)
  const isCopa = s.league_id === 1
  const pickType = s.pick_type ?? 'vip'

  /*
   * Horário do jogo. O card mostrava só a data em outro lugar, e "hoje 16:00"
   * é justamente o que decide se ainda dá tempo de entrar na aposta.
   *
   * Sai de `match_datetime` por fatia de string, nunca de `match_date`. Duas
   * armadilhas, as duas já vividas aqui:
   *
   * 1. `match_date` é coluna DATE -- "2026-08-09", sem hora nenhuma.
   *    `new Date("2026-08-09")` é meia-noite UTC, e imprimir isso em
   *    America/Sao_Paulo dava 21:00 do dia ANTERIOR. Não era um horário
   *    errado por pouco: era 21:00 em TODO pick, sempre, fosse o jogo
   *    11:00 ou 18:30.
   * 2. `match_datetime` já chega em horário de Brasília sem fuso, então
   *    deixar o navegador interpretar joga o horário pro fuso de quem lê.
   *    Mesma regra de home/FreePickHero.tsx e home/NextGames.tsx.
   */
  const kickoff = s.match_datetime ? String(s.match_datetime).slice(11, 16) : null

  const probPct = s.probability != null ? Number(s.probability) * 100 : null

  // Sugestão nunca pode nascer acima do teto: em mercado com teto baixo
  // (faltas/goleiros) o Kelly do calcVipStake chegava a pedir mais unidades
  // do que o backend aceita.
  const maxUnits = MAX_UNITS_POR_TIPO[pickType] ?? Math.max(10, stakeSuggestion?.units ?? 10)

  return (
  <>
    <motion.div
      variants={fadeInUp}
      whileHover={onClick ? { y: -3 } : undefined}
      /* A sombra da levantada saiu daqui e virou `.hover-elev` (index.css):
         era um preto fixo em 50%, que no tema claro pesava como borrao. O
         framer nao consegue interpolar `var()`, entao quem anima a sombra
         agora e' o CSS · o `y` continua com a mola daqui. */
      whileTap={onClick ? { scale: 0.985 } : undefined}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      /* Casca comum dos 6 tipos de card (ver .pick-card em index.css). A cor da
         borda vem de PICK_TYPE_BORDER, que é a mesma convenção do badge.

         Cursor e levantada só existem quando há clique de verdade. O card
         inteiro era um botão gigante que abria o detalhe, e isso disparava sem
         querer o tempo todo: dentro dele já moram "Apostar", "Compartilhar",
         "Entenda esta análise", o coração de favorito e o ícone de informação.
         Errar o alvo entre eles abria uma tela cheia por engano. */
      className={`pick-card hover-elev group ${onClick ? 'cursor-pointer' : ''} ${isCopa ? 'border-yellow-500/20' + (onClick ? ' hover:border-yellow-500/40' : '') : PICK_TYPE_BORDER[pickType] ?? PICK_TYPE_BORDER.vip}`}
      onClick={onClick}
      /* Âncora do tour: o passo "Encontre seus picks" destaca o PRIMEIRO card
         que existir na tela, e não um desenho de card. Ver
         components/onboarding/steps.tsx. */
      data-tour="pick-card"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <PickTypeBadge type={pickType} />
          {(s.league_id || s.league_name) && (
            <div className="flex items-center gap-1 min-w-0">
              <LeagueLogo id={s.league_id} name={s.league_name} />
              {s.league_name && <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{s.league_name}</span>}
            </div>
          )}
          {kickoff && (
            <span className="flex items-center gap-1 text-[10px] text-ink-4 shrink-0">
              <Clock className="w-3 h-3" />
              {kickoff}
            </span>
          )}
        </div>
        {s.result ? (
          <ResultBadge result={s.result} />
        ) : isLive ? (
          <Badge tone="red" className="animate-pulse">Ao vivo</Badge>
        ) : (
          <Badge tone="neutral">Pendente</Badge>
        )}
      </div>

      {/* Hero: Odd | Stake | EV */}
      <div className="font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          {/* "Odd combinada" quando o pick tem pernas · e' o vocabulario da
              multipla, e no Boost o numero e' exatamente isso: o produto das
              duas odds, nao a odd de um mercado. Ver as pernas logo abaixo,
              cada uma com a sua. */}
          <div className="text-[10px] text-ink-3 mb-0.5">
            {s.legs && s.legs.length > 0 ? 'Odd combinada' : 'Odd'}
          </div>
          <div className="text-3xl font-black text-green-400">
            {seguido && oddSeguida != null
              ? Number(oddSeguida).toFixed(2)
              : Number(s.odd).toFixed(2)}
          </div>
          {seguido && oddSeguida != null && Math.abs(oddSeguida - Number(s.odd)) > 0.001 && (
            <div className="text-[9px] text-ink-4 mt-0.5">pick: {Number(s.odd).toFixed(2)}</div>
          )}
          <div className="text-[10px] text-ink-4 mt-0.5">
            {seguido && casaSeguida ? casaSeguida : s.bet_house}
          </div>
        </div>
        {!s.result && seguido && stakeSeguida != null ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostado</div>
              <div className="text-xl font-black text-green-400">{stakeSeguida}u</div>
              {banca && <div className="text-[11px] text-ink-4">R${(stakeSeguida * banca.unit_value).toFixed(0)}</div>}
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              {(() => {
                const effOdd = oddSeguida ?? Number(s.odd)
                const profitU = (effOdd - 1) * stakeSeguida
                return (
                  <>
                    <div className="text-xl font-black text-ink-1">+{profitU.toFixed(2)}u</div>
                    {banca && <div className="text-[11px] text-green-600 font-semibold">+R${(profitU * banca.unit_value).toFixed(0)}</div>}
                  </>
                )
              })()}
            </div>
          </>
        ) : stakeSuggestion && !s.result ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Apostar</div>
              <div className="text-xl font-black text-green-400">{stakeSuggestion.units}u</div>
              <div className="text-[11px] text-ink-4">R${stakeSuggestion.amountR.toFixed(0)}</div>
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-ink-1">+{((Number(s.odd) - 1) * stakeSuggestion.units).toFixed(2)}u</div>
              <div className="text-[11px] text-green-600 font-semibold">+R${((Number(s.odd) - 1) * stakeSuggestion.amountR).toFixed(0)}</div>
            </div>
          </>
        ) : s.result ? (
          (() => {
            /*
             * DINHEIRO SÓ PRA QUEM APOSTOU DE VERDADE.
             *
             * A stake caía pra `stakeSuggestion?.units ?? 1` quando o usuário
             * NÃO tinha seguido o pick, e o card estampava "Lucro +3,75u · Em
             * reais +R$38" com o valor da banca dele. Ele não entrou nessa
             * aposta: o card anunciava um ganho que nunca existiu, na conta de
             * quem só estava olhando o histórico.
             *
             * Seguiu (`user_stake_units`) -> a conta é a dele: stake que ele
             * declarou, odd que ele pegou, e o valor em reais pela unidade da
             * banca dele.
             *
             * Não seguiu -> mostra o resultado DO PICK na stake do PLANO
             * PÚBLICO (stakePlan.ts), com o rótulo dizendo em quantas unidades.
             * Era 1u fixo, e isso fazia o card discordar do placar da mesma
             * semana: /public/results já pesava o mesmo pick por 4u (VIP) ou 3u
             * (free e mercados). Dois números do mesmo pick, na mesma tela.
             * Sem reais: real depende de stake, e stake que não houve não vira
             * dinheiro.
             *
             * Alavancagem não tem stake de plano (peso 0): ela é um caminho e
             * só vira unidade na banca de quem apostou. Pra quem não seguiu, o
             * card mostra o resultado e diz que não conta em unidades, em vez
             * de estampar um "+0,00u" que parece defeito.
             */
            const seguiu = stakeSeguida != null
            const contaU = seguiu || contaEmUnidades(pickType)
            const u = seguiu ? stakeSeguida! : stakeDe(pickType)
            const p = calcProfitUnits(s.result, Number(s.odd), u, seguiu ? oddSeguida : null)
            const color = p >= 0 ? 'text-green-400' : 'text-red-400'
            const profitR = seguiu && banca ? Math.abs(p) * banca.unit_value : null
            return (
              <>
                <div className="flex-1 px-4 py-3 text-center">
                  <div className="text-[10px] text-ink-3 mb-0.5">
                    {seguiu ? 'Seu lucro' : 'Lucro do pick'}
                  </div>
                  {contaU ? (
                    <>
                      <div className={`text-xl font-black ${color}`}>
                        {p >= 0 ? '+' : ''}{p.toFixed(2)}u
                      </div>
                      <div className="text-[10px] text-ink-4">
                        {seguiu ? `(${u}u)` : `por ${u}u`}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="text-xl font-black text-ink-3">-</div>
                      <div className="text-[10px] text-ink-4">só conta apostado</div>
                    </>
                  )}
                </div>
                <div className="flex-1 px-4 py-3 text-center">
                  {seguiu ? (
                    <>
                      <div className="text-[10px] text-ink-3 mb-0.5">Em reais</div>
                      {profitR != null ? (
                        <div className={`text-xl font-black ${color}`}>
                          {p >= 0 ? '+' : '-'}R${profitR.toFixed(0)}
                        </div>
                      ) : (
                        <div className="text-xl font-black text-ink-4">-</div>
                      )}
                    </>
                  ) : (
                    <>
                      {/* Vocabulário do próprio card: o botão vira "Registrado"
                          quando a aposta é seguida, então o oposto é este. */}
                      <div className="text-[10px] text-ink-3 mb-0.5">Sua aposta</div>
                      <div className="text-sm font-semibold text-ink-4 pt-1.5">Não registrada</div>
                    </>
                  )}
                </div>
              </>
            )
          })()
        ) : (
          <div className="flex-1 px-4 py-3 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">EV</div>
            <div className={`text-xl font-black ${s.ev != null && s.ev > 0 ? 'text-green-400' : 'text-ink-3'}`}>
              {/* ev vem como fração do endpoint de lista · ver AnalysisModal */}
              {s.ev != null ? `${(Number(s.ev) * 100).toFixed(1)}%` : 's/d'}
            </div>
          </div>
        )}
      </div>

      {/* Times + mercado */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={s.home_team_id} name={s.home_team_name} />
          <span className="text-sm font-bold text-ink-1 truncate">{s.home_team_name}</span>
          <span className="text-ink-4 text-xs shrink-0">vs</span>
          <span className="text-sm font-bold text-ink-1 truncate">{s.away_team_name}</span>
          <TeamLogo id={s.away_team_id} name={s.away_team_name} />
        </div>
        {/* PICK COMBINADO MOSTRA AS PERNAS, uma por linha.
          *
          * O Pick Boost é "Over 1.5 no jogo todo" E "Under 2.5 no primeiro
          * tempo" -- duas apostas diferentes, em tempos diferentes da partida,
          * que só compartilham o bilhete. Escrever isso numa linha só
          * ("Over 1.5 FT + Under 2.5 HT") economizava espaço e cobrava o preço
          * errado: o card parecia um mercado único de nome esquisito, e quem
          * ia apostar não sabia que precisava marcar DUAS seleções na casa.
          *
          * Cada perna leva a odd dela. A odd do topo continua sendo a
          * combinada, que é o que se aposta -- as de baixo explicam de onde
          * ela veio, e é a mesma leitura que o bilhete da casa mostra. */}
        {s.legs && s.legs.length > 0 ? (
          /* PERNA DESENHADA COMO A DA MÚLTIPLA (02/09).
           *
           * Os dois produtos são a mesma coisa para quem aposta: um bilhete de
           * várias seleções por uma odd só. Mas cada um tinha o próprio desenho
           * de perna: a múltipla numa caixa com borda, círculo numerado e a odd
           * na direita; o Boost numa linha solta com um quadradinho cinza. Duas
           * gramáticas para a mesma ideia, e a do Boost era a mais fraca: sem
           * caixa, as duas pernas encostavam uma na outra e liam como uma frase
           * só.
           *
           * Fica a da múltipla, que é a que já estava resolvida, e com o estado
           * por perna junto. Num Boost só a perna do 1º tempo pode cair, e o
           * card não tinha como mostrar isso. */
          <div className="space-y-2">
            {s.legs.map((leg, i) => {
              /* Mesma regra da múltipla: a perna mostra o resultado DELA.
                 Bilhete GREEN implica todas GREEN (dedução, não palpite);
                 bilhete RED sem o dado da perna fica neutro, porque não se sabe
                 qual caiu e pintar as duas de vermelho inventa metade. */
              const lr = (leg.result ?? (s.result === 'GREEN' ? 'GREEN' : undefined)) as
                'GREEN' | 'RED' | undefined
              const boxClass = lr === 'GREEN' ? 'border-green-500/20 bg-green-500/5'
                : lr === 'RED' ? 'border-red-500/20 bg-red-500/5'
                : 'border-line bg-surface-1/60'
              const circleClass = lr === 'GREEN' ? 'bg-green-500/20 text-green-400'
                : lr === 'RED' ? 'bg-red-500/20 text-red-400'
                : 'bg-amber-500/10 text-amber-400'
              return (
                <div key={i} className={`rounded-md border px-3 py-2 ${boxClass}`}>
                  <div className="flex items-center gap-2">
                    <span className={`w-5 h-5 flex items-center justify-center rounded-full
                                      ${circleClass} text-[10px] font-black shrink-0`}>
                      {lr === 'GREEN' ? '✓' : lr === 'RED' ? '✗' : i + 1}
                    </span>
                    {/* A APOSTA, e não o nome do mercado. "Mais de 1.5 gols"
                        cabe e se entende; o técnico fica no InfoTip. */}
                    <span className="text-xs text-ink-2 font-semibold truncate">
                      {leg.label ?? translateMarket(leg.market)}
                    </span>
                    {leg.periodo && (
                      <span className="shrink-0 px-1.5 py-px rounded bg-surface-3 border border-line
                                       text-[10px] text-ink-4 whitespace-nowrap">
                        {leg.periodo}
                      </span>
                    )}
                    <InfoTip text={explainMarket(leg.market, leg.line ?? undefined)} />
                    {leg.odd != null && (
                      <span className={`ml-auto font-mono font-black text-sm shrink-0 ${
                        lr === 'GREEN' ? 'text-green-400'
                        : lr === 'RED' ? 'text-red-400' : 'text-amber-300'}`}>
                        {Number(leg.odd).toFixed(2)}
                      </span>
                    )}
                  </div>
                  {leg.probability != null && (
                    <div className="ml-7 mt-1 text-[10px] text-ink-4">
                      {Math.round(Number(leg.probability) * 100)}% de chance nesta perna
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : s.player_name ? (
          /* PICK DE JOGADOR EM CAMPOS ROTULADOS.
           *
           * Numa linha só o card dizia "Chutes no alvo, Pedro · 2 ou mais
           * chutes no alvo": o mercado aparecia duas vezes, o nome da pessoa
           * ficava espremido dentro dele, e o separador era um ponto do meio,
           * pontuação que o site não usa em lugar nenhum.
           *
           * Quebrado em jogador, mercado e linha, cada pergunta tem um lugar:
           * QUEM, O QUÊ e QUANTO precisa sair. A foto entra porque esta é a
           * única família de pick que é sobre uma pessoa, e escudo de time não
           * identifica o Pedro. */
          <div className="flex items-start gap-2.5">
            <PlayerPhoto id={s.player_id} name={s.player_name} size={38} />
            <dl className="flex-1 min-w-0 space-y-0.5">
              <div className="flex items-baseline gap-2">
                <dt className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">Jogador</dt>
                <dd className="text-xs font-bold text-ink-1 truncate">{s.player_name}</dd>
                {s.player_team && (
                  <span className="text-[10px] text-ink-4 truncate shrink">{s.player_team}</span>
                )}
              </div>
              <div className="flex items-baseline gap-2">
                <dt className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">Mercado</dt>
                <dd className="text-xs font-semibold text-ink-2 truncate">
                  {translateMarket(s.market)}
                </dd>
                <InfoTip text={explainMarket(s.market, s.line)} />
              </div>
              <div className="flex items-baseline gap-2">
                <dt className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">Linha</dt>
                <dd className="text-xs text-ink-2 truncate">
                  {linhaDoJogador(s.line, s.line_value, s.player_name)}
                </dd>
              </div>
            </dl>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-ink-3">
            <span className="font-semibold text-ink-2">{translateMarket(s.market)}</span>
            {s.line && <><span>,</span><span>{translateLine(s.line)}</span></>}
            <InfoTip text={explainMarket(s.market, s.line)} />
          </div>
        )}
      </div>

      <PickProbability confidence={s.confidence} probability={s.probability} />

      {/* O "Fato" NÃO aparece no pick de jogador (02/09).
        *
        * Ele repetia, em texto corrido, exatamente o que os três campos acima
        * já dizem em duas linhas: quem, qual mercado, qual média, em quantas
        * atuações. Quatro linhas de parágrafo por card, num produto que sai em
        * lista e é lido no celular.
        *
        * O texto não se perde: continua inteiro em "Entenda esta análise", que
        * é onde ele responde a pergunta que o card não responde ("por que ela
        * acha que sai"). Nos outros produtos ele fica, porque lá é a única
        * frase que descreve a partida. */}
      {!s.player_name && <PickReasoning text={fato} />}


      {/* Footer */}
      {(s.reasoning || s.ev != null || probPct != null) && (
        <PickExplainButton onClick={() => setShowAnalysis(true)} />
      )}

      <PickCardFooter
        onBet={!s.result ? (banca ? handleFollow : () => navigate('/banca')) : undefined}
        betState={following || buscandoOdd ? 'loading' : followed ? 'done' : 'idle'}
        hasBanca={!!banca}
        onShare={handleShare}
        shareState={sharing ? 'loading' : shared ? 'done' : 'idle'}
      />
    </motion.div>

    <AnimatePresence>
    {showAnalysis && (
      <AnalysisModal
        onClose={() => setShowAnalysis(false)}
        data={{
          market: translateMarket(s.market),
          line: translateLine(s.line),
          /* O jogador vai separado pelo mesmo motivo do card: no pick de
             jogador, "quem" é metade da aposta, e ele estava dentro da string
             da linha. Com os campos separados o modal escreve a regra de
             verdade ("dá GREEN se Pedro fizer 2 ou mais chutes no alvo") em
             vez do texto genérico de mercado desconhecido. */
          playerId: s.player_id ?? undefined,
          playerName: s.player_name ?? undefined,
          playerTeam: s.player_team ?? undefined,
          lineValue: s.line_value ?? undefined,
          // Crus, pra regra do mercado: explainMarket casa por chave em inglês.
          marketRaw: s.market,
          lineRaw: s.line,
          pickId: s.id,
          pickType,
          odd: Number(s.odd),
          confidence: s.confidence,
          probability: s.probability,
          ev: s.ev,
          reasoning: s.reasoning,
          homeTeam: s.home_team_name,
          awayTeam: s.away_team_name,
          /* Pick combinado explica PERNA A PERNA. O modal já sabia fazer isso
             (a múltipla usa desde sempre) -- o card é que não passava, então o
             Boost abria a análise mostrando "Over 1.5 FT + Under 2.5 HT" como
             se fosse um mercado só, o mesmo defeito que o card tinha. */
          legs: s.legs,
          /* As duas pernas do Boost são do MESMO jogo, ao contrário da
             múltipla. Muda o texto, não o desenho. */
          legsMesmoJogo: (s.legs?.length ?? 0) > 0 && s.pick_type === 'boost',
        }}
      />
    )}
    </AnimatePresence>

    <AnimatePresence>
    {showModal && (
      <ApostaModal
        pickOdd={modalOdd}
        originalOdd={Number(s.odd)}
        suggestedUnits={Math.min(stakeSuggestion?.units ?? 1, maxUnits)}
        suggestedHouse={s.bet_house}
        maxUnits={maxUnits}
        onConfirm={handleConfirm}
        onCancel={() => setShowModal(false)}
        loading={following}
        error={apiError}
      />
    )}
    </AnimatePresence>
    <AnimatePresence>
    {showSuccess && (
      <motion.div
        variants={toastUp} initial="hidden" animate="visible" exit="exit"
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-white text-sm font-semibold px-5 py-3 rounded-lg shadow-lg whitespace-nowrap"
      >
        Pick registrado com sucesso!
      </motion.div>
    )}
    </AnimatePresence>
  </>
  )
}


export default memo(SuggestionCard)
