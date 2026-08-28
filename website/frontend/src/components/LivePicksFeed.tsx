/*
 * Aba "Picks Ao Vivo" · as oportunidades que o Motor Live encontrou.
 *
 * NÃO CONFUNDIR COM LivePicks.tsx
 * -------------------------------
 * `LivePicks.tsx` é "Minhas Apostas": o que o usuário decidiu seguir, sendo
 * acompanhado em tempo real. Este arquivo é o produto novo: o que o motor
 * está sugerindo agora. São telas diferentes com dados diferentes, e a
 * colisão de nome que existia na chave da aba (`aovivo` significando Minhas
 * Apostas) foi desfeita junto com este componente.
 *
 * O QUE O CARD MOSTRA, E POR QUÊ
 * ------------------------------
 * Um pick Live carrega duas leituras do mesmo jogo, e as duas importam:
 *   - o SNAPSHOT da criação, que é o que o motor viu quando decidiu;
 *   - o ESTADO ATUAL, que é onde o jogo está agora.
 * Mostrar só o segundo esconde a análise; mostrar só o primeiro mente sobre o
 * jogo. O card mostra os dois, e é essa distância que diz se a aposta ainda
 * faz sentido.
 *
 * DUAS COISAS QUE ESTA TELA APRENDEU RODANDO COM JOGO DE VERDADE (11/08)
 * ---------------------------------------------------------------------
 * 1. ODD VENCIDA NÃO É PICK ENCERRADO. A odd ao vivo vale 3 minutos, então
 *    três minutos depois de nascer todo card caía na seção "Encerrados" com
 *    um "Expirado antes de ser seguido" e o tratamento visual de coisa morta ·
 *    enquanto a partida seguia no 38'. O que venceu foi o PREÇO. O pick
 *    continua de pé, continua sendo acompanhado e continua entrando na
 *    assertividade do motor (routers/live_picks.py: EXPIRED também é
 *    liquidado). Encerrado é só o que tem `result`.
 * 2. O CARD NÃO REPETE A PROSA. O `reasoning` do motor descreve exatamente os
 *    mesmos números que os ladrilhos e as barras já mostram. Aberto por
 *    padrão, ele dobrava a altura do card e virava parede de texto no celular.
 *    Fica atrás de um "Por que este pick", que é onde quem quer conferir vai
 *    procurar.
 *
 * A validade da odd fica visível o tempo todo, em contagem regressiva. Odd ao
 * vivo evapora, e um pick sem prazo à vista convida o usuário a registrar uma
 * aposta que já não existe.
 */
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Radio, Timer, CheckCircle2, ChevronDown, PowerOff, Eye } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import ApostaModal from './ApostaModal'
import { Badge, Button, EmptyState, ErrorState, LiveDot, ResultBadge, Skeleton,
         SkeletonPickGrid, StatTile } from './ui'
import { PickProbability } from './PickCardParts'
import { calcVipStake } from '../utils/stakeUtils'

/* Teto de unidades do Live · espelha STAKE_LIMITS["live"] em
 * backend/routers/banca.py. É o mais baixo de qualquer produto, e a razão está
 * escrita lá: o motor ainda não tem histórico próprio e a odd pode mudar entre
 * a publicação e a aposta.
 *
 * Sem o teto AQUI, o Kelly pediria 7u num pick de 82% e o modal deixaria
 * escolher · o erro só apareceria no POST, depois de o usuário confirmar. É o
 * mesmo defeito que MAX_UNITS_POR_TIPO já corrigiu nos cards pré-jogo. */
const MAX_UNIDADES_LIVE = 4

/** "2026-08-28T21:04:12-03:00" -> "21:04". Fatiado e nunca por `new Date`:
 *  o backend grava o relógio do motor já em Brasília (ver `_relogio_do_watch`
 *  em routers/live_picks.py), e qualquer parse reintroduziria a conversão de
 *  fuso que essa escolha existe pra evitar. */
const horaCurta = (iso?: string | null) => (iso ? iso.slice(11, 16) : '')

/** Uma linha de `live_match_observations` · o que o motor leu daquele jogo. */
interface EmLeitura {
  fixture_id: number
  minuto: number | null
  status: string | null
  goals_observado: number | null
  corners_observado: number | null
  shots_observado: number | null
  shots_on_target_observado: number | null
  red_cards_observado: number | null
  lido_em: string | null
  home_team: string | null
  away_team: string | null
  liga: string | null
  tem_pick: boolean
}

/* O PLACAR DO LIVE, dentro do "O que é" da aba · o mesmo bloco que os outros
 * produtos ganharam em 28/08, só que desta fonte.
 *
 * Ele NÃO pode sair de /suggestions/stats/quick: aquele endpoint soma os oito
 * pipelines de pré-jogo, e o Live é medido à parte de propósito (ver a
 * docstring de live_picks.estatisticas · "juntar os dois é decisão de produto
 * que ainda não foi tomada"). Puxar o número de lá rotularia de "Ao Vivo" um
 * desempenho que não é dele.
 */
function PlacarDoLive() {
  const [d, setD] = useState<any>(null)
  const [pronto, setPronto] = useState(false)

  useEffect(() => {
    let vivo = true
    api.get('/live-picks/stats')
      .then(r => { if (vivo) setD(r.data) })
      .catch(() => { /* placar é contexto, não conteúdo · falha em silêncio */ })
      .finally(() => { if (vivo) setPronto(true) })
    return () => { vivo = false }
  }, [])

  if (!pronto) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-3" aria-busy="true">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-[4.5rem] rounded-md" />
        ))}
      </div>
    )
  }

  const resolvidos = Number(d?.resolvidos ?? 0)
  if (!d?.disponivel || resolvidos === 0) {
    return (
      <p className="text-[11px] text-ink-4 mt-3 leading-relaxed">
        Nenhum pick ao vivo foi liquidado ainda · o placar aparece aqui assim que o
        primeiro fechar.
      </p>
    )
  }

  const win = Number(d.win_rate ?? 0)
  const lucro = Number(d.profit ?? 0)
  const tiles = [
    { label: 'Picks', value: String(resolvidos),          cor: 'text-ink-1' },
    { label: 'Green', value: String(d.greens ?? 0),       cor: 'text-accent-ink' },
    { label: 'Red',   value: String(d.reds ?? 0),         cor: 'text-red-400' },
    { label: 'Win %', value: `${win}%`,                   cor: win >= 55 ? 'text-accent-ink' : 'text-ink-2' },
    { label: 'Lucro', value: `${lucro >= 0 ? '+' : ''}${lucro.toFixed(1).replace('.', ',')}u`,
      cor: lucro >= 0 ? 'text-accent-ink' : 'text-red-400' },
  ]

  return (
    <div className="mt-3">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {tiles.map(({ label, value, cor }) => (
          <div key={label} className="bg-surface-1 border border-line rounded-md p-3 text-center">
            <div className={`font-mono text-xl font-black tabular-nums ${cor}`}>{value}</div>
            <div className="text-[10px] text-ink-3 mt-1">{label}</div>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-red-400/70 mt-1.5 leading-relaxed">
        Só do Ao Vivo · o placar do pré-jogo é medido à parte. Entra todo pick que o motor
        gerou, seguido ou não: a taxa descreve o motor, não o que deu tempo de pegar.
        {typeof d.minuto_medio === 'number' && ` Minuto médio de entrada: ${d.minuto_medio}'.`}
      </p>
    </div>
  )
}

/* AS PARTIDAS QUE O MOTOR ESTÁ LENDO AGORA (28/08, pedido do usuário).
 *
 * A aba passa a maior parte do tempo dizendo "nenhuma oportunidade ao vivo
 * agora", e essa frase é verdadeira e vazia ao mesmo tempo · ela não separa
 * "varreu doze jogos e nenhum pagava" de "não tem jogo nenhum rolando". O
 * aviso de motor ligado resolveu metade; isto resolve a outra, mostrando O QUE
 * ele está olhando, com o placar de cada jogo.
 *
 * O número não custa requisição de API: sai de `live_match_observations`, que
 * o próprio motor grava a cada partida processada. É literalmente o que ele
 * leu · não uma segunda consulta que poderia divergir dele.
 */
function EmLeituraAgora({ isActive }: { isActive: boolean }) {
  const [dados, setDados] = useState<{ partidas: EmLeitura[]; disponivel: boolean } | null>(null)
  const timer = useRef<number | null>(null)

  const carregar = useCallback(() => {
    api.get('/live-picks/em-leitura')
      .then(r => setDados(r.data))
      .catch(() => setDados({ partidas: [], disponivel: false }))
  }, [])

  useEffect(() => {
    if (!isActive) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    carregar()
    timer.current = window.setInterval(carregar, POLL_MS)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [isActive, carregar])

  const partidas = dados?.partidas ?? []
  if (!dados?.disponivel || partidas.length === 0) return null

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-1 h-4 rounded-full bg-red-400" />
        <h3 className="text-sm font-bold text-ink-1 flex items-center gap-1.5">
          <Eye className="w-3.5 h-3.5 text-red-400" />
          Em leitura agora · {partidas.length}
        </h3>
      </div>
      <p className="text-[11px] text-ink-4 mb-3 leading-relaxed">
        Os jogos que o motor está acompanhando nesta varredura, com o que ele leu de cada
        um · os números são o total da partida, os dois times somados. Ele só publica
        quando ela se afasta do esperado e a odd paga por isso.
      </p>

      <div className="grid gap-2 sm:grid-cols-2">
        {partidas.map(p => (
          <div
            key={p.fixture_id}
            className={`rounded-lg border p-3 ${
              p.tem_pick ? 'border-red-400/40 bg-red-500/5' : 'border-line bg-surface-1'}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] text-ink-4 truncate">{p.liga ?? 'liga ?'}</span>
              <span className="flex items-center gap-1.5 shrink-0">
                {/* O minuto é o que faz a linha parecer viva · sem ele o
                  * cartão descreve um jogo sem dizer em que ponto ele está. */}
                <LiveDot tone="red" />
                <span className="font-mono text-[11px] font-bold text-red-300 tabular-nums">
                  {p.minuto != null ? `${p.minuto}'` : (p.status ?? '·')}
                </span>
              </span>
            </div>

            {/* Nomes sem número no meio: `live_match_observations` guarda o
              * TOTAL da partida, e não o placar por lado · um número único
              * entre os dois times seria lido como placar e mentiria em todo
              * jogo que não está 0 a 0. O gol entra na fila de contadores
              * abaixo, onde "total" é a leitura certa. */}
            <p className="text-sm text-ink-2 mt-1 truncate">
              {p.home_team ?? 'Time ?'}
              <span className="text-ink-4 mx-1.5">x</span>
              {p.away_team ?? 'Time ?'}
            </p>

            {/* Os contadores que o motor de fato usa pra decidir, todos como
              * TOTAL da partida. Escanteio e chute no alvo primeiro porque são
              * os dois mercados que ele publica. */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[10px] text-ink-4">
              <span>gols <span className="font-mono text-ink-1 tabular-nums">{p.goals_observado ?? '·'}</span></span>
              <span>escanteios <span className="font-mono text-ink-2 tabular-nums">{p.corners_observado ?? '·'}</span></span>
              <span>no alvo <span className="font-mono text-ink-2 tabular-nums">{p.shots_on_target_observado ?? '·'}</span></span>
              <span>chutes <span className="font-mono text-ink-2 tabular-nums">{p.shots_observado ?? '·'}</span></span>
              {!!p.red_cards_observado && (
                <span className="text-red-400 font-semibold">{p.red_cards_observado} vermelho(s)</span>
              )}
              {p.tem_pick && (
                <span className="text-red-300 font-semibold ml-auto">já virou pick</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Unidades sugeridas pra ESTE pick e ESTA banca · a mesma conta do card VIP.
 *
 * Fica fora do card porque o MODAL precisa abrir com o mesmo número que o card
 * mostrou. Enquanto ele calculava por conta própria (`stake_units ?? 1`), o
 * card dizia "3u" e o modal abria em "1u" · duas respostas pra mesma pergunta,
 * na mesma batida de dedo. */
function unidadesSugeridas(
  pick: Pick<LivePick, 'probability' | 'odd' | 'ev' | 'stake_units'>,
  banca?: { bankroll_current: number; unit_value: number } | null,
): number {
  if (banca?.bankroll_current && banca.unit_value > 0) {
    const kelly = calcVipStake(
      Number(pick.probability), Number(pick.odd), Number(pick.ev),
      banca.bankroll_current, banca.unit_value,
    )
    if (kelly) return Math.min(kelly.units, MAX_UNIDADES_LIVE)
  }
  // Sem banca configurada, a sugestão do motor · é melhor que nada, e é o
  // mesmo número que o pick carrega no /admin.
  return Math.min(pick.stake_units ?? 1, MAX_UNIDADES_LIVE)
}
import { PICK_TYPE_BORDER } from '../utils/resultStyle'

const TEAM_LOGO = (id?: number) => (id ? `/api/proxy/team/${id}.png` : null)

/* Mesmo intervalo do polling de Minhas Apostas (15s): o dado que alimenta os
   dois vem do mesmo cache de 20s no backend, então poll mais rápido só
   gastaria requisição sem trazer número novo. */
const POLL_MS = 15000

const STATUS_LABEL: Record<string, string> = {
  '1H': '1º Tempo', HT: 'Intervalo', '2H': '2º Tempo', ET: 'Prorrogação',
  FT: 'Encerrado', AET: 'Encerrado', PEN: 'Encerrado', NS: 'Não iniciado',
}

interface LivePick {
  id: number
  fixture_id: number
  league_name?: string
  home_team_name: string
  away_team_name: string
  home_team_id?: number
  away_team_id?: number
  market: string
  market_type: string
  line: string
  odd: number
  probability: number
  ev: number
  edge: number
  confidence: number
  stake_units?: number
  reasoning?: string
  minute_at_creation: number
  home_goals_at_creation: number
  away_goals_at_creation: number
  corners_at_creation?: number | null
  shots_at_creation?: number | null
  shots_on_target_at_creation?: number | null
  possession_home_at_creation?: number | null
  observed_at_creation: number
  remaining_minutes: number
  /* leituras do motor no instante da criação */
  pressure_home?: number | null
  pressure_away?: number | null
  pressure_total?: number | null
  rhythm_score?: number | null
  rhythm_level?: string | null
  rhythm_trend?: string | null
  live_signal_score?: number | null
  data_freshness?: string | null
  projected_total?: number | null
  odd_valid_until?: string
  segundos_de_validade: number | null
  status: string
  expiration_reason?: string
  result?: string | null
  profit?: number | null
  /* estado atual, vindo do enriquecimento no backend */
  live_status: string
  elapsed?: number | null
  home_goals?: number | null
  away_goals?: number | null
  current_val?: number | null
  stat_label?: string
  is_live: boolean
  is_ft: boolean
  pick_status?: string
  is_followed: boolean
  user_stake_units?: number | null
  /* O backend manda os três desde sempre (ver routers/live_picks.py::feed) e a
     interface não os declarava · o card não tinha como mostrar onde apostar
     nem a odd que o usuário de fato registrou. */
  bet_house?: string | null
  user_actual_odd?: number | null
  user_bet_house?: string | null
}

/* Cabeçalho de seção na mesma marcação de Picks.tsx (barra colorida + título).
   Duplicado aqui, e não importado, porque lá ele é interno da página · são dez
   linhas de marcação, e transformar em primitivo compartilhado mexeria nas 14
   chamadas daquele arquivo por um ganho que não é deste trabalho. */
function TituloDeSecao({ cor, texto }: { cor: string; texto: string }) {
  return (
    <div className="flex items-center gap-3 mb-4 mt-6 first:mt-0">
      <span className={`w-0.5 h-5 ${cor} rounded-full block`} />
      <h2 className="text-sm font-bold text-ink-2">{texto}</h2>
    </div>
  )
}

function TeamLogo({ id, name }: { id?: number; name: string }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={18} height={18}
      className="object-contain shrink-0" style={{ width: 18, height: 18 }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

/* Barra do progresso da linha: onde a linha está, onde o jogo está e de que
   lado o pick precisa ficar.

   Os dois rótulos ficam ACIMA da barra, um em cada ponta, em vez de flutuarem
   colados nas posições exatas: com linha 10 e valor 5 eles se sobrepunham, e
   um número em cima do outro não informa nada. A posição continua sendo dada
   pelo desenho · o texto só nomeia. */
function BarraDaLinha({ atual, linha, direcao, rotulo }: {
  atual: number; linha: number; direcao: 'over' | 'under'; rotulo?: string
}) {
  const maximo = Math.max(linha * 1.6, atual * 1.15 + 1)
  const posLinha = Math.min((linha / maximo) * 100, 97)
  const posAtual = Math.min((atual / maximo) * 100, 100)
  const favoravel = direcao === 'over' ? atual > linha : atual < linha
  const cor = favoravel ? 'bg-green-500' : 'bg-red-400'

  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-[10px] text-ink-4 mb-1.5">
        <span>
          {rotulo ?? 'agora'}{' '}
          <span className={`font-bold tabular-nums ${favoravel ? 'text-green-400' : 'text-red-400'}`}>
            {atual}
          </span>
        </span>
        <span>linha <span className="font-bold text-ink-2 tabular-nums">{linha}</span></span>
      </div>
      <div className="relative h-1.5 bg-surface-3/60 rounded-full">
        <div className={`absolute left-0 top-0 h-full rounded-full transition-all duration-700 ${cor}`}
          style={{ width: `${posAtual}%` }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-ink-2/70 rounded"
          style={{ left: `${posLinha}%` }} />
      </div>
    </div>
  )
}

const RITMO_LABEL: Record<string, string> = {
  BAIXO: 'baixo', MEDIO: 'médio', ALTO: 'alto', MUITO_ALTO: 'muito alto',
}
const TENDENCIA_LABEL: Record<string, string> = {
  ACELERANDO: 'acelerando', DESACELERANDO: 'desacelerando',
  ESTAVEL: 'estável', INDEFINIDA: 'sem leitura',
}
const PRESSAO_LABEL: Record<string, string> = {
  BAIXA: 'baixa', MEDIA: 'média', ALTA: 'alta', MUITO_ALTA: 'muito alta',
}

/* Nível da pressão a partir do score. Os cortes são os mesmos de
   pressure_model.py (escala centrada em 0.5 = time médio) · duplicar o número
   aqui é aceitável porque é só rótulo de exibição, mas se o corte mudar lá,
   muda aqui. */
function nivelPressao(score?: number | null): string | null {
  if (score == null) return null
  if (score < 0.35) return 'BAIXA'
  if (score < 0.50) return 'MEDIA'
  if (score < 0.68) return 'ALTA'
  return 'MUITO_ALTA'
}

/* Barra de pressão dos dois lados. Mostra domínio, que é a pergunta que o
   número responde: quem está empurrando o jogo. */
function BarraPressao({ casa, fora, nomeCasa, nomeFora }: {
  casa: number; fora: number; nomeCasa: string; nomeFora: string
}) {
  const soma = casa + fora
  const fatiaCasa = soma > 0 ? (casa / soma) * 100 : 50
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-[10px] text-ink-4 mb-1.5">
        <span>Pressão ofensiva</span>
        <span className="tabular-nums">
          {casa.toFixed(2)} {PRESSAO_LABEL[nivelPressao(casa) ?? ''] ?? ''}
          {' · '}
          {fora.toFixed(2)} {PRESSAO_LABEL[nivelPressao(fora) ?? ''] ?? ''}
        </span>
      </div>
      <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-3/60">
        <div className="bg-accent/70 transition-all duration-700" style={{ width: `${fatiaCasa}%` }} />
        <div className="bg-ink-4/40 transition-all duration-700" style={{ width: `${100 - fatiaCasa}%` }} />
      </div>
      <div className="flex items-center justify-between text-[10px] text-ink-4 mt-1">
        <span className="truncate max-w-[45%]">{nomeCasa}</span>
        <span className="truncate max-w-[45%] text-right">{nomeFora}</span>
      </div>
    </div>
  )
}

function Contagem({ segundos }: { segundos: number | null }) {
  const [restante, setRestante] = useState(segundos ?? 0)
  useEffect(() => { setRestante(segundos ?? 0) }, [segundos])
  useEffect(() => {
    if (restante <= 0) return
    const t = setInterval(() => setRestante(s => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [restante > 0])

  if (segundos === null) return null
  const expirou = restante <= 0
  const apertado = restante > 0 && restante <= 30
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-bold tabular-nums ${
      expirou ? 'text-ink-4' : apertado ? 'text-amber-400' : 'text-ink-3'}`}>
      <Timer size={11} />
      {expirou
        ? 'preço da criação · confira na casa'
        : `odd válida por ${Math.floor(restante / 60)}:${String(restante % 60).padStart(2, '0')}`}
    </span>
  )
}

const CardLive = forwardRef<HTMLDivElement, {
  pick: LivePick
  onSeguir: (p: LivePick) => void
  /** Banca do usuário · sem ela o card mostra unidades e não reais. */
  banca?: { bankroll_current: number; unit_value: number } | null
}>(function CardLive({ pick, onSeguir, banca }, ref) {
  /* Encerrado é só o que tem resultado. `EXPIRED` sem resultado quer dizer que
     a JANELA DA ODD fechou sem ninguém seguir · o jogo continua e o pick
     continua sendo acompanhado (ver o cabeçalho deste arquivo). */
  const encerrado = !!pick.result
  const oddVencida = pick.status === 'EXPIRED' && !pick.result

  /* A odd que vale pra CONTA é a que o usuário registrou, quando registrou.
     Ao vivo a linha se move mais que em pré-jogo, então usar a do pick pra
     calcular o lucro de quem já apostou daria um número que ele não vai ver. */
  const oddEfetiva = pick.user_actual_odd ?? pick.odd

  /* Quanto apostar · CONFORME A BANCA, igual VIP, múltipla e free.
   *
   * `picks_live.stake_units` é a sugestão do motor, e ela não conhece a banca
   * de ninguém: é a mesma para quem tem R$ 200 e para quem tem R$ 20.000. Os
   * cards pré-jogo resolvem isso há tempo, com o Kelly em cima do bankroll
   * real do usuário, e não havia razão pro Live ser o único produto a mostrar
   * uma unidade que não fala da banca de quem está lendo.
   *
   * `calcVipStake` é a MESMA função do card VIP · o que muda é só o teto, que
   * aqui é 4u (ver MAX_UNIDADES_LIVE).
   *
   * Sem banca configurada, cai na sugestão do motor: é melhor que nada, e é o
   * mesmo número que o pick carrega no /admin.
   *
   * Quem já apostou vê o que APOSTOU, não o que era sugerido. */
  const aposta = useMemo(
    () => ({ unidades: pick.user_stake_units ?? unidadesSugeridas(pick, banca) }),
    [pick, banca])
  const direcao: 'over' | 'under' = pick.line.toLowerCase().startsWith('under') ? 'under' : 'over'
  const linhaNum = parseFloat(pick.line.replace(/[^\d.]/g, ''))
  const temBarra = pick.current_val != null && !isNaN(linhaNum)
  const podeSeguir = !pick.is_followed && !encerrado && !oddVencida

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`pick-card p-3.5 ${PICK_TYPE_BORDER.live} ${encerrado ? 'opacity-75' : ''}`}
    >
      {/* cabeçalho: liga, jogo e minuto */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {pick.league_name && (
            <p className="text-[11px] text-ink-4 truncate mb-1">{pick.league_name}</p>
          )}
          <div className="flex items-center gap-2 text-sm font-bold text-ink-1">
            <TeamLogo id={pick.home_team_id} name={pick.home_team_name} />
            <span className="truncate">{pick.home_team_name}</span>
            <span className="text-ink-3 font-black tabular-nums px-0.5">
              {pick.home_goals ?? '-'}<span className="text-ink-4">x</span>{pick.away_goals ?? '-'}
            </span>
            <span className="truncate">{pick.away_team_name}</span>
            <TeamLogo id={pick.away_team_id} name={pick.away_team_name} />
          </div>
        </div>
        <div className="shrink-0">
          {pick.is_live ? (
            <Badge tone="red" className="gap-1.5">
              <LiveDot tone="red" className="w-1.5 h-1.5" />
              {pick.elapsed != null ? `${pick.elapsed}'` : STATUS_LABEL[pick.live_status] ?? pick.live_status}
            </Badge>
          ) : (
            <Badge tone="neutral">{STATUS_LABEL[pick.live_status] ?? pick.live_status}</Badge>
          )}
        </div>
      </div>

      {/* a aposta */}
      <div className="flex items-end justify-between gap-3 mt-3 pt-3 border-t border-line">
        <div className="min-w-0">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide font-bold">{pick.market}</p>
          <p className="text-base font-black text-ink-1 truncate leading-tight">{pick.line}</p>
          {(pick.user_bet_house || pick.bet_house) && (
            <p className="text-[10px] text-ink-4 mt-0.5 truncate">
              {pick.user_bet_house || pick.bet_house}
            </p>
          )}
        </div>
        <div className="text-right shrink-0">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide font-bold">Odd</p>
          <p className="text-xl font-black text-accent-ink tabular-nums leading-tight">
            {Number(oddEfetiva).toFixed(2)}
          </p>
          {/* A odd que o usuário registrou pode divergir da do pick: ele segue
              depois, e a linha se move ao vivo mais que em pré-jogo. Mostrar as
              duas é o mesmo que o card VIP faz · e aqui importa mais. */}
          {pick.is_followed && Math.abs(Number(oddEfetiva) - Number(pick.odd)) > 0.001 && (
            <p className="text-[9px] text-ink-4">pick: {Number(pick.odd).toFixed(2)}</p>
          )}
        </div>
      </div>

      {/* Quanto apostar e quanto isso paga · faltava no card ao vivo e existia
          em todos os outros. Sem os dois números o assinante tinha o pick e não
          tinha a aposta: a unidade sugerida é o que traduz "78% e EV +9%" em
          uma decisão. Ver PickCardParts, mesma anatomia dos cards pré-jogo. */}
      {!encerrado && (aposta.unidades > 0) && (
        <div className="flex divide-x divide-line/60 border-t border-line mt-3 pt-3">
          <div className="flex-1 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">{pick.is_followed ? 'Apostado' : 'Apostar'}</div>
            <div className="text-lg font-black text-green-400 tabular-nums">{aposta.unidades}u</div>
            {banca && (
              <div className="text-[11px] text-ink-4 tabular-nums">
                R${(aposta.unidades * banca.unit_value).toFixed(0)}
              </div>
            )}
          </div>
          <div className="flex-1 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
            <div className="text-lg font-black text-ink-1 tabular-nums">
              +{((Number(oddEfetiva) - 1) * aposta.unidades).toFixed(2)}u
            </div>
            {banca && (
              <div className="text-[11px] text-green-600 font-semibold tabular-nums">
                +R${((Number(oddEfetiva) - 1) * aposta.unidades * banca.unit_value).toFixed(0)}
              </div>
            )}
          </div>
        </div>
      )}

      {temBarra && (
        <BarraDaLinha atual={Number(pick.current_val)} linha={linhaNum} direcao={direcao}
          rotulo={pick.stat_label?.toLowerCase()} />
      )}

      {/* Probabilidade pela MESMA peça dos cards pré-jogo · era um ladrilho
          próprio aqui, com outra cor e outro corte, e a mesma porcentagem
          aparecia diferente dependendo da aba. Ver PickCardParts. */}
      <PickProbability
        confidence={pick.confidence}
        probability={pick.probability}
        className="mt-3"
      />

      <div className="grid grid-cols-2 gap-2 mt-2">
        <StatTile className="p-2" label="EV" tone={pick.ev >= 0 ? 'green' : 'red'}
          value={<span className="text-lg">{pick.ev >= 0 ? '+' : ''}{(pick.ev * 100).toFixed(1)}%</span>} />
        <StatTile className="p-2" label="Confiança"
          value={<span className="text-lg">{(pick.confidence * 100).toFixed(0)}%</span>} />
      </div>

      {/* Pressão e ritmo · é o que separa este card de um card pré-jogo.
          Fica no corpo, não escondido no detalhe: é a leitura que justifica
          o pick ter nascido neste minuto e não em outro. */}
      {pick.pressure_home != null && pick.pressure_away != null && (
        <BarraPressao
          casa={Number(pick.pressure_home)} fora={Number(pick.pressure_away)}
          nomeCasa={pick.home_team_name} nomeFora={pick.away_team_name}
        />
      )}

      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-3 text-[11px] text-ink-4">
        <span>
          Criado aos <span className="font-bold text-ink-2 tabular-nums">{pick.minute_at_creation}&#39;</span>
          {' · '}{pick.home_goals_at_creation}x{pick.away_goals_at_creation}
          {' · '}<span className="tabular-nums">{pick.observed_at_creation}</span>{' '}
          {pick.stat_label?.toLowerCase() ?? 'no mercado'}
        </span>
        {pick.rhythm_level && (
          <span>
            Ritmo <span className="font-bold text-ink-2">
              {RITMO_LABEL[pick.rhythm_level] ?? pick.rhythm_level.toLowerCase()}
            </span>
            {pick.rhythm_trend && pick.rhythm_trend !== 'INDEFINIDA' && (
              <span className={
                pick.rhythm_trend === 'ACELERANDO' ? ' text-green-400'
                  : pick.rhythm_trend === 'DESACELERANDO' ? ' text-amber-400' : ''}>
                {' '}{TENDENCIA_LABEL[pick.rhythm_trend] ?? pick.rhythm_trend.toLowerCase()}
              </span>
            )}
          </span>
        )}
        {pick.live_signal_score != null && (
          <span>
            Sinais <span className="font-bold text-ink-2 tabular-nums">
              {(Number(pick.live_signal_score) * 100).toFixed(0)}%
            </span>
          </span>
        )}
        {pick.projected_total != null && (
          <span>
            Projeção <span className="font-bold text-ink-2 tabular-nums">
              {Number(pick.projected_total).toFixed(1)}
            </span>
          </span>
        )}
        {pick.data_freshness && pick.data_freshness !== 'FRESH' && (
          <span className="text-amber-400">dado {pick.data_freshness.toLowerCase()}</span>
        )}
      </div>

      {/* A prosa do motor repete os números acima · fica atrás de um toque, em
          vez de dobrar a altura do card com o que já está na tela. */}
      {pick.reasoning && (
        <details className="group mt-3">
          <summary className="flex items-center gap-1 text-[11px] font-bold text-ink-3 cursor-pointer
                              list-none hover:text-ink-2 transition-colors">
            <ChevronDown size={12} className="transition-transform group-open:rotate-180" />
            Por que este pick
          </summary>
          <p className="mt-2 text-[11px] text-ink-3 leading-relaxed">{pick.reasoning}</p>
        </details>
      )}

      {/* rodapé: validade e ação */}
      <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-line">
        {encerrado ? (
          <span className="inline-flex items-center gap-2">
            <ResultBadge result={pick.result} />
            {pick.profit != null && (
              <span className={`text-[11px] font-bold tabular-nums ${
                Number(pick.profit) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {Number(pick.profit) >= 0 ? '+' : ''}{Number(pick.profit).toFixed(2)}u
              </span>
            )}
          </span>
        ) : (
          <Contagem segundos={pick.segundos_de_validade} />
        )}

        {pick.is_followed ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-green-400">
            <CheckCircle2 size={12} />
            Em Minhas Apostas
            {pick.user_stake_units ? ` · ${pick.user_stake_units}u` : ''}
          </span>
        ) : podeSeguir ? (
          <Button size="sm" onClick={() => onSeguir(pick)}>Apostar</Button>
        ) : null}
      </div>
    </motion.div>
  )
})

export default function LivePicksFeed({ isActive, banca }: {
  isActive: boolean
  /* Vem da página, que já a carregou pro resto dos cards · buscar de novo aqui
     seria uma segunda fonte pro mesmo número. */
  banca?: { bankroll_current: number; unit_value: number } | null
}) {
  const [picks, setPicks] = useState<LivePick[] | null>(null)
  const [disponivel, setDisponivel] = useState(true)
  const [motivo, setMotivo] = useState<string | null>(null)
  /* Estado do motor · só o que o assinante precisa (ligado e última varredura).
     O diagnóstico completo continua sendo de admin, em /watch-status. */
  const [motor, setMotor] = useState<{ ligado: boolean; ultima_rodada: string | null } | null>(null)
  const [erro, setErro] = useState(false)
  const [alvo, setAlvo] = useState<LivePick | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [erroModal, setErroModal] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const navigate = useNavigate()

  const carregar = useCallback(async () => {
    try {
      const r = await api.get('/live-picks/feed')
      setDisponivel(r.data.disponivel !== false)
      setMotivo(r.data.motivo ?? null)
      setMotor(r.data.motor ?? null)
      setPicks(r.data.picks ?? [])
      setErro(false)
    } catch {
      setErro(true)
      setPicks([])
    }
  }, [])

  /* Poll só enquanto a aba está visível. Fora dela não há motivo pra manter
     a chamada de pé: o backend consulta a API-Football nesse caminho. */
  useEffect(() => {
    if (!isActive) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    carregar()
    timer.current = window.setInterval(carregar, POLL_MS)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [isActive, carregar])

  const confirmar = async (oddReal: number, casa: string, unidades: number) => {
    if (!alvo) return
    setSalvando(true)
    setErroModal(null)
    try {
      await api.post('/banca/follow', {
        pick_id: alvo.id, pick_type: 'live',
        stake_units: unidades, actual_odd: oddReal, bet_house: casa,
      })
      setAlvo(null)
      carregar()
    } catch (e: any) {
      setErroModal(e?.response?.data?.detail ?? 'Não foi possível registrar agora.')
    } finally {
      setSalvando(false)
    }
  }

  /* A ABA É SÓ O QUE ESTÁ DE PÉ (2026-08-27, pedido do usuário).
   *
   * Ela tinha uma segunda seção com os encerrados do dia, e isso confundia as
   * duas perguntas que a tela responde. "Ao vivo" é uma tela de DECISÃO: o
   * usuário abre com o jogo rolando, e o que ele precisa é do que ainda dá pra
   * apostar. Pick liquidado é histórico, e histórico já tem duas casas melhores
   * (Minhas Apostas e Resultados), com filtro, paginação e P&L.
   *
   * Pior: encerrado empurrava o pick vivo pra baixo numa noite movimentada, e a
   * odd ao vivo dura minutos.
   *
   * O corte é pelo RESULTADO, não pelo status. Odd vencida não encerra pick:
   * ele segue sendo acompanhado e liquidado como qualquer outro (ver o
   * cabeçalho deste arquivo). Cortar por status mandava pra fora um pick de um
   * jogo que ainda estava no 38'. */
  const emAndamento = useMemo(() => (picks ?? []).filter(p => !p.result), [picks])

  if (!isActive) return null

  if (picks === null) return <SkeletonPickGrid />

  if (erro) return <ErrorState onRetry={carregar} />

  if (!disponivel) {
    return (
      <EmptyState
        Icon={Radio}
        title="Motor Ao Vivo não está ativo neste ambiente"
        description={motivo ?? 'Os Picks Ao Vivo ainda estão em validação e rodam apenas no ambiente de testes.'}
      />
    )
  }

  return (
    <div>
      {/* Painel de abertura na cor do produto, como o das outras abas · o Live
          é vermelho no site inteiro (PICK_TYPE_HEX.live). */}
      <div className="bg-red-500/5 border border-red-400/25 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-bold text-red-300 mb-2 flex items-center gap-2">
          <LiveDot tone="red" />
          O que são os Picks Ao Vivo?
        </h3>
        <p className="text-[13px] text-ink-3 leading-relaxed">
          O motor lê o placar, o ritmo e as estatísticas da partida{' '}
          <span className="font-bold text-ink-2">em andamento</span> e compara com a odd do momento.
          Ele só publica quando o jogo se afasta do esperado e o preço paga por isso, então
          varredura sem oportunidade não vira pick.
        </p>
        <p className="text-[13px] text-ink-3 leading-relaxed mt-2">
          A odd ao vivo muda rápido: o preço mostrado é o do instante da análise.{' '}
          <span className="font-bold text-ink-2">Confira o valor na casa antes de apostar.</span>
        </p>
        <PlacarDoLive />
      </div>

      <EmLeituraAgora isActive={isActive} />

      {/* O VAZIO PRECISA DIZER SE O MOTOR ESTÁ LIGADO.
        *
        * "Nenhuma oportunidade ao vivo agora" dizia a mesma coisa em duas
        * situações que pedem reações opostas: o motor varreu os jogos e não
        * achou nada -- que é o caso NORMAL, e uma boa notícia sobre o filtro --
        * ou o motor simplesmente não está rodando. Na primeira vale esperar; na
        * segunda, esperar é perder a noite. */}
      {emAndamento.length === 0 && (
        motor?.ligado ? (
          <EmptyState
            Icon={Radio}
            title="Nenhuma oportunidade ao vivo agora"
            description={
              'O motor está acompanhando os jogos neste momento. Ele só publica quando a partida '
              + 'se afasta do esperado e a odd paga por isso, então varredura sem oportunidade '
              + 'não vira pick.'
              + (motor.ultima_rodada ? ` Última varredura às ${horaCurta(motor.ultima_rodada)}.` : '')
            }
          />
        ) : (
          <EmptyState
            Icon={PowerOff}
            title="O motor não está rodando agora"
            description={
              'Ele varre os jogos em andamento apenas quando está ligado · nada será publicado até '
              + 'lá. Não é falta de oportunidade, é o motor parado.'
              + (motor?.ultima_rodada ? ` A última varredura foi às ${horaCurta(motor.ultima_rodada)}.` : '')
            }
          />
        )
      )}

      {emAndamento.length > 0 && (
        <>
          <TituloDeSecao
            cor={motor?.ligado ? 'bg-red-400' : 'bg-line-strong'}
            texto={`Em andamento · ${emAndamento.length}`}
          />
          {/* Motor desligado COM pick na tela é o caso que mais engana: os
              cards estão lá, parecem novos, e nenhum outro vai chegar. */}
          {motor && !motor.ligado && (
            <p className="text-[11px] text-amber-400 mb-3 flex items-center gap-1.5">
              <PowerOff className="w-3.5 h-3.5 shrink-0" />
              O motor está parado · estes são os últimos picks publicados, e não virão novos
              enquanto ele não voltar.
            </p>
          )}
          <div className="space-y-4">
            <AnimatePresence mode="popLayout">
              {emAndamento.map(p => (
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} banca={banca} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      {/* Os encerrados do dia saíram daqui · ver o comentário em `emAndamento`.
          O link existe porque tirar a seção não pode virar "sumiu": o pick
          liquidado continua em Minhas Apostas, com P&L e filtro. */}
      <button
        onClick={() => navigate('/meus-picks')}
        className="mt-6 w-full text-center text-xs text-ink-3 hover:text-ink-1 transition-colors py-3 border border-line rounded-md hover:border-line-strong"
      >
        Ver os picks já encerrados em Minhas Apostas
      </button>

      <AnimatePresence>
        {alvo && (
          <ApostaModal
            pickOdd={Number(alvo.odd)}
            suggestedUnits={unidadesSugeridas(alvo, banca)}
            maxUnits={MAX_UNIDADES_LIVE}
            loading={salvando}
            error={erroModal}
            onConfirm={confirmar}
            onCancel={() => { setAlvo(null); setErroModal(null) }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
