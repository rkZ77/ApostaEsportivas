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
import { Radio, RefreshCw, Timer, CheckCircle2, Clock, PowerOff, CalendarClock,
         Goal, Flag, Target, Crosshair, Lock, Radar, Ban, Square, Share2, Loader2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { capitalizarFrase } from '../utils/format'
import api from '../services/api'
import ApostaModal from './ApostaModal'
import { Badge, Button, ComoFunciona, EmptyState, ErrorState, LiveDot, PickTypeBadge,
         ResultBadge, Skeleton, SkeletonPickGrid } from './ui'
import { CampoDoPick, PickExplainButton, PickProbability } from './PickCardParts'
import LiveAnalysisModal from './LiveAnalysisModal'
import VarreduraDoRadar from './VarreduraDoRadar'
import { translateLine, translateMarket, metadesDaLinha, nomeDoMercadoComGrade } from '../utils/marketTranslate'
import { LeagueLogo, TeamLogo } from './TeamLogo'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import { pctProb } from '../utils/format'
import { rotuloDoStatus, escudoDoTime } from '../lib/aoVivo'
import { calcVipStake } from '../utils/stakeUtils'
import { sinalizarNavegacao } from '../services/progressBus'
import FiltrosDePicks, { filtrarPicks, ordenarPicks, type OrdemDePick } from './FiltrosDePicks'

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
  /** JOGO EM CAMPO QUE O MOTOR AINDA NÃO LEU.
   *
   *  O motor só entra na partida depois dos primeiros minutos, e até lá não
   *  existe leitura nenhuma dela: sem placar, sem contador, sem minuto. Estes
   *  jogos entram no Radar mesmo assim, porque a alternativa era o Radar
   *  aparecer vazio com jogo rolando na TV. Ver a rota em-leitura. */
  aguardando?: boolean
  /** Minutos desde o apito. NÃO é o minuto do jogo: o intervalo e o atraso do
   *  início entram nessa conta, então a tela escreve "começou há X". */
  iniciado_ha_min?: number | null
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
  const src = escudoDoTime(id ?? undefined)
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

/* A FITA DE BUSCA SAIU (10/09/2026, pedido do usuário).
 *
 * A aba tinha DOIS radares: a fita rolando no topo e o bloco de cartões no
 * rodapé, os dois lendo a mesma lista e dizendo a mesma frase com palavras
 * diferentes. Duas vezes o mesmo sinal não convence o dobro, só divide a
 * atenção · e a fita era a metade que mostrava menos (nome dos times e o
 * minuto, sem contador nenhum).
 *
 * Ficou o bloco, agora chamado RADAR: mesmo ícone pulsando, o verbo do produto
 * no título e os números que fazem alguém entender por que ainda não saiu
 * pick.
 */

interface ProximoJogo {
  fixture_id: number
  home_team: string | null
  away_team: string | null
  home_team_id: number | null
  away_team_id: number | null
  league_id: number | null
  liga: string | null
  /** Brasília SEM fuso · lido por fatia de string, nunca por `new Date`. */
  match_datetime: string
  falta_seg: number
}

/* O DIA DO JOGO, sem deixar o navegador interpretar o horário.
 *
 * `match_datetime` é hora de Brasília gravada sem fuso. Jogar isso num `Date`
 * faz o navegador assumir o fuso DELE e deslocar a partida em horas para quem
 * não está em Brasília -- que é o erro que o resto do site já evita lendo por
 * fatia. A comparação de DIA é feita entre strings "AAAA-MM-DD", que é
 * exatamente o que uma data sem fuso permite comparar sem risco.
 */
const DIAS_CURTOS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb']

function diaDoJogo(iso: string, hojeISO: string, amanhaISO: string): string {
  const dia = iso.slice(0, 10)
  if (dia === hojeISO) return 'hoje'
  if (dia === amanhaISO) return 'amanhã'
  // O nome do dia da semana precisa de calendário, e aqui é seguro: a conta é
  // feita à meia-noite UTC de uma data pura, sem hora nenhuma para deslocar.
  const d = new Date(`${dia}T00:00:00Z`)
  return `${DIAS_CURTOS[d.getUTCDay()]}, ${dia.slice(8, 10)}/${dia.slice(5, 7)}`
}

/** "em 40min", "em 3h20". Vem do servidor em segundos e não depende de fuso. */
function faltaCurto(seg: number): string {
  const min = Math.round(seg / 60)
  if (min < 60) return `em ${Math.max(1, min)}min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m === 0 ? `em ${h}h` : `em ${h}h${String(m).padStart(2, '0')}`
}

/*
 * A AGENDA DO MOTOR.
 *
 * "Nenhum jogo em campo agora" é verdade e encerra a conversa: quem abriu a
 * aba às 15h não sabe se volta em uma hora ou se a tarde inteira vai ser
 * assim, e a tela não dá motivo nenhum pra ele voltar. Aqui ele vê o dia e a
 * hora dos próximos jogos que o motor vai acompanhar.
 *
 * São os jogos que fazem o motor ACORDAR (mesmo critério de
 * `_ha_jogo_na_janela` no backend), não uma agenda de futebol qualquer ·
 * prometer análise de partida que o motor nunca vai abrir seria pior que não
 * mostrar nada.
 */
function AgendaDoMotor({ isActive }: { isActive: boolean }) {
  const [jogos, setJogos] = useState<ProximoJogo[] | null>(null)

  useEffect(() => {
    if (!isActive) return
    let vivo = true
    api.get('/live-picks/proximos-jogos')
      .then(r => { if (vivo) setJogos(r.data?.partidas ?? []) })
      /* Falhou: a agenda simplesmente não aparece. Ela é o complemento do
         estado vazio, e um erro vermelho no lugar dela chamaria mais atenção
         que o próprio assunto da tela. */
      .catch(() => { if (vivo) setJogos([]) })
    return () => { vivo = false }
  }, [isActive])

  if (!jogos || jogos.length === 0) return null

  /* "Hoje" e "amanhã" pelo relógio de Brasília, que é o fuso em que os jogos
     estão gravados · usar o relógio do aparelho marcaria "amanhã" num jogo
     de hoje pra quem está em outro fuso. */
  const hojeISO = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
  const amanha = new Date(`${hojeISO}T12:00:00Z`)
  amanha.setUTCDate(amanha.getUTCDate() + 1)
  const amanhaISO = amanha.toISOString().slice(0, 10)

  return (
    <div className="mt-6">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-1 h-4 rounded-full bg-line-strong" />
        <h3 className="text-sm font-bold text-ink-1 flex items-center gap-1.5">
          <CalendarClock className="w-3.5 h-3.5 text-ink-3" />
          Próximos jogos no radar
        </h3>
      </div>
      <p className="text-[11px] text-ink-4 mb-3 leading-relaxed">
        O motor volta a varrer assim que um destes entrar em campo. A análise começa
        com a partida em andamento, não antes do apito.
      </p>
      <ul className="divide-y divide-line border border-line rounded-xl overflow-hidden bg-surface-1">
        {jogos.map(j => (
          <li key={j.fixture_id} className="flex items-center gap-2.5 px-3 py-2.5">
            <div className="flex flex-col items-center justify-center w-[52px] shrink-0">
              <span className="font-mono text-sm font-bold text-ink-1 tabular-nums leading-none">
                {j.match_datetime.slice(11, 16)}
              </span>
              <span className="text-[10px] text-ink-4 mt-0.5">
                {diaDoJogo(j.match_datetime, hojeISO, amanhaISO)}
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 min-w-0">
                <TeamLogoOrDot id={j.home_team_id} name={j.home_team} />
                <span className="text-sm text-ink-1 truncate">{j.home_team ?? 'Time ?'}</span>
              </div>
              <div className="flex items-center gap-1.5 min-w-0 mt-1">
                <TeamLogoOrDot id={j.away_team_id} name={j.away_team} />
                <span className="text-sm text-ink-1 truncate">{j.away_team ?? 'Time ?'}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-1 min-w-0">
                <LeagueLogo id={j.league_id ?? undefined} name={j.liga ?? ''} />
                <span className="text-[10px] text-ink-4 truncate">{j.liga ?? 'liga ?'}</span>
              </div>
            </div>
            <span className="text-[10px] text-ink-3 shrink-0 tabular-nums">
              {faltaCurto(j.falta_seg)}
            </span>
          </li>
        ))}
      </ul>
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
  const visivel = useJanelaVisivel()
  const [dados, setDados] = useState<{ partidas: EmLeitura[]; disponivel: boolean } | null>(null)
  const [tick, setTick] = useState(0)
  const timer = useRef<number | null>(null)

  const carregar = useCallback(() => {
    api.get('/live-picks/em-leitura')
      .then(r => { setDados(r.data); setTick(0) })
      .catch(() => setDados({ partidas: [], disponivel: false }))
  }, [])

  useEffect(() => {
    if (!isActive || !visivel) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    carregar()
    timer.current = window.setInterval(carregar, POLL_MS)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [isActive, visivel, carregar])

  useEffect(() => {
    // O relógio de "há quantos segundos" também para: ele só existe pra
    // envelhecer o cartão na tela de quem está olhando.
    if (!isActive || !visivel) return
    const t = window.setInterval(() => setTick(v => v + 1), 1000)
    return () => clearInterval(t)
  }, [isActive, visivel])

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
          {/* O RADAR. As ondas saindo do ícone são o que faz a pessoa entender
              que a varredura está ACONTECENDO, e não apenas ligada · o
              `motion-safe` respeita quem pediu menos animação no sistema. */}
          <span className="relative flex items-center justify-center w-5 h-5 shrink-0">
            <span aria-hidden="true"
                  className="absolute inset-0 rounded-full border border-accent/40 motion-safe:animate-ping" />
            <Radar className="relative w-4 h-4 text-accent-ink motion-safe:animate-pulse" aria-hidden="true" />
          </span>
          <h3 className="text-sm font-bold text-ink-1 flex items-center gap-1.5">
            Radar
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
            ? <><LiveDot /> varrendo</>
            : <><PowerOff className="w-3 h-3" /> parado</>}
          {motor?.ultima_rodada && (
            <span className="font-mono text-ink-4">{horaCurta(motor.ultima_rodada)}</span>
          )}
        </span>
      </div>
      {/* A VARREDURA, DESENHADA (10/09/2026, pedido do usuário) · o ícone
          pulsando dizia "ligado" e mais nada. Aqui os jogos aparecem como
          alvos, e a distância até o centro é quanto de partida ainda falta.
          Ver components/VarreduraDoRadar. */}
      <VarreduraDoRadar partidas={partidas} />

      <p className="text-[11px] text-ink-4 mb-3 leading-relaxed">
        Os jogos que a IA varre agora atrás de oportunidade no mercado, com o total da
        partida somando os dois times.
        {comPick === 0 && ' Nenhum virou pick ainda, e isso é o normal.'}
      </p>

      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {partidas.map(p => {
          const { minuto, projetado } = minutoVivo(p, tick)
          const idade = (p.idade_seg ?? 0) + tick
          // A barra é o tempo de jogo, não uma métrica · é o que dá noção de
          // "ainda dá tempo de sair pick aqui" sem precisar de número nenhum.
          const andamento = minuto != null ? Math.min(100, (minuto / 90) * 100) : 0
          /* Jogo ainda não lido não tem número nenhum para mostrar · os quatro
             ladrilhos com "-" seriam quatro promessas vazias ocupando metade
             do cartão. No lugar deles vai uma linha dizendo o que está
             acontecendo de verdade: o motor entra daqui a pouco. */
          const semLeitura = !!p.aguardando
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
                    {/* SEM LEITURA, SEM MINUTO. O tempo desde o apito não é o
                        minuto da partida (o intervalo entra na conta), então o
                        cartão diz o que sabe: que a bola já rolou. */}
                    <span className="font-mono text-[11px] font-bold text-accent-ink tabular-nums"
                          title={projetado ? 'Minuto projetado desde a última leitura' : undefined}>
                      {p.aguardando
                        ? (p.iniciado_ha_min != null ? `há ${p.iniciado_ha_min}min` : 'em campo')
                        : minuto != null
                          ? `${projetado ? '~' : ''}${minuto}'`
                          : rotuloDoStatus(p.status)}
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

                {semLeitura ? (
                  <p className="mt-2.5 text-[10px] text-ink-4 leading-relaxed">
                    A IA entra nesta partida depois dos primeiros minutos, quando o jogo
                    já tem estatística suficiente para ser lido.
                  </p>
                ) : (
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

                )}

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
                      {semLeitura ? 'em campo' : p.fresco ? 'ao vivo' : `lido ${idadeCurta(idade)}`}
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
                    : <span className="text-ink-4">
                        {semLeitura ? 'aguardando os primeiros minutos' : 'sem oportunidade ainda'}
                      </span>}
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



/* Poll de 30s: o backend separou o TTL de fixture (30s) e de stats (60s),
   então 30s é o ponto ótimo — bate no cache de placar sempre e no de stats
   a cada dois polls. Era 15s, o que com TTL de 20s garantia miss em stats
   a cada visita. Dobrar o intervalo reduz ~50% das requisições de stats
   sem atrasar o placar (fixture atualiza em 30s de qualquer forma). */
/* O NAVEGADOR ESTA' NA FRENTE? (2026-09-06, pedido do usuario)
 *
 * `isActive` diz que a aba do PRODUTO ("Picks Ao Vivo") esta' escolhida, e era
 * so' isso que segurava o polling. Com o site aberto numa aba do Chrome que
 * ninguem esta' olhando -- ou com o celular no bolso -- a tela continuava
 * pedindo feed, leitura e odd a cada intervalo, e cada um desses caminhos
 * consulta a API-Football do outro lado.
 *
 * `visibilitychange` responde a pergunta certa: o usuario esta' vendo isto
 * AGORA. Escondeu, para tudo; voltou, busca uma vez na hora (a tela nao pode
 * mostrar dado de dez minutos atras como se fosse de agora) e retoma o ritmo.
 */
function useJanelaVisivel(): boolean {
  const [visivel, setVisivel] = useState(() =>
    typeof document === 'undefined' || !document.hidden)

  useEffect(() => {
    const aoMudar = () => setVisivel(!document.hidden)
    document.addEventListener('visibilitychange', aoMudar)
    return () => document.removeEventListener('visibilitychange', aoMudar)
  }, [])

  return visivel
}

const POLL_MS = 30_000



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
  /** Dia da partida, "YYYY-MM-DD" em Brasília · é o corte de "hoje". */
  match_date?: string | null
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
  /** O contador que liquidou o pick (9 escanteios), e o motivo, se foi anulado.
   *
   *  As duas colunas existem no banco desde 02/09 com este propósito escrito
   *  na migração, e o feed do Ao Vivo não as mandava -- então "empatou com a
   *  linha" e "anulamos porque o provedor não publicou" chegavam na tela como
   *  o mesmo "PUSH, +0.00u", sem nada que os separasse. */
  settled_value?: number | null
  void_reason?: string | null
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

/* Barra do progresso da linha: onde a linha está, onde o jogo está e de que
   lado o pick precisa ficar.

   Os dois rótulos ficam ACIMA da barra, um em cada ponta, em vez de flutuarem
   colados nas posições exatas: com linha 10 e valor 5 eles se sobrepunham, e
   um número em cima do outro não informa nada. A posição continua sendo dada
   pelo desenho · o texto só nomeia. */
/* Ícone do contador que a barra mede. Mesma família de símbolos que a aba já
   usa nos ladrilhos de leitura, então escanteio é escanteio nas duas. */
function IconeDoContador({ rotulo }: { rotulo?: string }) {
  const r = (rotulo ?? '').toLowerCase()
  const Icone =
    r.includes('escanteio') ? Flag
    : r.includes('gol') ? Goal
    : r.includes('cart') ? Square
    : r.includes('alvo') ? Crosshair
    : r.includes('chute') || r.includes('finaliza') ? Target
    : null
  return Icone ? <Icone className="w-3 h-3 shrink-0" /> : null
}

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
      {/* MAIÚSCULA E ÍCONE (2026-09-06, pedido do usuário). O rótulo vinha do
          `stat_label` em caixa baixa ("escanteios 8"), e nome de contador é
          início de frase aqui: é o rótulo de um número, não texto corrido. */}
      <div className="flex items-baseline justify-between text-[10px] text-ink-4 mb-1.5">
        <span className="flex items-center gap-1">
          <IconeDoContador rotulo={rotulo} />
          {capitalizarFrase(rotulo ?? 'agora')}{' '}
          <span className={`font-bold tabular-nums ${favoravel ? 'text-green-400' : 'text-red-400'}`}>
            {atual}
          </span>
        </span>
        <span>Linha <span className="font-bold text-ink-2 tabular-nums">{linha}</span></span>
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
  /** A odd que a casa está pagando NESTE momento, quando a leitura alcançou
   *  este pick. `cotado: false` = o mercado está suspenso agora. */
  oddAgora?: {
    odd: number | null; cotado: boolean; variacao?: number
    /** Chance implícita na odd de agora · sem vig quando os dois lados cotam. */
    prob_mercado?: number | null; prob_sem_vig?: boolean
  } | null
}>(function CardLive({ pick, onSeguir, banca, oddAgora }, ref) {
  const [verAnalise, setVerAnalise] = useState(false)
  /* Compartilhar, igual ao card de pré-jogo: mesma imagem, mesma rota
     (`/pick/live/<id>`), mesmo hook. O card ao vivo era o único sem isso. */
  const { share: compartilhar, sharing: compartilhando, shared: compartilhado } = useShareStoryImage()

  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation()
    compartilhar({
      pickId: pick.id,
      pickTypeRoute: 'live',
      homeTeamName: pick.home_team_name,
      awayTeamName: pick.away_team_name,
      homeTeamId: pick.home_team_id,
      awayTeamId: pick.away_team_id,
      leagueName: pick.league_name,
      pickType: 'live',
      market: translateMarket(pick.market),
      line: translateLine(pick.line),
      house: pick.user_bet_house ?? pick.bet_house ?? undefined,
      odd: Number(pick.odd),
      probabilityPct: pctProb(pick.probability ?? pick.confidence),
      result: pick.result ?? undefined,
      profit: pick.profit != null ? Number(pick.profit) : null,
    })
  }

  /* Encerrado é só o que tem resultado. `EXPIRED` sem resultado quer dizer que
     a JANELA DA ODD fechou sem ninguém seguir · o jogo continua e o pick
     continua sendo acompanhado (ver o cabeçalho deste arquivo). */
  const encerrado = !!pick.result
  /* "Odd vencida" só quando o mercado REALMENTE não está mais lá.
  
     Antes bastava o relógio: o pick nascia com validade de alguns minutos e,
     passados eles, o card dizia "odd vencida" mesmo com a casa ainda cotando.
     Agora a leitura de `/live-picks/odds-agora` responde isso com o mercado na
     mão -- enquanto ela disser `cotado`, o pick está de pé. */
  const oddVencida = pick.status === 'EXPIRED' && !pick.result && !oddAgora?.cotado

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
  /* A BARRA "agora X / linha Y" E' DE JOGO EM ANDAMENTO (2026-09-05, pedido do
     usuario). Ela responde "onde o jogo esta' em relacao ao numero", que e' a
     leitura de quem decide entrar -- num pick ja' liquidado ela mostra um
     "agora" que nao existe mais, ao lado do resultado que ja' fechou a
     conta. */
  const temBarra = pick.current_val != null && !isNaN(linhaNum) && !encerrado
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

  /* A ODD DA TELA MUDA DE DONO QUANDO A PESSOA PEGA O BILHETE (10/09/2026,
   * pedido do usuario).
   *
   * Antes o numero grande era sempre o da publicacao e a odd de agora entrava
   * numa linha minuscula embaixo. Pra quem AINDA NAO entrou, isso era o dado
   * errado em destaque: o preco que ele vai digitar na casa e' o de agora, e o
   * da publicacao so' serve de referencia. Entao pra ele o numero grande passa
   * a ser o preco corrente, com o da publicacao virando a nota de rodape.
   *
   * Depois de seguir, o inverso: a odd dele esta' travada no bilhete e ficar
   * mexendo naquele numero seria mentir sobre a aposta que ele tem. Dali em
   * diante quem continua se movendo na tela sao a leitura da partida e as
   * probabilidades -- a odd, nao. */
  const seguido = !!pick.is_followed
  const oddCorrente = (!encerrado && !seguido && oddAgora?.cotado && oddAgora.odd != null)
    ? Number(oddAgora.odd)
    : null
  const oddExibida = seguido ? Number(oddEfetiva) : (oddCorrente ?? Number(pick.odd))
  const lucroPot = (oddExibida - 1) * aposta.unidades

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
          {/* Pick JA' LIQUIDADO nao carrega o selo "Ao Vivo" nem o minuto: os
              dois dizem "esta' acontecendo agora", e na secao de encerrados
              isso e' uma partida que ja' terminou. Sobra a liga, que continua
              verdadeira. */}
          {!encerrado && <PickTypeBadge type="live" />}
          {(pick.league_id || pick.league_name) && (
            <div className="flex items-center gap-1 min-w-0">
              <LeagueLogo id={pick.league_id} name={pick.league_name} />
              {pick.league_name && (
                <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{pick.league_name}</span>
              )}
            </div>
          )}
          {pick.elapsed != null && !encerrado && (
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
              {rotuloDoStatus(pick.live_status) || 'Ao vivo'}
            </Badge>
          ) : (
            <Badge tone="neutral">{rotuloDoStatus(pick.live_status)}</Badge>
          )}
        </div>
      </div>

      {/* Faixa de números · Odd | Apostar | Lucro pot., exatamente as colunas
          do card VIP. Antes a odd morava numa linha própria e a unidade em
          outra faixa mais abaixo, então o mesmo dado aparecia em dois pesos
          tipográficos diferentes conforme a aba. */}
      <div className="font-mono flex items-stretch divide-x divide-line/60 border-b border-line/60">
        <div className="flex-1 px-5 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">
            {oddCorrente != null ? 'Odd agora' : 'Odd'}
          </div>
          <div className="text-3xl font-black text-green-400 tabular-nums">
            {oddExibida.toFixed(2)}
          </div>
          {/* A odd que o usuário registrou pode divergir da do pick: ele segue
              depois, e a linha se move ao vivo mais que em pré-jogo. */}
          {seguido && Math.abs(Number(oddEfetiva) - Number(pick.odd)) > 0.001 && (
            <div className="text-[9px] text-ink-4 mt-0.5">pick: {Number(pick.odd).toFixed(2)}</div>
          )}
          {/* A odd da PUBLICAÇÃO vira a nota de rodapé, e só quando ela de fato
              difere do preço de agora · repetir o mesmo número duas vezes em
              dois tamanhos não informa nada. A seta diz para que lado a casa
              moveu desde que o pick saiu. */}
          {oddCorrente != null && Math.abs(oddCorrente - Number(pick.odd)) > 0.001 && (
            <div className="text-[9px] mt-0.5 tabular-nums text-ink-4">
              publicada {Number(pick.odd).toFixed(2)}
              <span className={oddCorrente > Number(pick.odd) ? 'text-accent-ink font-bold ml-1'
                                                              : 'text-red-400 font-bold ml-1'}>
                {oddCorrente > Number(pick.odd) ? '↑' : '↓'}
              </span>
            </div>
          )}
          {!encerrado && !seguido && oddAgora && !oddAgora.cotado && (
            <div className="text-[9px] text-amber-400/80 mt-0.5">sem cotação agora</div>
          )}
          {/* Odd vencida SEM leitura nenhuma (a rota falhou, ou o pick é de um
              jogo que a leitura não alcança): o preço da tela é histórico, e
              dizer isso ao lado dele é o mínimo antes de alguém copiar o
              número pra casa. */}
          {!encerrado && !oddAgora && oddVencida && (
            <div className="text-[9px] text-amber-400/80 mt-0.5">confira o preço na casa</div>
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
          <TeamLogo id={pick.home_team_id} name={pick.home_team_name} size={18} />
          <span className="text-sm font-bold text-ink-1 truncate">{pick.home_team_name}</span>
          <span className={`text-xs font-black tabular-nums shrink-0 px-1 ${
            pick.is_live ? 'text-green-400' : 'text-ink-3'}`}>
            {pick.home_goals ?? '-'}<span className="text-ink-4">x</span>{pick.away_goals ?? '-'}
          </span>
          <span className="text-sm font-bold text-ink-1 truncate">{pick.away_team_name}</span>
          <TeamLogo id={pick.away_team_id} name={pick.away_team_name} size={18} />
        </div>
        {/* CAMPOS ROTULADOS, COMO NO CARD DA ABA HOJE (04/09, pedido do
            usuário) · aqui o mercado e a linha saíam soltos na mesma frase
            ("Escanteios Mais/Menos Menos de 11.0"), e o card ao vivo era o
            único produto do site que ainda escrevia a aposta assim. Com o
            rótulo, cada pergunta tem um lugar: O QUÊ, QUANTO e ONDE PEGAR.

            "Deu" não entra: o contador ainda está correndo, e a barra logo
            abaixo já mostra onde o jogo está em relação à linha. */}
        <dl className="space-y-0.5">
          <CampoDoPick rotulo="Mercado">
            <dd className="text-xs font-semibold text-ink-2 truncate">
              {nomeDoMercadoComGrade(pick.market, pick.line)}
            </dd>
          </CampoDoPick>
          {pick.line && (
            <CampoDoPick rotulo="Linha">
              <dd className="text-xs text-ink-2 truncate">
                {translateLine(pick.line)}
                {/* LINHA ASIÁTICA DITA COM ESSE NOME (2026-09-06, pedido do
                    usuário). "Menos de 1.75" parece um limiar como 1.5, e não
                    é: a aposta é partida em 1.5 e 2.0, e é daí que sai o meio
                    green que aparecia no resultado sem nada na tela ter
                    avisado. A liquidação já tratava a grade certa. */}
                {metadesDaLinha(pick.line) && (
                  <span className="block text-[10px] text-ink-4 mt-0.5">
                    asiática: metade em {metadesDaLinha(pick.line)![0]}, metade em {metadesDaLinha(pick.line)![1]}
                  </span>
                )}
              </dd>
            </CampoDoPick>
          )}
          {(pick.user_bet_house || pick.bet_house) && (
            <CampoDoPick rotulo="Casa">
              <dd className="text-xs text-ink-3 truncate">
                {pick.user_bet_house || pick.bet_house}
              </dd>
            </CampoDoPick>
          )}
        </dl>
      </div>

      <PickProbability confidence={pick.confidence} probability={pick.probability}
        mercadoAgora={oddAgora?.cotado
          ? { valor: oddAgora.prob_mercado ?? null, semVig: oddAgora.prob_sem_vig }
          : null} />

      {/* A barra da linha continua no corpo: ao vivo, "onde o jogo está em
          relação ao número" é a leitura que decide entrar. */}
      {temBarra && (
        <div className="px-5 pb-3">
          <BarraDaLinha atual={Number(pick.current_val)} linha={linhaNum} direcao={direcao}
            rotulo={pick.stat_label?.toLowerCase()} />
        </div>
      )}

      {/* POR QUE DEU PUSH · a unica leitura que este card nao entregava.
        *
        * PUSH chega na tela como "+0.00u" e mais nada, e ele tem DUAS causas
        * que nao se parecem: empate com a linha (regra do mercado -- 9
        * escanteios numa linha de 9.0, a casa devolve a entrada) e anulacao
        * nossa (o provedor nao publicou o numero, ou o jogo foi pra
        * prorrogacao e a folha soma 120 minutos). Sem separar as duas, um
        * resultado legitimo e um defeito nosso ficam identicos na tela -- e e'
        * o defeito que passa batido, que e' o pior dos dois lados.
        *
        * O card de pre-jogo (SuggestionCard) ja' dizia isso desde 02/09. Aqui
        * nao dizia, apesar de o backend gravar as duas colunas: o feed do Ao
        * Vivo simplesmente nao as mandava (ver o SELECT em live_picks.feed). */}
      {pick.result === 'PUSH' && (pick.void_reason || pick.settled_value != null) && (
        <div className="mx-5 mb-3 flex items-start gap-2 rounded-md border border-line
                        bg-surface-2/50 px-3 py-2">
          <Ban className="w-3.5 h-3.5 text-ink-4 shrink-0 mt-px" />
          <p className="text-[11px] text-ink-3 leading-relaxed">
            {pick.void_reason ? (
              <>
                <span className="font-semibold text-ink-2">Pick anulado.</span>{' '}
                {capitalizarFrase(pick.void_reason)}, então a aposta é devolvida e
                não conta como acerto nem como erro.
              </>
            ) : (
              <>
                <span className="font-semibold text-ink-2">Empatou com a linha.</span>{' '}
                O jogo fechou em {Number(pick.settled_value)}, exatamente a linha
                apostada, então a aposta é devolvida e não conta como acerto nem
                como erro.
              </>
            )}
          </p>
        </div>
      )}


      {/* O ESPAÇADOR QUE O "Fato" ERA.
        *
        * `.pick-card` é `flex flex-col h-full`: numa grade, todos os cards da
        * linha têm a altura do mais alto. Quem absorvia essa sobra era o bloco
        * do fato, com `flex-1`. Sem alguém absorvendo, o rodapé de cada card
        * para onde o conteúdo dele acabar, e quatro picks lado a lado ficam
        * com "Entenda esta análise" em quatro alturas diferentes. */}
      <div className="flex-1" aria-hidden="true" />
      <PickExplainButton onClick={() => setVerAnalise(true)} />

      {/* Rodapé · ação à esquerda e prazo da odd à direita, no lugar onde o
          card VIP põe compartilhar. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2 px-5 py-3 border-t border-line/60 mt-auto">
        {/* MESMO SELO DOS OUTROS CARDS (2026-09-06, pedido do usuário): pick já
            pego vira "Bilhete registrado" no lugar do botão, com a moldura verde
            do pré-jogo (ver PickCardFooter). Antes era uma frase solta ("Em
            Minhas Apostas com 1u") que ocupava o lugar do botão sem parecer
            parte da mesma família de cards. A stake fica junto, porque ao vivo
            ela varia mais que no pré-jogo. */}
        {pick.is_followed ? (
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-bold px-3 py-2
                           rounded-md border border-accent/30 text-accent-ink bg-accent/10 min-h-[36px]">
            <CheckCircle2 size={13} />
            {/* Só o rótulo. A stake já aparece na faixa de números do topo
                ("Apostado 1u"), e repeti-la aqui gastava a largura do botão
                dizendo de novo o que está três linhas acima -- no celular ela
                era o que fazia o rodapé quebrar em duas linhas. */}
            Bilhete registrado
          </span>
        ) : podeSeguir ? (
          <Button size="sm" onClick={() => onSeguir(pick)}>Pegar bilhete</Button>
        ) : null}

        <div className="ml-auto shrink-0 flex items-center gap-3">
          {/* O prazo da odd continua aqui enquanto ele existe. O AVISO de odd
              vencida saiu deste canto (2026-09-06, pedido do usuário): ele
              agora mora junto da própria odd, que é o número sobre o qual ele
              fala -- ver "sem cotação agora" na faixa de cima. */}
          {!encerrado && !oddVencida && (
            <Contagem segundos={pick.segundos_de_validade} />
          )}
          {/* MESMO BOTAO DOS OUTROS CARDS (2026-09-06, pedido do usuário):
              marcação, borda, tamanho e estados copiados de PickCardFooter --
              inclusive o rótulo que some abaixo de 640px, que é como o card de
              pré-jogo já se comporta no celular. */}
          <button
            onClick={handleShare}
            disabled={compartilhando}
            title="Compartilhar pick"
            className="flex items-center gap-1.5 text-xs font-semibold text-ink-2 hover:text-accent-ink
                       border border-line-strong hover:border-accent/50 px-3 py-2 rounded-md
                       transition-colors duration-1 ease-smooth disabled:opacity-60 min-h-[36px]"
          >
            {compartilhando
              ? <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
              : compartilhado
              ? <CheckCircle2 className="w-3.5 h-3.5 text-accent-ink shrink-0" />
              : <Share2 className="w-3.5 h-3.5 shrink-0" />}
            <span className="hidden sm:inline">
              {compartilhando ? 'Gerando...' : compartilhado ? 'Pronto' : 'Compartilhar'}
            </span>
          </button>
        </div>
      </div>
    </motion.div>

    <AnimatePresence>
    {verAnalise && (
      <LiveAnalysisModal
        onClose={() => setVerAnalise(false)}
        pickId={pick.id}
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

/** De quanto em quanto tempo a tela pede a odd corrente. Casa com o cache de
 *  3 minutos do servidor: pedir antes disso devolveria a mesma leitura. */
const INTERVALO_ODD_MS = 3 * 60 * 1000

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
  /* ODD DE AGORA (2026-09-06, pedido do usuario). Uma leitura no servidor cobre
     todos os picks abertos de todos os usuarios (`/odds/live` sem fixture
     devolve o mundo), e la' o cache de 60s segura o custo mesmo com a aba de
     varias pessoas pedindo a cada 15 segundos. */
  const [oddsAgora, setOddsAgora] = useState<Record<string, {
    odd: number | null; cotado: boolean; variacao?: number
    prob_mercado?: number | null; prob_sem_vig?: boolean
  }>>({})
  const ultimaOdd = useRef(0)
  const visivel = useJanelaVisivel()
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
    /* A ODD DE AGORA ANDA NO PRÓPRIO RITMO: 3 minutos, não os 15 segundos do
       feed. O cache do servidor já garante que ninguém gasta requisição de API
       antes disso, e pedir a cada poll só produziria resposta repetida.
    
       Fora do try do feed de propósito: a odd é um extra, e uma falha nela não
       pode apagar os picks da tela · falhou, o card mostra só a odd da
       publicação, como antes. */
    const agora = Date.now()
    if (agora - ultimaOdd.current >= INTERVALO_ODD_MS) {
      ultimaOdd.current = agora
      try {
        const o = await api.get('/live-picks/odds-agora')
        if (o.data?.disponivel) setOddsAgora(o.data.picks ?? {})
      } catch { ultimaOdd.current = 0 /* falhou: tenta no próximo poll */ }
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

  /* Poll só com a aba do produto escolhida E a janela na frente do usuário.
     Fora disso não há motivo pra manter a chamada de pé: o backend consulta a
     API-Football nesse caminho, e ninguém está lendo a resposta. */
  useEffect(() => {
    if (!isActive || !visivel) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    carregar()
    timer.current = window.setInterval(carregar, POLL_MS)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [isActive, visivel, carregar])

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

  /* O QUE ESTÁ DE PÉ VEM PRIMEIRO (2026-08-27), E O ENCERRADO VOLTOU DEPOIS
   * DELE (2026-09-05) · as duas decisões do usuário, e elas convivem.
   *
   * A de agosto tirou os encerrados porque eles empurravam o pick vivo pra
   * baixo numa noite movimentada, e a odd ao vivo dura minutos. Isso continua
   * valendo, e é por isso que a lista de baixo é a última coisa da aba.
   *
   * O que a ausência custava: num dia em que os picks já fecharam, a aba dizia
   * "nenhuma entrada agora" e não mostrava os greens que o produto acabou de
   * fazer. Quem abre à noite via uma tela vazia de um dia que teve resultado.
   *
   * O corte é pelo RESULTADO, não pelo status. Odd vencida não encerra pick:
   * ele segue sendo acompanhado e liquidado como qualquer outro (ver o
   * cabeçalho deste arquivo). Cortar por status mandava pra fora um pick de um
   * jogo que ainda estava no 38'. */
  const emAndamento = useMemo(() => (picks ?? []).filter(p => !p.result), [picks])

  /* OS ENCERRADOS DE HOJE VOLTARAM (2026-09-05, pedido do usuario).
  
     Eles saíram em agosto porque empurravam o pick vivo pra baixo numa noite
     movimentada, e a odd ao vivo dura minutos. A razao continua valendo -- por
     isso eles ficam NO FIM, depois das suas apostas e das oportunidades, e
     nunca antes.
  
     O que a ausencia deles custava: numa noite em que os tres picks do dia ja'
     fecharam, a aba dizia "nenhuma entrada agora" e nao mostrava os greens que
     acabaram de sair. O produto tinha trabalhado o dia inteiro e a tela dele
     estava vazia. `feed` ja' devolve os liquidados (incluir_encerrados nasce
     true), entao isto nao custa consulta nenhuma. */
  const encerrados = useMemo(() => {
    /* SO' OS DE HOJE. O feed pede `dias=1` (hoje mais um dia pra tras) porque
       pick seguido nao pode sair da lista antes do apito, e isso trazia jogo
       de ONTEM pra uma secao chamada "hoje". O corte e' por `match_date`, que
       ja' vem em Brasilia, comparado com o dia de Brasilia -- nao por
       `created_at` nem por `new Date`, que reinterpretaria no fuso do leitor. */
    const hoje = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
    return (picks ?? []).filter(p => !!p.result && String(p.match_date ?? '').slice(0, 10) === hoje)
  }, [picks])
  const greensDeHoje = useMemo(() => encerrados.filter(p => p.result === 'GREEN').length, [encerrados])

  /* MESMA BARRA DE FILTRO DAS OUTRAS ABAS (07/09).
     A lista de encerrados chega a dez cards num dia normal e nao tinha
     controle nenhum: "quais deram green" so' se respondia rolando a pagina.
     Liga sai de dentro do proprio componente compartilhado quando ha' mais de
     uma, entao aqui nao ha' regra propria. */
  const [liveLiga, setLiveLiga]           = useState('')
  const [liveResultado, setLiveResultado] = useState('')
  const [liveOrdem, setLiveOrdem]         = useState<OrdemDePick>('rank')
  const encerradosDaAba = useMemo(
    () => ordenarPicks(filtrarPicks(encerrados as any[], liveLiga, liveResultado), liveOrdem),
    [encerrados, liveLiga, liveResultado, liveOrdem],
  )

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
      {/* Magenta, a cor do produto · mesmo tratamento das Múltiplas em azul e
          do Pick Boost. O verde daqui era o verde da MARCA, que toda tela usa:
          num produto que se abre ao lado de outros, ele não distinguia nada. */}
      <ComoFunciona titulo="O que são os Picks Ao Vivo?" className="mb-4"
                    cor="text-indigo-300"
                    borda="border-indigo-400/20" fundo="bg-indigo-400/5">
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

          {/* O BOTÃO "ATUALIZAR" SAIU (01/09/2026, pedido do usuário).
              Ele existia para encurtar a espera dos 15 segundos do polling,
              mas cobrava uma barra de ferramentas inteira em cima dos picks
              para uma ação que a aba já faz sozinha. A aba continua se
              atualizando no mesmo intervalo · o que sumiu é o botão, não o
              comportamento.

              E o estado do motor deixa de ser uma pílula desenhada aqui e
              passa a usar o `Badge` do design system, como todo selo do site.
              Hibernando NÃO é pausado, e o tom diz isso: verde enquanto está
              tudo certo, âmbar só no caso em que alguém desligou, que é o
              único dos três que pede ação de alguém. */}
          {motor && (() => {
            const dormindo = motor.ligado && motor.hibernando
            return (
              <Badge tone={motor.ligado ? 'green' : 'amber'}>
                {!motor.ligado
                  ? <><PowerOff className="w-3 h-3" /> Radar pausado</>
                  : dormindo
                  ? <><Clock className="w-3 h-3" /> Aguardando jogo</>
                  : <><Radar className="w-3 h-3" /> Radar varrendo o mercado</>}
                {motor.ultima_rodada && (
                  <span className="font-mono font-normal opacity-70">
                    {horaCurta(motor.ultima_rodada)}
                  </span>
                )}
              </Badge>
            )
          })()}
        </div>
      </div>

      {/* O VAZIO PRECISA DIZER SE O MOTOR ESTÁ LIGADO.
        *
        * "Nenhuma oportunidade ao vivo agora" dizia a mesma coisa em duas
        * situações que pedem reações opostas: o motor varreu os jogos e não
        * achou nada -- que é o caso NORMAL, e uma boa notícia sobre o filtro --
        * ou o motor simplesmente não está rodando. Na primeira vale esperar; na
        * segunda, esperar é perder a noite. */}
      {/* O TEASER JÁ EXPLICA O VAZIO (10/09). Com o Ao Vivo VIP puro, quem não
        * assina nunca tem card na tela, então o estado vazio dispararia sempre
        * · "Nenhuma entrada agora" logo acima de quatro jogos trancados é a
        * contradição que faz a aba parecer quebrada, que é justamente o que o
        * teaser veio resolver. */}
      {emAndamento.length === 0 && encerrados.length === 0 && bloqueados.length === 0 && (
        motor?.ligado && motor.hibernando ? (
          <>
            <EmptyState
              Icon={Clock}
              title="Nenhum jogo em campo agora"
              description={
                'A IA acompanha partida em andamento, então ela espera o próximo jogo começar '
                + 'para voltar a buscar. Nada é publicado até lá, e nada está errado.'
              }
            />
            {/* O ESTADO VAZIO GANHA UM DEPOIS (10/09/2026, pedido do usuário).
                "Nenhum jogo em campo" fecha a conversa; a agenda diz quando
                ela recomeça, e é a única coisa que dá motivo pra voltar. */}
            <AgendaDoMotor isActive={isActive} />
          </>
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
          <>
            <EmptyState
              Icon={PowerOff}
              title="O radar está pausado"
              description={
                'Nada será publicado até ele voltar. Não é falta de oportunidade.'
                + (motor?.ultima_rodada ? ` A última varredura foi às ${horaCurta(motor.ultima_rodada)}.` : '')
              }
            />
            {/* Pausado, a agenda continua verdadeira: são os jogos por causa
                dos quais ele vai voltar a varrer. */}
            <AgendaDoMotor isActive={isActive} />
          </>
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
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} banca={banca}
                          oddAgora={oddsAgora[String(p.id)]} />
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
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} banca={banca}
                          oddAgora={oddsAgora[String(p.id)]} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      {encerrados.length > 0 && (
        <>
          <TituloDeSecao
            cor="bg-line-strong"
            texto="Já encerrados hoje"
            contagem={encerrados.length}
          />
          <p className="text-[11px] text-ink-4 mb-3">
            {greensDeHoje > 0
              ? `${greensDeHoje} ${greensDeHoje === 1 ? 'green' : 'greens'} até agora. `
              : ''}
            Estes já foram liquidados e não aceitam mais entrada.
          </p>
          <div className="mb-3">
            <FiltrosDePicks
              picks={encerrados as any[]} liga={liveLiga} setLiga={setLiveLiga}
              resultado={liveResultado} setResultado={setLiveResultado}
              ordem={liveOrdem} setOrdem={setLiveOrdem}
              mostrados={encerradosDaAba.length}
            />
          </div>
          {encerradosDaAba.length === 0 ? (
            <p className="text-xs text-ink-4 py-6 text-center">
              Nenhum pick encerrado com esses filtros. Limpe o filtro para ver o dia inteiro.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {encerradosDaAba.map(p => (
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} banca={banca} />
              ))}
            </div>
          )}
        </>
      )}

      {/* O DIA INTEIRO, TRANCADO (10/09).
          O Ao Vivo virou VIP puro: quem não assina não vê pick nenhum completo,
          só o teaser · jogo, liga e odd, sem mercado, análise nem stake. É o
          mesmo contrato dos outros produtos VIP, e o teaser fica porque a
          alternativa que estava no ar antes dele era pior que um cadeado: a aba
          respondia erro e o produto inteiro parecia quebrado. */}
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

          <div className="rounded-lg border border-indigo-500/30 bg-surface-1 p-5 flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="w-11 h-11 rounded-full border border-indigo-500/30 flex items-center justify-center shrink-0">
              <Lock className="w-5 h-5 text-indigo-300" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-display text-ink-1 font-bold text-sm mb-0.5">
                {bloqueados.length} {bloqueados.length === 1 ? 'entrada' : 'entradas'} ao vivo hoje
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
