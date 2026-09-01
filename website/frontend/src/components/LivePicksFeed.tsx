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
import { Radio, RefreshCw, Timer, CheckCircle2, Clock, PowerOff, Eye,
         Goal, Flag, Target, Crosshair, Lock } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import ApostaModal from './ApostaModal'
import { Badge, Button, ComoFunciona, EmptyState, ErrorState, LiveDot, Marquee, PickTypeBadge,
         ResultBadge, Skeleton, SkeletonPickGrid } from './ui'
import { PickExplainButton, PickProbability, PickReasoning } from './PickCardParts'
import InfoTip from './InfoTip'
import LiveAnalysisModal from './LiveAnalysisModal'
import { explainMarket, translateLine, translateMarket } from '../utils/marketTranslate'
import { LeagueLogo } from './TeamLogo'
import { calcVipStake } from '../utils/stakeUtils'
import { sinalizarNavegacao } from '../services/progressBus'

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

/** Estado do motor, como as rotas do Live o devolvem.
 *
 * TRÊS ESTADOS, NÃO DOIS (30/08). `hibernando` é ligado E sem jogo em campo:
 * o laço está de pé e volta sozinho quando uma partida começa. Sem essa
 * distinção, "aguardando o primeiro jogo do dia" e "alguém desligou o motor"
 * virariam a mesma frase na tela · e são situações opostas para quem está
 * esperando pick.
 */
type EstadoDoMotor = {
  ligado: boolean
  hibernando?: boolean
  ultima_rodada: string | null
} | null

/** Uma linha de `live_match_observations` · o que o motor leu daquele jogo. */
interface EmLeitura {
  fixture_id: number
  home_team_id: number | null
  away_team_id: number | null
  league_id: number | null
  minuto: number | null
  status: string | null
  goals_observado: number | null
  corners_observado: number | null
  shots_observado: number | null
  shots_on_target_observado: number | null
  red_cards_observado: number | null
  lido_em: string | null
  /** Segundos desde a leitura do motor, calculado no banco. */
  idade_seg: number | null
  /** true = minuto, placar e contadores vieram da API agora, não da varredura. */
  fresco?: boolean
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
function PlacarDoLive({ recarregar }: {
  /* Contador vindo do botão de atualizar · ver EmLeituraAgora. O placar entra
     junto porque ele muda quando um pick liquida, e liquidação é exatamente o
     que acontece enquanto a pessoa está com a aba aberta. */
  recarregar?: number
}) {
  const [d, setD] = useState<any>(null)
  const [pronto, setPronto] = useState(false)

  useEffect(() => {
    let vivo = true
    api.get('/live-picks/stats')
      .then(r => { if (vivo) setD(r.data) })
      .catch(() => { /* placar é contexto, não conteúdo · falha em silêncio */ })
      .finally(() => { if (vivo) setPronto(true) })
    return () => { vivo = false }
  }, [recarregar])

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
        Nenhum pick ao vivo foi liquidado ainda. O placar aparece aqui assim que o
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
      <p className="text-[10px] text-accent-ink/70 mt-1.5 leading-relaxed">
        Só do Ao Vivo. O placar do pré-jogo é medido à parte. Entra todo pick que o motor
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
 *
 * TRÊS MUDANÇAS EM 29/08 (pedido do usuário)
 * ------------------------------------------
 * 1. DESCEU PRA DEPOIS DOS PICKS. O bloco abria a aba, e a aba é uma tela de
 *    DECISÃO: quem entra quer ver o que dá pra apostar, não a lista do que
 *    está sendo observado. Observação é contexto, e contexto vem depois.
 *
 * 2. O RELÓGIO ANDA SOZINHO. O minuto vinha da última varredura e ficava
 *    parado nela · num motor que varre de minutos em minutos, o cartão dizia
 *    18' durante muito tempo depois de o jogo estar no 24', e isso se lê como
 *    tela travada, não como leitura periódica. Agora o minuto avança a cada
 *    60s a partir da idade da leitura (`idade_seg`, calculada no banco), e o
 *    cartão diz de quando é o dado. O minuto derivado é marcado com til: ele é
 *    projeção do relógio, não leitura nova.
 *
 * 3. O CARTÃO VIROU PARTIDA, NÃO LINHA DE TABELA. O confronto com escudo, a
 *    barra do tempo de jogo no topo e os contadores em ladrilhos · a lista
 *    antiga era uma fileira de quatro números que só quem já sabia o que
 *    procurar conseguia ler.
 */

/** Segundos para "agora", "há 12s", "há 3min". Curto de propósito: o rótulo
 *  fica dentro do cartão e concorre com o dado. */
const idadeCurta = (seg: number): string => {
  if (seg < 5) return 'agora'
  if (seg < 60) return `há ${Math.floor(seg)}s`
  const min = Math.floor(seg / 60)
  return min < 60 ? `há ${min}min` : `há ${Math.floor(min / 60)}h`
}

/** Minuto de jogo projetado a partir da leitura mais o tempo que passou.
 *
 * Só projeta com a bola rolando: no intervalo o relógio para, e somar minuto
 * ali inventaria um jogo que não está acontecendo. Devolve também se o número
 * é projetado, porque a tela precisa dizer isso em vez de fingir leitura
 * nova. */
function minutoVivo(p: EmLeitura, segundosExtras: number): { minuto: number | null; projetado: boolean } {
  if (p.minuto == null) return { minuto: null, projetado: false }
  // Dado fresco não se projeta: o minuto JÁ é o de agora, veio da mesma fonte
  // que os cards de pick usam. Projetar em cima dele somaria duas vezes o mesmo
  // tempo e o cartão passaria o jogo na frente.
  if (p.fresco) return { minuto: p.minuto, projetado: false }
  const rolando = p.status === '1H' || p.status === '2H' || p.status === 'ET'
  const idade = (p.idade_seg ?? 0) + segundosExtras
  if (!rolando || idade < 60) return { minuto: p.minuto, projetado: false }
  // Teto no fim de cada tempo: o acréscimo existe, mas projetar além dele é
  // inventar. Sem o corte, um jogo parado num HT mal detectado subiria pra 130'.
  const teto = p.status === '1H' ? 45 : p.status === '2H' ? 90 : 120
  const projetado = Math.min(teto, p.minuto + Math.floor(idade / 60))
  return { minuto: projetado, projetado: projetado > p.minuto }
}

/* A IA PROCURANDO, EM MOVIMENTO (29/08, pedido do usuário).
 *
 * O estado "buscando" era uma pílula parada com um ponto piscando. Diz a
 * verdade e não mostra nada: quem lê não faz ideia de que há doze jogos sendo
 * varridos agora, e a aba passa a maior parte do tempo sem pick nenhum na
 * tela -- ou seja, o tempo todo parecendo que nada acontece.
 *
 * A fita põe os jogos que estão sendo lidos passando na horizontal. É o mesmo
 * dado do bloco de leitura logo abaixo, só que como sinal de atividade em vez
 * de tabela: o movimento é o que comunica "está trabalhando", e ele é honesto
 * porque cada item ali é uma partida de verdade sendo observada.
 *
 * Ela SÓ aparece com a busca ligada. Fita girando com o motor parado seria
 * animação decorativa mentindo sobre o estado do produto.
 */
/* Placeholder de escudo quando não há id de time */
function TeamLogoOrDot({ id, name }: { id?: number | null; name?: string | null }) {
  const [err, setErr] = useState(false)
  const src = id ? `/api/proxy/team/${id}.png` : null
  if (!src || err) {
    return (
      <span className="w-[18px] h-[18px] rounded-full bg-surface-3 border border-line shrink-0
                       flex items-center justify-center text-[8px] font-bold text-ink-4 uppercase">
        {(name ?? '?').slice(0, 1)}
      </span>
    )
  }
  return (
    <img src={src} alt={name ?? ''} width={18} height={18}
      className="object-contain shrink-0"
      style={{ width: 18, height: 18 }}
      onError={() => setErr(true)} />
  )
}

function FitaDeBusca({ partidas }: { partidas: EmLeitura[] }) {
  if (partidas.length === 0) return null
  const itens = partidas.map(p => (
    <span key={p.fixture_id}
          className="inline-flex items-center gap-1.5 text-[11px] whitespace-nowrap
                     bg-surface-1 border border-line rounded-md px-2.5 py-1">
      <LeagueLogo id={p.league_id ?? undefined} name={p.liga ?? ''} />
      <TeamLogoOrDot id={p.home_team_id} name={p.home_team} />
      <span className="text-ink-2 font-medium">{p.home_team ?? 'Time'}</span>
      <span className="text-ink-4 text-[10px]">x</span>
      <TeamLogoOrDot id={p.away_team_id} name={p.away_team} />
      <span className="text-ink-2 font-medium">{p.away_team ?? 'Time'}</span>
      {p.minuto != null && (
        <span className="font-mono text-accent-ink font-bold text-[10px]
                         bg-accent/10 border border-accent/20 rounded px-1">
          {p.minuto}&apos;
        </span>
      )}
    </span>
  ))
  return (
    <div className="relative overflow-hidden rounded-lg border border-accent/20 bg-accent/[0.04] py-2.5 mb-6">
      <div className="flex items-center gap-2 px-3 mb-2">
        <LiveDot />
        <span className="text-[10px] font-bold text-accent-ink uppercase tracking-wide">
          a IA está lendo estes jogos agora
        </span>
        <span className="ml-auto font-mono text-[10px] text-ink-4 tabular-nums">
          {partidas.length} {partidas.length === 1 ? 'jogo' : 'jogos'}
        </span>
      </div>
      {/* gap-2 entre os cards: cada item já tem borda e fundo próprios */}
      <Marquee items={itens} spacing="pr-2" speed={28} />
    </div>
  )
}

/* A busca de "o que a IA está lendo", em um lugar só.
 *
 * DOIS COMPONENTES LEEM ISTO: a fita de busca no topo da aba e o bloco de
 * cartões no rodapé. Cada um pedindo por conta própria seria a mesma chamada
 * duas vezes de 15 em 15 segundos, e duas cópias da mesma lista podendo
 * divergir na tela por alguns segundos -- a fita mostrando um jogo que o bloco
 * ainda não tem, ou o contrário.
 *
 * `tick` mora aqui pelo mesmo motivo que a busca: ele é o relógio que faz o
 * minuto e o "lido há" andarem entre duas varreduras, sem pedir nada ao
 * servidor.
 */
function useEmLeitura(isActive: boolean, recarregar?: number) {
  const [dados, setDados] = useState<{ partidas: EmLeitura[]; disponivel: boolean } | null>(null)
  const [tick, setTick] = useState(0)
  const timer = useRef<number | null>(null)

  const carregar = useCallback(() => {
    api.get('/live-picks/em-leitura')
      .then(r => { setDados(r.data); setTick(0) })
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

  useEffect(() => {
    if (!isActive) return
    const t = window.setInterval(() => setTick(v => v + 1), 1000)
    return () => clearInterval(t)
  }, [isActive])

  /* O botão de atualizar da aba puxa esta busca junto. Sem isto ele
     atualizaria os picks e deixaria a leitura para trás -- e é justamente na
     leitura que o minuto e os contadores da partida aparecem, ou seja: a
     metade da tela em que "está desatualizado" é visível a olho nu. */
  const primeiroPedido = useRef(true)
  useEffect(() => {
    if (primeiroPedido.current) { primeiroPedido.current = false; return }
    if (isActive) carregar()
  }, [recarregar, isActive, carregar])

  return {
    partidas: dados?.partidas ?? [],
    disponivel: dados?.disponivel ?? false,
    tick,
  }
}


function EmLeituraAgora({ partidas, tick, disponivel, motor }: {
  partidas: EmLeitura[]
  tick: number
  disponivel: boolean
  motor?: EstadoDoMotor
}) {
  if (!disponivel || partidas.length === 0) return null
  /* BUSCA PAUSADA NÃO MOSTRA PARTIDA (29/08, pedido do usuário).
   *
   * A janela de `live_match_observations` é de 60 minutos, então logo depois
   * de o motor parar a lista continua cheia -- com os jogos da última
   * varredura, congelados. Na tela isso vira o pior dos dois mundos: a página
   * diz "busca pausada" no topo e mostra "a IA está lendo" logo abaixo.
   *
   * Quem manda é o estado do motor, não o que sobrou na tabela. */
  if (!motor?.ligado || motor.hibernando) return null

  const comPick = partidas.filter(p => p.tem_pick).length

  return (
    <div className="mt-8">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="w-1 h-4 rounded-full bg-accent" />
          <h3 className="text-sm font-bold text-ink-1 flex items-center gap-1.5">
            <Eye className="w-3.5 h-3.5 text-accent-ink" />
            A IA está lendo
            <span className="font-mono text-[11px] font-bold tabular-nums text-ink-3
                             bg-surface-2 border border-line rounded-full px-2 py-0.5 ml-0.5">
              {partidas.length}
            </span>
          </h3>
        </div>
        {/* O SINAL DE VIDA. Antes o estado do motor só aparecia no vazio da
          * aba, ou seja: exatamente quando NÃO havia o que olhar. Aqui ele
          * fica ao lado do que está sendo lido, que é onde a pergunta nasce. */}
        <span className={`flex items-center gap-1.5 text-[10px] font-semibold px-2 py-1 rounded-full border ${
          motor?.ligado
            ? 'border-accent/40 bg-accent/10 text-accent-ink'
            : 'border-line-strong bg-surface-2 text-ink-3'}`}>
          {motor?.ligado
            ? <><LiveDot /> buscando</>
            : <><PowerOff className="w-3 h-3" /> pausada</>}
          {motor?.ultima_rodada && (
            <span className="font-mono text-ink-4">{horaCurta(motor.ultima_rodada)}</span>
          )}
        </span>
      </div>
      <p className="text-[11px] text-ink-4 mb-3 leading-relaxed">
        Os jogos que a IA acompanha agora, com o total da partida somando os dois times.
        {comPick === 0 && ' Nenhum virou pick ainda, e isso é o normal.'}
      </p>

      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {partidas.map(p => {
          const { minuto, projetado } = minutoVivo(p, tick)
          const idade = (p.idade_seg ?? 0) + tick
          // A barra é o tempo de jogo, não uma métrica · é o que dá noção de
          // "ainda dá tempo de sair pick aqui" sem precisar de número nenhum.
          const andamento = minuto != null ? Math.min(100, (minuto / 90) * 100) : 0
          return (
            <div
              key={p.fixture_id}
              className={`relative overflow-hidden rounded-xl border transition-colors duration-1 ${
                p.tem_pick
                  ? 'border-accent/50 bg-accent/[0.07]'
                  : 'border-line bg-surface-1 hover:border-line-strong'}`}
            >
              {/* Faixa do tempo de jogo, colada no topo do cartão. */}
              <div className="absolute inset-x-0 top-0 h-[3px] bg-surface-3/60">
                <div
                  className={`h-full transition-all duration-1000 ease-linear ${
                    p.tem_pick ? 'bg-accent' : 'bg-ink-4/60'}`}
                  style={{ width: `${andamento}%` }}
                />
              </div>

              <div className="p-3 pt-3.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <LeagueLogo id={p.league_id ?? undefined} name={p.liga ?? ''} />
                    <span className="text-[10px] text-ink-4 truncate">{p.liga ?? 'liga ?'}</span>
                  </span>
                  <span className="flex items-center gap-1.5 shrink-0">
                    <LiveDot />
                    <span className="font-mono text-[11px] font-bold text-accent-ink tabular-nums"
                          title={projetado ? 'Minuto projetado desde a última leitura' : undefined}>
                      {minuto != null
                        ? `${projetado ? '~' : ''}${minuto}'`
                        : (STATUS_LABEL[p.status ?? ''] ?? p.status ?? '-')}
                    </span>
                  </span>
                </div>

                {/* O CONFRONTO EM DUAS LINHAS.
                  *
                  * `live_match_observations` guarda o TOTAL da partida, não o
                  * placar por lado · por isso o gol aparece como UM número no
                  * ladrilho abaixo, e não entre os nomes: um número entre os
                  * dois times é lido como placar e mentiria em todo jogo que
                  * não está empatado. */}
                <div className="mt-2 space-y-1">
                  {([[p.home_team_id, p.home_team], [p.away_team_id, p.away_team]] as const).map(
                    ([id, nome], i) => (
                      <div key={i} className="flex items-center gap-1.5 min-w-0">
                        <TeamLogoOrDot id={id} name={nome} />
                        <span className="text-sm text-ink-1 truncate">{nome ?? 'Time ?'}</span>
                      </div>
                    ))}
                </div>

                <div className="grid grid-cols-4 gap-1 mt-2.5">
                  {([
                    [Goal,      'Gols',           p.goals_observado],
                    [Flag,      'Escanteios',     p.corners_observado],
                    [Target,    'Chutes no alvo', p.shots_on_target_observado],
                    [Crosshair, 'Chutes',         p.shots_observado],
                  ] as const).map(([Icone, rotulo, valor]) => (
                    <div key={rotulo}
                         className="rounded-md bg-surface-2/70 border border-line/60 py-1.5 text-center"
                         title={rotulo}>
                      <Icone className="w-3 h-3 text-ink-4 mx-auto" aria-hidden="true" />
                      <div className="font-mono text-sm font-bold tabular-nums text-ink-1 leading-tight mt-0.5"
                           aria-label={rotulo}>
                        {valor ?? '-'}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between gap-2 mt-2 text-[10px]">
                  <span className="flex items-center gap-2 text-ink-4">
                    {/* COM DADO FRESCO A FRASE MUDA DE ASSUNTO.
                      * "lido há 46min" descrevia a última varredura do motor, e
                      * enquanto os números eram dele isso era a informação
                      * certa. Agora que minuto, placar e contadores vêm da API,
                      * dizer "lido há 46min" ao lado de um número atual seria
                      * desmentir a própria tela. O relógio do motor só aparece
                      * quando é ele que está mandando no cartão. */}
                    <span className="font-mono tabular-nums">
                      {p.fresco ? 'ao vivo' : `lido ${idadeCurta(idade)}`}
                    </span>
                    {!!p.red_cards_observado && (
                      <span className="flex items-center gap-1" title="Cartões vermelhos">
                        <span className="w-2 h-3 rounded-[1px] bg-red-500 shrink-0" aria-hidden="true" />
                        <span className="font-mono tabular-nums text-red-400">
                          {p.red_cards_observado}
                        </span>
                      </span>
                    )}
                  </span>
                  {p.tem_pick
                    ? <span className="text-accent-ink font-bold">já virou pick</span>
                    : <span className="text-ink-4">sem oportunidade ainda</span>}
                </div>
              </div>
            </div>
          )
        })}
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
  pick: Pick<LivePick, 'probability' | 'odd' | 'ev' | 'stake_units' | 'suggested_stake_units'>,
  banca?: { bankroll_current: number; unit_value: number } | null,
): number {
  // O backend calcula a mesma coisa desde 29/08 (live_picks.py), e ele é a
  // resposta preferida pelo mesmo motivo que vale no SuggestionCard: é o
  // número que o APP recebe, e duas implementações do mesmo Kelly divergem no
  // dia em que uma das duas mudar.
  if (pick.suggested_stake_units != null && pick.suggested_stake_units > 0) {
    return Math.min(pick.suggested_stake_units, MAX_UNIDADES_LIVE)
  }
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

/* Poll de 30s: o backend separou o TTL de fixture (30s) e de stats (60s),
   então 30s é o ponto ótimo — bate no cache de placar sempre e no de stats
   a cada dois polls. Era 15s, o que com TTL de 20s garantia miss em stats
   a cada visita. Dobrar o intervalo reduz ~50% das requisições de stats
   sem atrasar o placar (fixture atualiza em 30s de qualquer forma). */
const POLL_MS = 30_000

const STATUS_LABEL: Record<string, string> = {
  '1H': '1º Tempo', HT: 'Intervalo', '2H': '2º Tempo', ET: 'Prorrogação',
  FT: 'Encerrado', AET: 'Encerrado', PEN: 'Encerrado', NS: 'Não iniciado',
}

/* O teaser de quem não assina. Times, liga, odd e o minuto · nunca mercado,
   linha, análise, probabilidade ou stake, que é o que se paga. */
interface TeaserAoVivo {
  id: number
  league_name?: string | null
  home_team_name?: string | null
  away_team_name?: string | null
  odd?: number | string | null
  minute_at_creation?: number | null
}

interface LivePick {
  id: number
  fixture_id: number
  /* O feed já mandava o id da liga e a interface não o declarava · sem ele o
     cabeçalho do card mostrava o nome da competição sem o escudo, que é a
     única peça do cabeçalho VIP que faltava aqui. */
  league_id?: number
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
  /** Kelly do backend sobre a banca de quem está lendo · null sem banca. */
  suggested_stake_units?: number | null
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
function TituloDeSecao({ cor, texto, contagem }: {
  cor: string
  texto: string
  /* A CONTAGEM É ELEMENTO, NÃO TEXTO (29/08, pedido do usuário).
   *
   * Ela vinha colada no título por um ponto médio ("Suas apostas ao vivo · 3"),
   * e o ponto saiu da aba inteira. Passar o número por prop, e não dentro da
   * string, é o que impede o separador de voltar na próxima seção que alguém
   * escrever. */
  contagem?: number
}) {
  return (
    <div className="flex items-center gap-3 mb-4 mt-6 first:mt-0">
      <span className={`w-0.5 h-5 ${cor} rounded-full block`} />
      <h2 className="text-sm font-bold text-ink-2">{texto}</h2>
      {contagem != null && (
        <span className="font-mono text-[11px] font-bold tabular-nums text-ink-3
                         bg-surface-2 border border-line rounded-full px-2 py-0.5">
          {contagem}
        </span>
      )}
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

/* Ritmo, tendência, pressão e o nível de cada um saíram daqui em 28/08.
   Eles descrevem o INSTANTE DA CRIAÇÃO do pick, e no card viravam uma faixa de
   micro-rótulos de 10px embaixo de tudo · agora moram no "Entenda esta
   análise" (LiveAnalysisModal), ao lado do snapshot que explicam. */

function Contagem({ segundos }: { segundos: number | null }) {
  const [restante, setRestante] = useState(segundos ?? 0)
  useEffect(() => { setRestante(segundos ?? 0) }, [segundos])
  useEffect(() => {
    if (restante <= 0) return
    const t = setInterval(() => setRestante(s => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [restante])

  if (segundos === null) return null
  const expirou = restante <= 0
  const apertado = restante > 0 && restante <= 30
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-bold tabular-nums ${
      expirou ? 'text-ink-4' : apertado ? 'text-amber-400' : 'text-ink-3'}`}>
      <Timer size={11} />
      {expirou
        ? 'preço da criação, confira na casa'
        : `odd válida por ${Math.floor(restante / 60)}:${String(restante % 60).padStart(2, '0')}`}
    </span>
  )
}

/*
 * Card de pick AO VIVO · mesma anatomia do card VIP (SuggestionCard).
 *
 * Até 28/08 este card era outro produto visual: cabeçalho próprio, dois
 * ladrilhos de EV/confiança que nenhum outro card tem, oito micro-rótulos de
 * 11px no rodapé (criado aos, ritmo, sinais, projeção, dado) e a prosa do
 * motor dentro de um `<details>` nativo chamado "Por que este pick". Lado a
 * lado com um pick VIP na mesma página, parecia vir de outro site.
 *
 * Agora segue a ordem canônica das peças em PickCardParts:
 *   cabeçalho -> faixa Odd/Aposta/Lucro -> times e mercado -> probabilidade
 *   -> leitura curta -> "Entenda esta análise" -> rodapé de ação.
 *
 * O QUE CONTINUA DIFERENTE, E POR QUÊ: a barra da linha (onde o jogo está em
 * relação ao número apostado) fica no corpo, porque ao vivo ela é a leitura
 * que decide entrar ou não · e a contagem regressiva da odd fica no rodapé,
 * colada na ação, porque é o prazo dela.
 *
 * O que saiu do corpo não sumiu: ritmo, pressão, sinais, projeção, posse e o
 * snapshot da criação foram para o "Entenda esta análise" (LiveAnalysisModal),
 * que é a versão ao vivo do modal do pré-jogo · lá eles ganham rótulo inteiro
 * e a comparação "antes e agora" que no rodapé do card não cabia.
 */
const CardLive = forwardRef<HTMLDivElement, {
  pick: LivePick
  onSeguir: (p: LivePick) => void
  /** Banca do usuário · sem ela o card mostra unidades e não reais. */
  banca?: { bankroll_current: number; unit_value: number } | null
}>(function CardLive({ pick, onSeguir, banca }, ref) {
  const [verAnalise, setVerAnalise] = useState(false)

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
  /* O QUE FECHA O BOTÃO É O RESULTADO, NÃO O RELÓGIO (29/08, decisão do
   * usuário).
   *
   * A odd vencida tirava o botão da tela, e isso confundia prazo com fim: o
   * `EXPIRED` diz que o PREÇO daquele instante caducou, não que o pick
   * acabou. O jogo segue, o pick segue sendo acompanhado e liquidado, e quem
   * quiser entrar pela odd que a casa mostra AGORA está tomando uma decisão
   * legítima -- é o mesmo caso que o backend já aceitava desde 17/07
   * (banca.follow_pick só recusa depois do resultado; a odd real vai no
   * `actual_odd`, e é ela que entra na banca).
   *
   * O prazo continua visível na contagem ao lado, que é onde ele informa sem
   * decidir pela pessoa. */
  const podeSeguir = !pick.is_followed && !encerrado
  const temAposta = !encerrado && aposta.unidades > 0
  const lucroPot = (Number(oddEfetiva) - 1) * aposta.unidades

  return (
  <>
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`pick-card ${PICK_TYPE_BORDER.live} ${encerrado ? 'opacity-75' : ''}`}
    >
      {/* Cabeçalho · tipo, liga e minuto à esquerda; estado à direita. Mesma
          divisão do card VIP, e o minuto ocupa ali o lugar do horário do jogo:
          é o "quando" deste pick. */}
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-3 border-b border-line/60">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <PickTypeBadge type="live" />
          {(pick.league_id || pick.league_name) && (
            <div className="flex items-center gap-1 min-w-0">
              <LeagueLogo id={pick.league_id} name={pick.league_name} />
              {pick.league_name && (
                <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{pick.league_name}</span>
              )}
            </div>
          )}
          {pick.elapsed != null && (
            <span className="flex items-center gap-1 text-[10px] text-ink-4 shrink-0 tabular-nums">
              <Clock className="w-3 h-3" />
              {pick.elapsed}&#39;
            </span>
          )}
        </div>
        <div className="shrink-0">
          {encerrado ? (
            <ResultBadge result={pick.result} />
          ) : pick.is_live ? (
            <Badge tone="green" className="gap-1.5">
              <LiveDot className="w-1.5 h-1.5" />
              {STATUS_LABEL[pick.live_status] ?? 'Ao vivo'}
            </Badge>
          ) : (
            <Badge tone="neutral">{STATUS_LABEL[pick.live_status] ?? pick.live_status}</Badge>
          )}
        </div>
      </div>

      {/* Faixa de números · Odd | Apostar | Lucro pot., exatamente as colunas
          do card VIP. Antes a odd morava numa linha própria e a unidade em
          outra faixa mais abaixo, então o mesmo dado aparecia em dois pesos
          tipográficos diferentes conforme a aba. */}
      <div className="font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
          <div className="text-3xl font-black text-green-400 tabular-nums">
            {Number(oddEfetiva).toFixed(2)}
          </div>
          {/* A odd que o usuário registrou pode divergir da do pick: ele segue
              depois, e a linha se move ao vivo mais que em pré-jogo. */}
          {pick.is_followed && Math.abs(Number(oddEfetiva) - Number(pick.odd)) > 0.001 && (
            <div className="text-[9px] text-ink-4 mt-0.5">pick: {Number(pick.odd).toFixed(2)}</div>
          )}
          {(pick.user_bet_house || pick.bet_house) && (
            <div className="text-[10px] text-ink-4 mt-0.5 truncate">
              {pick.user_bet_house || pick.bet_house}
            </div>
          )}
        </div>

        {encerrado ? (
          <div className="flex-1 px-4 py-3 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">Resultado</div>
            {pick.profit != null ? (
              <>
                <div className={`text-xl font-black tabular-nums ${
                  Number(pick.profit) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {Number(pick.profit) >= 0 ? '+' : ''}{Number(pick.profit).toFixed(2)}u
                </div>
                {banca && (
                  <div className="text-[11px] text-ink-4 tabular-nums">
                    {Number(pick.profit) >= 0 ? '+' : '-'}R$
                    {Math.abs(Number(pick.profit) * banca.unit_value).toFixed(0)}
                  </div>
                )}
              </>
            ) : (
              <div className="text-xl font-black text-ink-3">-</div>
            )}
          </div>
        ) : temAposta ? (
          <>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">{pick.is_followed ? 'Apostado' : 'Apostar'}</div>
              <div className="text-xl font-black text-green-400 tabular-nums">{aposta.unidades}u</div>
              {banca && (
                <div className="text-[11px] text-ink-4 tabular-nums">
                  R${(aposta.unidades * banca.unit_value).toFixed(0)}
                </div>
              )}
            </div>
            <div className="flex-1 px-4 py-3 text-center">
              <div className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</div>
              <div className="text-xl font-black text-ink-1 tabular-nums">+{lucroPot.toFixed(2)}u</div>
              {banca && (
                <div className="text-[11px] text-green-600 font-semibold tabular-nums">
                  +R${(lucroPot * banca.unit_value).toFixed(0)}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 px-4 py-3 text-center">
            <div className="text-[10px] text-ink-3 mb-0.5">EV</div>
            <div className={`text-xl font-black tabular-nums ${
              pick.ev >= 0 ? 'text-green-400' : 'text-ink-3'}`}>
              {pick.ev >= 0 ? '+' : ''}{(pick.ev * 100).toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {/* Times, placar e mercado · o placar entra no lugar do "vs" porque ao
          vivo ele é parte da identificação do jogo, não um detalhe. */}
      <div className="px-5 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <TeamLogo id={pick.home_team_id} name={pick.home_team_name} />
          <span className="text-sm font-bold text-ink-1 truncate">{pick.home_team_name}</span>
          <span className={`text-xs font-black tabular-nums shrink-0 px-1 ${
            pick.is_live ? 'text-green-400' : 'text-ink-3'}`}>
            {pick.home_goals ?? '-'}<span className="text-ink-4">x</span>{pick.away_goals ?? '-'}
          </span>
          <span className="text-sm font-bold text-ink-1 truncate">{pick.away_team_name}</span>
          <TeamLogo id={pick.away_team_id} name={pick.away_team_name} />
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3">
          <span className="font-semibold text-ink-2">{translateMarket(pick.market)}</span>
          {pick.line && <span>{translateLine(pick.line)}</span>}
          <InfoTip text={explainMarket(pick.market, pick.line)} />
        </div>
      </div>

      <PickProbability confidence={pick.confidence} probability={pick.probability} />

      {/* A barra da linha continua no corpo: ao vivo, "onde o jogo está em
          relação ao número" é a leitura que decide entrar. */}
      {temBarra && (
        <div className="px-5 pb-3">
          <BarraDaLinha atual={Number(pick.current_val)} linha={linhaNum} direcao={direcao}
            rotulo={pick.stat_label?.toLowerCase()} />
        </div>
      )}

      <PickReasoning text={pick.reasoning} label="Leitura" />

      <PickExplainButton onClick={() => setVerAnalise(true)} />

      {/* Rodapé · ação à esquerda e prazo da odd à direita, no lugar onde o
          card VIP põe compartilhar. */}
      <div className="flex items-center gap-2 px-5 py-3 border-t border-line/60 mt-auto">
        {pick.is_followed ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-green-400">
            <CheckCircle2 size={12} />
            Em Minhas Apostas
            {pick.user_stake_units ? ` com ${pick.user_stake_units}u` : ''}
          </span>
        ) : podeSeguir ? (
          <Button size="sm" onClick={() => onSeguir(pick)}>Apostar</Button>
        ) : null}

        <div className="ml-auto shrink-0">
          {/* Com a odd vencida o botão continua ali (ver `podeSeguir`), então o
              lugar do prazo passa a dizer o que mudou: o preço da tela é
              histórico, e o que vale é o da casa agora. Some o relógio, entra
              o aviso -- oferecer o botão sem essa linha seria oferecer um
              número que já não existe. */}
          {encerrado ? null : oddVencida ? (
            <span className="text-[10px] text-amber-400 font-semibold">
              odd vencida, confira o preço atual
            </span>
          ) : (
            <Contagem segundos={pick.segundos_de_validade} />
          )}
        </div>
      </div>
    </motion.div>

    <AnimatePresence>
    {verAnalise && (
      <LiveAnalysisModal
        onClose={() => setVerAnalise(false)}
        data={{
          market: pick.market,
          line: pick.line,
          odd: Number(pick.odd),
          probability: pick.probability,
          confidence: pick.confidence,
          ev: pick.ev,
          reasoning: pick.reasoning,
          homeTeam: pick.home_team_name,
          awayTeam: pick.away_team_name,
          minuteAtCreation: pick.minute_at_creation,
          homeGoalsAtCreation: pick.home_goals_at_creation,
          awayGoalsAtCreation: pick.away_goals_at_creation,
          observedAtCreation: pick.observed_at_creation,
          cornersAtCreation: pick.corners_at_creation,
          shotsAtCreation: pick.shots_at_creation,
          shotsOnTargetAtCreation: pick.shots_on_target_at_creation,
          possessionHomeAtCreation: pick.possession_home_at_creation,
          remainingMinutes: pick.remaining_minutes,
          pressureHome: pick.pressure_home,
          pressureAway: pick.pressure_away,
          rhythmLevel: pick.rhythm_level,
          rhythmTrend: pick.rhythm_trend,
          liveSignalScore: pick.live_signal_score,
          projectedTotal: pick.projected_total,
          dataFreshness: pick.data_freshness,
          elapsed: pick.elapsed,
          homeGoals: pick.home_goals,
          awayGoals: pick.away_goals,
          currentVal: pick.current_val,
          statLabel: pick.stat_label,
          isLive: pick.is_live,
        }}
      />
    )}
    </AnimatePresence>
  </>
  )
})

export default function LivePicksFeed({ isActive, banca }: {
  isActive: boolean
  /* Vem da página, que já a carregou pro resto dos cards · buscar de novo aqui
     seria uma segunda fonte pro mesmo número. */
  banca?: { bankroll_current: number; unit_value: number } | null
}) {
  const [picks, setPicks] = useState<LivePick[] | null>(null)
  /* O que o free NÃO vê. Vem do servidor sem mercado, análise nem stake ·
     mesmo contrato de teaser dos outros produtos VIP. */
  const [bloqueados, setBloqueados] = useState<TeaserAoVivo[]>([])
  const [eVip, setEVip] = useState(true)
  const [disponivel, setDisponivel] = useState(true)
  const [motivo, setMotivo] = useState<string | null>(null)
  /* Estado do motor · só o que o assinante precisa (ligado e última varredura).
     O diagnóstico completo continua sendo de admin, em /watch-status. */
  const [motor, setMotor] = useState<EstadoDoMotor>(null)
  const [erro, setErro] = useState(false)
  const [alvo, setAlvo] = useState<LivePick | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [erroModal, setErroModal] = useState<string | null>(null)
  const [atualizando, setAtualizando] = useState(false)
  /* Incrementado pelo botão · é o que faz EmLeituraAgora e o placar buscarem
     de novo. Ver o comentário do prop `recarregar`. */
  const [pedidoDeRecarga, setPedidoDeRecarga] = useState(0)
  const timer = useRef<number | null>(null)
  const navigate = useNavigate()
  /* Uma busca só, dois leitores: a fita do topo e o bloco do rodapé. */
  const { partidas: emLeitura, tick: tickLeitura, disponivel: leituraOk } =
    useEmLeitura(isActive, pedidoDeRecarga)

  const carregar = useCallback(async () => {
    try {
      const r = await api.get('/live-picks/feed')
      setDisponivel(r.data.disponivel !== false)
      setMotivo(r.data.motivo ?? null)
      setMotor(r.data.motor ?? null)
      setPicks(r.data.picks ?? [])
      setBloqueados(r.data.bloqueados ?? [])
      setEVip(r.data.e_vip !== false)
      setErro(false)
    } catch {
      setErro(true)
      setPicks([])
    }
  }, [])

  /* O botão de atualizar. Puxa a barra do topo junto (sinalizarNavegacao)
     porque a espera é a mesma de uma troca de aba, e o site inteiro responde a
     essa espera do mesmo jeito desde 29/08.

     O `finally` solta o botão mesmo com a rede fora: um botão travado em
     "atualizando" é pior que um que falhou, porque tira da pessoa a
     possibilidade de tentar de novo. */
  const atualizarTudo = useCallback(async () => {
    setAtualizando(true)
    sinalizarNavegacao()
    setPedidoDeRecarga(n => n + 1)
    try {
      await carregar()
    } finally {
      setAtualizando(false)
    }
  }, [carregar])

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

  /* SUAS APOSTAS PRIMEIRO, E SEPARADAS (2026-08-29, pedido do usuário).
   *
   * A aba misturava numa lista só o que a pessoa já pegou e o que o motor
   * acabou de publicar · são duas perguntas diferentes. "Já apostei, como está
   * indo?" é acompanhamento e dura até o apito. "Vale entrar?" é decisão e
   * dura o que a odd durar. Juntas, numa noite com cinco picks, a aposta em
   * andamento descia a tela conforme chegavam oportunidades novas.
   *
   * O backend garante que ela ESTÁ na resposta até o jogo acabar (ver o UNION
   * em routers/live_picks.py::feed); aqui ela ganha o topo. */
  const minhas = useMemo(() => emAndamento.filter(p => p.is_followed), [emAndamento])
  const oportunidades = useMemo(() => emAndamento.filter(p => !p.is_followed), [emAndamento])

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
      {/* ComoFunciona ANTES dos picks: igual a todas as outras abas.
          Fecha por padrão — quem conhece o produto passa direto. */}
      <ComoFunciona titulo="O que são os Picks Ao Vivo?" className="mb-4">
        <p>
          A IA lê a partida em andamento e compara com a odd do momento. Só publica quando o jogo
          se afasta do esperado e o preço paga por isso.{' '}
          <span className="font-bold text-ink-1">Confira a odd na casa antes de apostar.</span>
        </p>
        <PlacarDoLive recarregar={pedidoDeRecarga} />
      </ComoFunciona>

      <div className="flex flex-wrap items-center justify-end gap-2 mb-4">
        <div className="flex items-center gap-2">
        {/* O ESTADO DO MOTOR NO TOPO, SEMPRE (29/08, pedido do usuário).
          *
          * Ele existia em dois lugares e nenhum dos dois era o topo: no vazio
          * da aba -- ou seja, só quando NÃO havia pick -- e num aviso âmbar que
          * aparecia apenas com o motor parado. Em noite movimentada, com cards
          * na tela, não havia como saber se o motor seguia varrendo ou se
          * aqueles eram os últimos picks de um motor que já tinha parado.
          *
          * Agora é a primeira coisa da aba, e diz as duas metades da resposta:
          * se está varrendo, e de quando foi a última passada. */}

          {/* ATUALIZAR NA MÃO (29/08, pedido do usuário).
            *
            * A aba já pesquisa sozinha de 15 em 15 segundos, e mesmo assim o
            * botão faz falta: ao vivo a pessoa está decidindo com o jogo
            * rolando, e "esperar até 15 segundos pra ver se mudou" é uma
            * espera sem fim visível. O botão troca isso por uma ação com
            * resposta imediata.
            *
            * Ele puxa as três fontes da aba de uma vez -- picks, leitura e
            * placar -- porque atualizar só uma deixaria a tela meio nova e
            * meio velha, que é pior que velha inteira. */}
          <Button size="sm" variant="ghost" onClick={atualizarTudo} disabled={atualizando}
                  aria-label="Atualizar os dados da aba">
            <RefreshCw className={`w-3.5 h-3.5 ${atualizando ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
          {motor && (() => {
            /* Hibernando NÃO é pausado, e a cor diz isso: continua no verde do
               produto, porque nada está errado -- só não há jogo em campo. O
               âmbar fica reservado pro caso em que alguém desligou, que é o
               único dos três que pede ação de alguém. */
            const dormindo = motor.ligado && motor.hibernando
            return (
              <span className={`flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full border ${
                motor.ligado
                  ? 'border-accent/40 bg-accent/10 text-accent-ink'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-400'}`}>
                {!motor.ligado
                  ? <><PowerOff className="w-3 h-3" /> busca pausada</>
                  : dormindo
                  ? <><Clock className="w-3 h-3" /> aguardando jogo</>
                  : <><LiveDot /> IA buscando entradas</>}
                {motor.ultima_rodada && (
                  <span className="font-mono font-normal opacity-80">
                    {horaCurta(motor.ultima_rodada)}
                  </span>
                )}
              </span>
            )
          })()}
        </div>
      </div>

      <FitaDeBusca partidas={motor?.ligado && !motor.hibernando ? emLeitura : []} />

      {/* O VAZIO PRECISA DIZER SE O MOTOR ESTÁ LIGADO.
        *
        * "Nenhuma oportunidade ao vivo agora" dizia a mesma coisa em duas
        * situações que pedem reações opostas: o motor varreu os jogos e não
        * achou nada -- que é o caso NORMAL, e uma boa notícia sobre o filtro --
        * ou o motor simplesmente não está rodando. Na primeira vale esperar; na
        * segunda, esperar é perder a noite. */}
      {emAndamento.length === 0 && (
        motor?.ligado && motor.hibernando ? (
          <EmptyState
            Icon={Clock}
            title="Nenhum jogo em campo agora"
            description={
              'A IA acompanha partida em andamento, então ela espera o próximo jogo começar '
              + 'para voltar a buscar. Nada é publicado até lá, e nada está errado.'
            }
          />
        ) : motor?.ligado ? (
          <EmptyState
            Icon={Radio}
            title="Nenhuma entrada agora"
            description={
              'A IA está acompanhando os jogos. Ela só publica quando a partida se afasta do '
              + 'esperado e a odd paga por isso.'
              + (motor.ultima_rodada ? ` Última busca às ${horaCurta(motor.ultima_rodada)}.` : '')
            }
          />
        ) : (
          <EmptyState
            Icon={PowerOff}
            title="A busca está pausada"
            description={
              'Nada será publicado até ela voltar. Não é falta de oportunidade.'
              + (motor?.ultima_rodada ? ` A última busca foi às ${horaCurta(motor.ultima_rodada)}.` : '')
            }
          />
        )
      )}

      {minhas.length > 0 && (
        <>
          <TituloDeSecao cor="bg-accent" texto="Suas apostas ao vivo" contagem={minhas.length} />
          <p className="text-[11px] text-ink-4 mb-3">
            Ficam aqui até o apito final, com o resultado entrando sozinho.
          </p>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AnimatePresence mode="popLayout">
              {minhas.map(p => (
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} banca={banca} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      {oportunidades.length > 0 && (
        <>
          <TituloDeSecao
            cor={motor?.ligado ? 'bg-accent' : 'bg-line-strong'}
            texto={minhas.length > 0 ? 'Outras oportunidades' : 'Em andamento'}
            contagem={oportunidades.length}
          />
          {/* Motor desligado COM pick na tela é o caso que mais engana: os
              cards estão lá, parecem novos, e nenhum outro vai chegar. */}
          {motor && !motor.ligado && (
            <p className="text-[11px] text-amber-400 mb-3 flex items-center gap-1.5">
              <PowerOff className="w-3.5 h-3.5 shrink-0" />
              Busca pausada. Estes são os últimos publicados.
            </p>
          )}
          {/* Hibernando com card na tela: o pick continua valendo, mas o placar
              dele não está sendo acompanhado enquanto não há jogo em campo. Sem
              esta linha, um card parado parece card travado. */}
          {motor?.ligado && motor.hibernando && (
            <p className="text-[11px] text-ink-4 mb-3 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 shrink-0" />
              Sem jogo em campo agora. O placar volta a andar quando a próxima partida começar.
            </p>
          )}
          {/* Grade igual à do VIP · o card ao vivo virou o mesmo objeto, e uma
              coluna só o esticava até 1400px numa noite com dois picks. Os
              cortes são os mesmos de Picks.tsx, e param em 3: ao vivo o card é
              mais alto (barra da linha) e uma quarta coluna aperta o placar. */}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AnimatePresence mode="popLayout">
              {oportunidades.map(p => (
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} banca={banca} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      {/* O RESTO DO DIA, TRANCADO.
          Quem não assina vê um pick por dia e o teaser do que ficou de fora ·
          jogo, liga e odd, sem mercado, análise nem stake. É o mesmo contrato
          dos outros produtos VIP, e existe porque a alternativa que estava no
          ar era pior que um cadeado: a aba respondia erro e o produto inteiro
          parecia quebrado. */}
      {!eVip && bloqueados.length > 0 && (
        <div className="mt-6 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            {bloqueados.slice(0, 4).map(b => (
              <div key={b.id} className="card p-4 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-ink-1 truncate">
                    {b.home_team_name} x {b.away_team_name}
                  </p>
                  <p className="text-[11px] text-ink-4 truncate">
                    {b.league_name}
                    {b.minute_at_creation != null ? `, ${b.minute_at_creation}'` : ''}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-[10px] text-ink-4">Odd</p>
                  <p className="font-mono text-base font-black text-ink-2">
                    {b.odd != null ? Number(b.odd).toFixed(2) : '-'}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-lg border border-green-500/30 bg-surface-1 p-5 flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="w-11 h-11 rounded-full border border-green-500/30 flex items-center justify-center shrink-0">
              <Lock className="w-5 h-5 text-green-400" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-display text-ink-1 font-bold text-sm mb-0.5">
                Mais {bloqueados.length} {bloqueados.length === 1 ? 'entrada' : 'entradas'} ao vivo hoje
              </p>
              <p className="text-ink-3 text-xs leading-relaxed">
                O jogo e a odd você já vê. O mercado, a leitura da partida e a sugestão de stake abrem no VIP.
              </p>
            </div>
            <Button to="/checkout" size="sm" className="shrink-0">Assinar VIP</Button>
          </div>
        </div>
      )}

      {/* O QUE O MOTOR ESTÁ LENDO fica DEPOIS dos picks (29/08, pedido do
          usuário). A aba é tela de decisão: primeiro o que dá pra apostar,
          depois o contexto de onde ele pode sair. Ver o cabeçalho do
          componente. */}
      <EmLeituraAgora partidas={emLeitura} tick={tickLeitura} disponivel={leituraOk}
                      motor={motor} />

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
