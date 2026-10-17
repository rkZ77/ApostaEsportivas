import { useEffect, useState, useRef, useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Star } from 'lucide-react'
import { separarFavoritos, useTimesFavoritos } from '../lib/timesFavoritos'
import { AnimatePresence, m as motion } from 'framer-motion'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { PAGE_WIDTH } from '../lib/pageWidth'
import { capitalizarFrase } from '../utils/format'
import { nomeDaLigaPt, paisDaLiga } from '../lib/paisDaLiga'
import RaioXDoJogo, { FormaPontos } from '../components/jogos/RaioXDoJogo'
import NumeroVivo from '../components/ui/NumeroVivo'
import BandejaDoBilhete from '../components/jogos/BandejaDoBilhete'
import { EstatisticasContent } from './Estatisticas'
import { linkDoRaioX } from '../lib/linkDoRaioX'
import { useAuth } from '../context/AuthContext'
import { Badge, ErrorState, LiveDot, SearchInput, Spinner } from '../components/ui'
import { sinalizarNavegacao } from '../services/progressBus'
import { tabFade } from '../lib/motion'
import { aoVivo as isLive, encerrado as isFinished, escudoDoTime } from '../lib/aoVivo'

// Data de hoje no fuso de Brasília (toISOString retorna UTC e quebraria de madrugada)
const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

function shiftDate(dateStr: string, days: number): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  const dt = new Date(y, m - 1, d + days)
  return dt.toLocaleDateString('en-CA')
}

function formatDateLabel(dateStr: string): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })
}

const DAY_SHORT = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']

function DateStrip({ date, onChange }: { date: string; onChange: (d: string) => void }) {
  const stripRef = useRef<HTMLDivElement>(null)
  // Pivot: semana começando 3 dias antes da data selecionada (7 dias visíveis)
  const [anchor, setAnchor] = useState(() => shiftDate(date, -3))

  const days = Array.from({ length: 7 }, (_, i) => shiftDate(anchor, i))

  const prev = () => setAnchor(a => shiftDate(a, -7))
  const next = () => setAnchor(a => shiftDate(a, 7))
  const goToday = () => {
    setAnchor(shiftDate(TODAY, -3))
    onChange(TODAY)
  }

  return (
    <div className="flex items-center gap-1">
      <button onClick={prev} aria-label="Semana anterior"
        className="w-7 h-7 flex items-center justify-center rounded-lg text-ink-3 hover:text-ink-1 hover:bg-surface-2 transition-colors text-sm shrink-0">
        ‹
      </button>
      <div ref={stripRef} className="flex gap-1 overflow-hidden">
        {days.map(d => {
          const [y, mo, dy] = d.split('-').map(Number)
          const dt = new Date(y, mo - 1, dy)
          const isToday  = d === TODAY
          const isActive = d === date
          return (
            <button key={d} onClick={() => onChange(d)}
              className={`font-mono flex flex-col items-center justify-center w-10 h-12 rounded-md transition-all shrink-0 ${
                isActive
                  ? 'bg-green-500 text-black font-black shadow-lg shadow-green-500/20'
                  : isToday
                  ? 'bg-green-500/10 border border-green-500/30 text-green-400 font-semibold'
                  : 'text-ink-2 hover:bg-surface-2 hover:text-ink-1'
              }`}>
              <span className="text-[9px] leading-none mb-0.5">
                {DAY_SHORT[dt.getDay()]}
              </span>
              <span className="text-sm font-black leading-none">{dy}</span>
            </button>
          )
        })}
      </div>
      <button onClick={next} aria-label="Próxima semana"
        className="w-7 h-7 flex items-center justify-center rounded-lg text-ink-3 hover:text-ink-1 hover:bg-surface-2 transition-colors text-sm shrink-0">
        ›
      </button>
      {date !== TODAY && (
        <button onClick={goToday}
          className="text-[10px] font-bold px-2 py-1 rounded-lg border border-green-500/40 text-accent-ink hover:bg-green-500/10 transition-colors shrink-0 ml-0.5">
          Hoje
        </button>
      )}
    </div>
  )
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  NS:   { label: 'Agendado',    color: 'text-ink-2' },
  '1H': { label: 'AO VIVO 1T', color: 'text-green-400' },
  HT:   { label: 'Intervalo',  color: 'text-yellow-400' },
  '2H': { label: 'AO VIVO 2T', color: 'text-green-400' },
  ET:   { label: 'Prorr.',     color: 'text-orange-400' },
  FT:   { label: 'Encerrado',  color: 'text-ink-3' },
  AET:  { label: 'Enc. Prorr.', color: 'text-ink-3' },
  PEN:  { label: 'Pênaltis',   color: 'text-ink-3' },
  CANC: { label: 'Cancelado',  color: 'text-red-500' },
  PST:  { label: 'Adiado',     color: 'text-red-400' },
}

// isLive/isFinished/TEAM_LOGO saíram daqui pra `lib/aoVivo.ts` em 02/09. As
// listas locais não conheciam SUSP/INT (jogo suspenso ficava sem ser nem ao
// vivo nem encerrado) nem CANC/PST -- ver o cabeçalho de lá.

const leagueLogo = (league_id: number) => `/api/proxy/league/${league_id}.png`

function TeamLogo({ id, name, side, size = 32 }: {
  id?: number; name: string
  /** Inverte a ordem no flex. Omitido, o escudo fica onde estiver no markup. */
  side?: 'left' | 'right'
  size?: number
}) {
  const src = escudoDoTime(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size} loading="lazy"
      className={`object-contain shrink-0 ${
        side === 'left' ? 'order-last' : side === 'right' ? 'order-first' : ''}`}
      style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

interface Fixture {
  fixture_id: number
  match_datetime: string
  home_team: string
  away_team: string
  home_team_id?: number
  away_team_id?: number
  league_name: string
  league_logo?: string
  league_flag?: string
  league_country?: string
  league_id: number
  season?: number | null
  status: string
  elapsed?: number | null
  home_goals: number | null
  away_goals: number | null
  has_pick?: boolean
  pick_market?: string | null
  pick_type_flag?: 'vip' | 'free' | null
  /** Ultimos 5 resultados de cada time, do mais recente pro mais antigo. */
  forma_home?: string[]
  forma_away?: string[]
}

interface LiveStats {
  /* Estado do jogo AGORA (15/10/2026): a lista mostrava status, minuto e
     placar da hora em que a página abriu, e só lia escanteio/chute daqui. */
  status?: string
  elapsed?: number | null
  home_goals?: number | null
  away_goals?: number | null
  home_corners: number
  away_corners: number
  home_shots_on: number
  away_shots_on: number
  home_yellow: number
  away_yellow: number
  home_possession: number
  away_possession: number
}

type PageTab = 'jogos' | 'estatistica'
/* 'aberto' (17/10/2026, pedido do usuário): todo jogo que ainda não acabou,
   os que vão começar e os que estão rolando. */
type Filtro = 'todos' | 'pick' | 'aovivo' | 'aberto'
const GRUPO_FAVORITOS = 'Seus times'
interface EstadoDaLista { date: string; filtro: Filtro; busca: string; rolagem: number }

export default function Fixtures() {
  const { isVip, isAdmin, user }   = useAuth()
  const canSeeStats = isVip || isAdmin || user?.plan === 'trial'
  /* VOLTAR DO RAIO-X (12/10/2026, celular). `abrirJogo` grava na entrada do
     histórico desta lista o dia, o filtro, a busca e a rolagem; o voltar do
     Raio-X traz a lista de volta como estava. Entrar pelo menu não tem estado
     e abre em hoje, no topo. */
  const location = useLocation()
  const [voltando] = useState(() => (location.state as { lista?: EstadoDaLista } | null)?.lista ?? null)
  const [pageTab, setPageTab]      = useState<PageTab>('jogos')
  const [date, setDate]            = useState(voltando?.date ?? TODAY)
  const [fixtures, setFixtures]    = useState<Fixture[]>([])
  const [loading, setLoading]      = useState(true)
  const [statsFixture, setStatsFixture] = useState<Fixture | null>(null)
  /*
   * lg é o mesmo corte que a Navbar e o sino usam.
   *
   * Acima dele o detalhe do jogo abre ao LADO da lista, como em qualquer
   * placar ao vivo; abaixo continua folha sobreposta, porque não há largura
   * pra duas colunas no celular.
   */
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia('(min-width: 1024px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  /*
   * O painel abre com o jogo mais relevante do dia já dentro.
   *
   * Painel vazio ao lado de uma lista cheia é espaço morto, e obriga um clique
   * pra ver a primeira informação. A ordem é a mesma que a pessoa usaria: o que
   * está rolando agora, depois o que a IA escolheu (VIP na frente da Free), e
   * senão o próximo a começar.
   *
   * SÓ no desktop: no celular não existe painel, e pré-selecionar abriria uma
   * folha sobre a lista sem ninguém ter pedido.
   */
  const jogoDestaque = useMemo(() => {
    if (!fixtures.length) return null
    const peso = (f: Fixture) =>
      (isLive(f.status) ? 100 : 0) +
      (f.has_pick ? (f.pick_type_flag === 'vip' ? 20 : 10) : 0) +
      (isFinished(f.status) ? -5 : 0)
    return [...fixtures].sort((a, b) => {
      const d = peso(b) - peso(a)
      if (d !== 0) return d
      return (a.match_datetime ?? '').localeCompare(b.match_datetime ?? '')
    })[0]
  }, [fixtures])

  useEffect(() => {
    if (!isDesktop) return
    // Só preenche o vazio. Trocar a seleção de quem já clicou seria a tela
    // desfazendo o que a pessoa fez.
    setStatsFixture(atual => atual ?? jogoDestaque)
  }, [jogoDestaque, isDesktop])

  // Data nova, destaque novo: manter o jogo de ontem selecionado enquanto a
  // lista mostra hoje é a pior combinação possível.
  // Jogo tocado na aba Ligas espera aqui a troca de data (ver abrirDaLiga).
  const pedidoDaLiga = useRef<Fixture | null>(null)
  useEffect(() => {
    setStatsFixture(pedidoDaLiga.current)
    pedidoDaLiga.current = null
  }, [date])
  const [collapsed, setCollapsed]      = useState<Set<string>>(new Set())
  const [liveStats, setLiveStats]      = useState<Record<number, LiveStats>>({})
  const [erro, setErro]                = useState(false)
  const { favoritos } = useTimesFavoritos()
  const [busca, setBusca]              = useState(voltando?.busca ?? '')
  const [filtro, setFiltro]            = useState<Filtro>(voltando?.filtro ?? 'todos')
  const navigate = useNavigate()

  /*
   * TOCAR NUM JOGO (2026-10-06).
   *
   * No computador o Raio-X abre no painel ao lado, como antes. No celular ele
   * abre na PROPRIA PAGINA (/jogos/<id>), e nao numa folha sobre a lista: tem
   * endereco, o voltar do aparelho funciona e a lista de jogadores ganha a
   * tela inteira. Os times vao na URL porque o jogo pode ser de uma data que
   * a coleta ainda nao trouxe pro banco.
   */
  function abrirJogo(f: Fixture) {
    if (isDesktop) { setStatsFixture(f); return }
    const lista: EstadoDaLista = { date, filtro, busca, rolagem: window.scrollY }
    navigate(location.pathname + location.search, { replace: true, state: { lista } })
    navigate(linkDoRaioX(f), { state: { daLista: true } })
  }

  /* JOGO TOCADO NA ABA LIGAS ("Hoje na liga", 15/10/2026). No computador volta
     pra aba Jogos, em hoje, com o Raio-X dele no painel; no celular abre a
     página do Raio-X como qualquer jogo. Trocar a data zera o painel (efeito
     de `date` acima), então o jogo pedido espera em `pedidoDaLiga`. */
  function abrirDaLiga(f: Fixture) {
    if (!isDesktop) { abrirJogo(f); return }
    setPageTab('jogos')
    if (date !== TODAY) { pedidoDaLiga.current = f; handleDateChange(TODAY) }
    else setStatsFixture(f)
  }

  /* De volta do Raio-X: a rolagem só depois que a lista carregou, senão a
     página ainda não tem altura para chegar lá. Uma vez só. */
  const rolagemPendente = useRef(voltando?.rolagem ?? 0)
  useEffect(() => {
    if (loading || !rolagemPendente.current) return
    const y = rolagemPendente.current
    rolagemPendente.current = 0
    requestAnimationFrame(() => window.scrollTo(0, y))
  }, [loading])

  function fetchFixtures(d: string) {
    setLoading(true)
    /* A falha nao pode terminar na mesma frase que o vazio: ate' 12/09 ela
       caia em `setFixtures([])` e a tela dizia "Nenhum jogo encontrado para
       esta data", que e' uma afirmacao sobre o dia -- e ela era falsa. */
    setErro(false)
    api.get('/fixtures/today', { params: { date: d } })
      .then(r => setFixtures(r.data))
      .catch(() => { setFixtures([]); setErro(true) })
      .finally(() => setLoading(false))
  }

  function handleDateChange(d: string) {
    setDate(d)
    setLiveStats({})
    fetchFixtures(d)
  }

  function toggleCollapse(key: string) {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  useEffect(() => { fetchFixtures(date) }, [])

  /* A LISTA SE ATUALIZA SOZINHA (15/10/2026, pedido do usuário: "não atualiza
     se eu não atualizo a página"). A lista inteira de novo a cada 5 min e ao
     voltar pra aba, SEM o esqueleto de carregando: o servidor guarda o dia
     por 10 min pra todo mundo (fixtures.CACHE_TTL), então isso não custa cota.
     O que muda rápido (minuto, placar) vem do placar ao vivo, logo abaixo. */
  const dateRef = useRef(date)
  dateRef.current = date
  useEffect(() => {
    const recarregar = () => {
      if (document.hidden) return
      const d = dateRef.current
      api.get('/fixtures/today', { params: { date: d } })
        .then(r => { if (dateRef.current === d) setFixtures(r.data) })
        .catch(() => {})
    }
    const timer = setInterval(recarregar, 5 * 60_000)
    document.addEventListener('visibilitychange', recarregar)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', recarregar) }
  }, [])

  /* O JOGO COMO ESTÁ AGORA: o que a lista trouxe, com status, minuto e placar
     do placar ao vivo por cima. Tudo na tela lê daqui, e não de `fixtures`. */
  const jogos = useMemo(() => fixtures.map(f => {
    const ls = liveStats[f.fixture_id]
    if (!ls?.status) return f
    return { ...f, status: ls.status, elapsed: ls.elapsed ?? f.elapsed,
             home_goals: ls.home_goals ?? f.home_goals, away_goals: ls.away_goals ?? f.away_goals }
  }), [fixtures, liveStats])
  const jogosRef = useRef(jogos)
  jogosRef.current = jogos

  /*
   * Atualiza estatísticas ao vivo a cada 30s para jogos em andamento.
   *
   * UMA requisição para todos os jogos, não uma por jogo. Numa rodada de
   * Brasileirão com oito partidas simultâneas eram oito requisições a cada meio
   * minuto, cada uma passando pela checagem de sessão no servidor e pegando um
   * slot do pool de conexões. O endpoint em lote busca as partidas de uma vez
   * só na API-Football (ver live.py::get_live_stats_bulk) e devolve o mesmo
   * formato, chaveado por fixture_id em texto.
   *
   * A aba escondida também não pesquisa: placar ao vivo que ninguém está
   * olhando não vale requisição.
   */
  useEffect(() => {
    /* Quem acompanhar, recalculado A CADA rodada (15/10/2026): os ao vivo, e
       os que a lista ainda dá como "não começou" mas cujo horário já passou
       (até 3h depois) · é assim que o jogo que começa com a página aberta
       vira ao vivo sem F5. Antes a lista era fixada na abertura da página. */
    const acompanhar = () => {
      const agora = Date.now()
      return jogosRef.current.filter(f => {
        if (isLive(f.status)) return true
        if (isFinished(f.status) || !f.match_datetime) return false
        const passou = agora - new Date(f.match_datetime).getTime()
        return passou >= 0 && passou < 3 * 3600_000
      }).map(f => f.fixture_id)
    }

    const fetchAll = () => {
      if (document.hidden) return
      const ids = acompanhar()
      if (ids.length === 0) return
      api.get('/live/live-stats', { params: { fixture_ids: ids.join(',') } })
        .then(r => setLiveStats(prev => {
          const next = { ...prev }
          for (const [fid, stats] of Object.entries((r.data ?? {}) as Record<string, LiveStats>)) {
            next[Number(fid)] = stats
          }
          return next
        }))
        .catch(() => {})
    }

    fetchAll()
    const timer = setInterval(fetchAll, 30_000)
    document.addEventListener('visibilitychange', fetchAll)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', fetchAll)
    }
  }, [fixtures])

  /* Busca por time e os dois recortes que importam num dia cheio: o que a IA
     escolheu e o que está rolando agora. Sem acento e sem caixa: quem digita
     "sao paulo" tem que achar o São Paulo. */
  const semAcento = (t: string) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  const termo = semAcento(busca.trim())
  const visiveis = jogos.filter(f =>
    (filtro !== 'pick' || f.has_pick) &&
    (filtro !== 'aovivo' || isLive(f.status)) &&
    (filtro !== 'aberto' || !isFinished(f.status)) &&
    (!termo || semAcento(`${f.home_team} ${f.away_team} ${f.league_name}`).includes(termo)))

  // Agrupa por liga (preserva ordem de aparição)
  const grouped: { key: string; league_id: number; logo?: string; flag?: string; country?: string; games: Fixture[] }[] = []
  const seen = new Set<string>()
  /* SEUS TIMES (12/10/2026): os jogos dos times com estrela (marcada no
     Raio-X) num grupo próprio no topo, e fora do grupo da liga. */
  const { dosFavoritos, resto } = separarFavoritos(visiveis, favoritos)
  if (dosFavoritos.length) {
    grouped.push({ key: GRUPO_FAVORITOS, league_id: 0, games: dosFavoritos })
  }
  for (const f of resto) {
    if (!seen.has(f.league_name)) {
      seen.add(f.league_name)
      grouped.push({
        key: f.league_name,
        league_id: f.league_id,
        logo: leagueLogo(f.league_id),
        flag: f.league_flag,
        country: f.league_country,
        games: [],
      })
    }
    grouped.find(g => g.key === f.league_name)!.games.push(f)
  }

  const dateLabel  = formatDateLabel(date)
  const liveCount  = jogos.filter(f => isLive(f.status)).length
  const abertosCount = jogos.filter(f => !isFinished(f.status)).length
  const pickCount  = fixtures.filter(f => f.has_pick).length

  return (
    <PageShell
      title="Jogos"
      description="Agenda dos jogos das ligas cobertas, com quais deles já têm pick da IA."
      noindex
      width="full"
      bar={{
        back: true,
        title: 'Jogos',
        sub: <span>{capitalizarFrase(dateLabel)}</span>,
        actions: (
          <>
            {pageTab === 'jogos' && pickCount > 0 && (
              <Badge tone="green" className="hidden sm:inline-flex">{pickCount} picks IA</Badge>
            )}
            {pageTab === 'jogos' && liveCount > 0 && (
              <span className="flex items-center gap-2">
                <LiveDot />
                <span className="text-accent-ink text-xs font-bold">{liveCount} ao vivo</span>
              </span>
            )}
          </>
        ),
      }}
      beforeMain={
        <div className="border-b border-line">
          {/* `beforeMain` é full-bleed de propósito (a borda vai de ponta a
              ponta), então o alinhamento com o conteúdo é por conta de quem
              chama. Lendo a largura do PageShell em vez de repetir o valor,
              mudar a página de faixa não deixa a régua de abas para trás. */}
          <div className={`mx-auto ${PAGE_WIDTH.full}`}>
            {pageTab === 'jogos' && (
              <div className="py-3">
                <DateStrip date={date} onChange={handleDateChange} />
              </div>
            )}
            <div className="flex">
              {([
                /* DUAS ABAS (2026-10-06): o jogo e a liga. Agenda saiu porque
                   repetia a lista de Jogos com três contadores; Explorar saiu
                   porque lia ligas FORA do cadastro direto da API, gastando
                   cota pra mostrar só placar, e a aba ficou só com as ligas
                   cadastradas. "Estatísticas" virou "Ligas": é a visão da
                   liga (tendência, ranking, árbitros), e o Raio-X é a do jogo. */
                { key: 'jogos',       label: 'Jogos' },
                { key: 'estatistica', label: 'Ligas' },
              ] as { key: PageTab; label: string }[]).map(t => (
                <motion.button
                  key={t.key}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => {
                    /* A barra verde do topo fecha quando a tela nova para de
                       buscar dados, mas ela só COMEÇA na troca de rota · e
                       estas abas são estado, não rota. Sem o aviso, trocar pra
                       Ligas ficava alguns segundos sem sinal nenhum de que
                       algo estava vindo. */
                    if (t.key !== pageTab) sinalizarNavegacao()
                    setPageTab(t.key)
                  }}
                  className={`relative px-4 py-2.5 text-sm font-semibold transition-colors ${
                    pageTab === t.key ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2'
                  }`}
                >
                  {t.label}
                  {pageTab === t.key && (
                    <motion.div layoutId="fixtures-tab-underline" className="absolute left-0 right-0 -bottom-px h-0.5 bg-accent" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />
                  )}
                </motion.button>
              ))}
            </div>
          </div>
        </div>
      }
    >
      <AnimatePresence mode="wait">
      {pageTab === 'estatistica' && (
        <motion.div key="estatistica" variants={tabFade} initial="hidden" animate="visible" exit="exit">
          <EstatisticasContent onAbrirJogo={f => abrirDaLiga(f as Fixture)} />
        </motion.div>
      )}

      {pageTab === 'jogos' && <motion.div key="jogos" variants={tabFade} initial="hidden" animate="visible" exit="exit">

        {/* Busca e recortes · no celular a lista de um sábado passa de 40
            jogos, e achar "o do Flamengo" rolando é o que mais se faz aqui. */}
        <div className="flex flex-col sm:flex-row gap-2 mb-3 sm:mb-4 lg:max-w-[720px]">
          <SearchInput value={busca} onChange={setBusca} placeholder="Buscar time ou liga"
            label="Buscar jogo" className="flex-1" />
          {/* Quatro recortes não cabem lado a lado num celular de 360px:
              a fila rola de lado em vez de quebrar a linha. */}
          <div className="flex gap-2 overflow-x-auto scrollbar-none">
            {([['todos', 'Todos'], ['pick', 'Com pick'], ['aovivo', 'Ao vivo'], ['aberto', 'Em aberto']] as const).map(([k, r]) => (
              <button key={k} onClick={() => setFiltro(k)}
                className={`h-11 px-4 rounded-full text-sm font-semibold border shrink-0 transition-colors ${
                  filtro === k ? 'bg-accent text-on-fill border-accent' : 'bg-surface-1 text-ink-2 border-line'}`}>
                {r}{k === 'aovivo' && liveCount > 0 ? ` · ${liveCount}` : ''}
                {k === 'aberto' && abertosCount > 0 ? ` · ${abertosCount}` : ''}
              </button>
            ))}
          </div>
        </div>
        <p className="hidden sm:block text-[11px] text-ink-3 mb-4">
          Só as ligas cadastradas no site. Toque num jogo pra abrir o Raio-X: taxa de acerto por linha,
          jogadores, confronto e árbitro.
        </p>

        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : erro ? (
          <div className="card">
            <ErrorState
              title="Não deu pra carregar os jogos"
              onRetry={() => fetchFixtures(date)}
            />
          </div>
        ) : fixtures.length > 0 && visiveis.length === 0 ? (
          <div className="card p-10 text-center">
            <p className="text-ink-2 text-sm">Nenhum jogo com esse filtro.</p>
            <button onClick={() => { setBusca(''); setFiltro('todos') }}
              className="mt-3 h-11 px-4 rounded-lg border border-line text-sm font-semibold text-ink-2">Limpar filtro</button>
          </div>
        ) : fixtures.length === 0 ? (
          <div data-tour="jogos-lista" className="card p-12 text-center border-dashed">
            <p className="text-ink-4 text-sm">Nenhum jogo encontrado para esta data.</p>
            <p className="text-ink-4 text-xs mt-2">As ligas monitoradas não têm jogos programados neste dia.</p>
          </div>
        ) : (
          /*
             Lista estreita à esquerda, detalhe à direita.

             Antes as ligas ficavam lado a lado em duas colunas largas, pra não
             deixar uma partida sozinha ocupando 1800px de linha. Só que linha
             de jogo não precisa de 900px · precisa caber nome, horário e
             placar. O espaço que sobrava agora vira o painel do jogo
             selecionado, que é onde a largura de tela realmente ajuda.
          */
          <div className="lg:flex lg:gap-5 lg:items-start">
          <div className="grid gap-3 sm:gap-5 items-start lg:w-[420px] xl:w-[460px] lg:shrink-0">
            {grouped.map(({ key: league, league_id, logo, flag, country, games }, i) => {
              const isCopa = league_id === 1
              return (
              /* A primeira liga e' a ancora do passo "Raio-X de cada jogo"
                 do tutorial (onboarding/steps.tsx). */
              <div key={league} data-tour={i === 0 ? 'jogos-lista' : undefined} className={`card overflow-hidden ${isCopa ? 'border border-yellow-500/20' : ''}`}>

                {/* Cabeçalho da liga com logo + bandeira (clicável para recolher) */}
                <div
                  className={`px-3 sm:px-4 py-2 sm:py-3 border-b flex items-center gap-2.5 cursor-pointer select-none ${isCopa ? 'bg-yellow-950/40 border-yellow-700/30' : 'bg-surface-2/60 border-line'}`}
                  onClick={() => toggleCollapse(league)}
                >
                  {league === GRUPO_FAVORITOS && (
                    <Star className="w-4 h-4 text-yellow-300 fill-yellow-300 shrink-0" aria-hidden />
                  )}
                  {logo && (
                    <img src={logo} alt={league} width={24} height={24}
                      className="w-6 h-6 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      />
                  )}
                  {/* Nome e país em português quando a liga é conhecida
                      (lib/paisDaLiga) · o provedor manda "Serie A" e "Brazil". */}
                  <span className={`text-xs font-bold ${isCopa ? 'text-yellow-300' : 'text-ink-2'}`}>{league === GRUPO_FAVORITOS ? league : nomeDaLigaPt(league_id, league)}</span>
                  {(paisDaLiga(league_id)?.pais ?? country) && (
                    <span className={`text-xs font-normal ${isCopa ? 'text-yellow-700' : 'text-ink-4'}`}>{paisDaLiga(league_id)?.pais ?? country}</span>
                  )}
                  {flag && (
                    <img src={flag} alt={country ?? ''} width={18} height={13}
                      className="h-3.5 object-contain shrink-0 rounded-sm"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      />
                  )}
                  {isCopa && <span className="text-[10px] font-black text-yellow-500 ml-1">Copa do Mundo</span>}
                  <span className={`text-xs ml-auto ${isCopa ? 'text-yellow-700' : 'text-ink-4'}`}>{games.length} {games.length === 1 ? 'jogo' : 'jogos'}</span>
                  <svg
                    className={`w-3.5 h-3.5 shrink-0 transition-transform duration-200 ${collapsed.has(league) ? '-rotate-90' : ''} ${isCopa ? 'text-yellow-700' : 'text-ink-4'}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>

                {/* Jogos */}
                {!collapsed.has(league) && <div className="divide-y divide-line/50">
                  {games.map(f => {
                    const st       = STATUS_MAP[f.status] ?? { label: f.status, color: 'text-ink-3' }
                    const live     = isLive(f.status)
                    const finished = isFinished(f.status)
                    const time     = f.match_datetime
                      ? new Date(f.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
                      : '--:--'

                    const ls = liveStats[f.fixture_id]

                    return (
                      <div key={f.fixture_id}>
                      <div
                        className={`flex items-center gap-2.5 sm:gap-3 px-3 sm:px-4 py-2 sm:py-2.5 transition-colors cursor-pointer ${
                          f.has_pick ? 'border-l-2 border-green-500/40' : ''} ${
                          // Selecionado fica marcado: com o painel ao lado, sem
                          // isso não dá pra saber de qual jogo ele fala.
                          statsFixture?.fixture_id === f.fixture_id
                            ? 'bg-surface-2/60' : 'hover:bg-surface-2/30'}`}
                        onClick={() => abrirJogo(f)}
                      >

                        {/*
                          Um time por linha, placar na coluna da direita.

                          O formato antigo era "Nome [escudo] × [escudo] Nome"
                          numa linha só: no celular os dois nomes disputavam a
                          mesma largura e "Independiente del Valle" virava
                          "Independiente d...". Empilhado, cada time tem a linha
                          inteira · é o mesmo motivo pelo qual placar ao vivo em
                          geral usa esse formato.
                        */}
                        <div className="w-12 sm:w-14 shrink-0 flex flex-col justify-center">
                          {live ? (
                            <>
                              <span className="text-[11px] font-bold text-green-400 tabular-nums leading-tight">
                                {f.elapsed ? `${f.elapsed}'` : st.label}
                              </span>
                              <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse mt-1" />
                            </>
                          ) : finished ? (
                            <span className="text-[11px] text-ink-4 leading-tight">{st.label}</span>
                          ) : (
                            <span className="font-mono text-[13px] font-bold text-ink-2 tabular-nums">{time}</span>
                          )}
                        </div>

                        <div className="w-px self-stretch bg-line/60 shrink-0" />

                        <div className="flex-1 min-w-0 space-y-0.5 sm:space-y-1">
                          {([
                            ['home', f.home_team, f.home_team_id, f.home_goals, f.away_goals, f.forma_home] as const,
                            ['away', f.away_team, f.away_team_id, f.away_goals, f.home_goals, f.forma_away] as const,
                          ]).map(([lado, nome, id, gols, golsAdv, forma]) => {
                            // Placar decidido escurece o perdedor, como em
                            // qualquer placar ao vivo · a leitura de quem ganhou
                            // fica instantânea, sem comparar os dois números.
                            const perdeu = finished && (gols ?? 0) < (golsAdv ?? 0)
                            return (
                              <div key={lado} className="flex items-center gap-2">
                                <TeamLogo id={id} name={nome} size={20} />
                                <span className={`text-[13px] flex-1 min-w-0 truncate ${
                                  perdeu ? 'text-ink-4 font-medium'
                                         : live ? 'text-ink-1 font-bold' : 'text-ink-1 font-semibold'}`}>
                                  {nome}
                                </span>
                                {!live && !finished && forma && forma.length > 0 && (
                                  <span className="hidden min-[380px]:block shrink-0">
                                    <FormaPontos forma={forma} tamanho="sm" />
                                  </span>
                                )}
                                {(finished || live) && (
                                  <span className={`font-mono text-sm font-black tabular-nums shrink-0 w-5 text-right ${
                                    live ? 'text-green-400' : perdeu ? 'text-ink-4' : 'text-ink-1'}`}>
                                    {/* Ao vivo o gol rola como placar (15/10/2026). */}
                                    {live ? <NumeroVivo valor={gols ?? 0} /> : (gols ?? 0)}
                                  </span>
                                )}
                              </div>
                            )
                          })}
                        </div>

                        {/* Badge de pick IA + lock hint */}
                        <div className="shrink-0 flex flex-col items-end justify-center gap-0.5 w-auto sm:w-[72px]">
                          {f.has_pick && (
                            <>
                              <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border ${
                                f.pick_type_flag === 'vip'
                                  ? 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
                                  : 'text-green-400 bg-green-500/10 border-green-500/20'
                              }`}>
                                Pick IA
                              </span>
                              {f.pick_market && (
                                <span className="hidden sm:block text-[10px] text-ink-3 max-w-[72px] truncate text-right">
                                  {f.pick_market}
                                </span>
                              )}
                            </>
                          )}
                          {!canSeeStats && (
                            <svg className="w-3 h-3 text-ink-4 mt-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                            </svg>
                          )}
                        </div>
                      </div>

                      {/* Stats ao vivo · aparece apenas quando o jogo está em andamento */}
                      {live && ls && (
                        <div className="font-mono px-4 py-2 bg-green-950/20 border-t border-green-900/20 grid grid-cols-4 gap-1 text-center">
                          <div>
                            <div className="text-[10px] text-ink-3 mb-0.5">Esc</div>
                            <div className="text-xs font-bold text-ink-2">{ls.home_corners} <span className="text-ink-4">-</span> {ls.away_corners}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-ink-3 mb-0.5">Fin</div>
                            <div className="text-xs font-bold text-ink-2">{ls.home_shots_on} <span className="text-ink-4">-</span> {ls.away_shots_on}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-ink-3 mb-0.5">Cart</div>
                            <div className="text-xs font-bold text-ink-2">{ls.home_yellow} <span className="text-ink-4">-</span> {ls.away_yellow}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-ink-3 mb-0.5">Posse</div>
                            <div className="text-xs font-bold text-ink-2">{ls.home_possession}% <span className="text-ink-4">-</span> {ls.away_possession}%</div>
                          </div>
                        </div>
                      )}
                      </div>
                    )
                  })}
                </div>}
              </div>
            )
            })}
          </div>

          {/*
            Painel do jogo selecionado. Só em tela larga · no celular o mesmo
            componente abre como folha sobreposta, logo abaixo.
          */}
          {/* O PAINEL ACOMPANHA A ROLAGEM (12/10/2026, pedido do usuario). O
              `sticky` ja' existia e nao fazia nada: com `items-start` na linha,
              esta coluna tinha so' a altura do proprio painel, e sticky so'
              gruda dentro do espaco da coluna. `self-stretch` a estica ate' a
              altura da lista. `top-20` deixa o painel abaixo do cabecalho fixo
              (h-16), que cobria o topo dele com o `top-4` de antes. */}
          <div className="hidden lg:block lg:self-stretch flex-1 min-w-0">
            {statsFixture ? (
              <div className="sticky top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto pr-1 scrollbar-none">
                <RaioXDoJogo key={statsFixture.fixture_id} jogo={statsFixture} trancado={!canSeeStats} />
              </div>
            ) : (
              <div className="card border-dashed p-12 text-center sticky top-20">
                <p className="text-sm text-ink-3">Clique em um jogo para abrir o Raio-X.</p>
                <p className="text-xs text-ink-4 mt-1.5">
                  Taxa de acerto por linha, jogadores com foto, confronto e árbitro.
                </p>
              </div>
            )}
          </div>
          </div>
        )}
      </motion.div>}
      </AnimatePresence>

      {pageTab === 'jogos' && <BandejaDoBilhete />}

    </PageShell>
  )
}
