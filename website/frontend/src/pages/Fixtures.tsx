import { useEffect, useState, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { PAGE_WIDTH } from '../lib/pageWidth'
import { capitalizarFrase } from '../utils/format'
import FixtureStatsModal from '../components/FixtureStatsModal'
import { EstatisticasContent } from './Estatisticas'
import { useAuth } from '../context/AuthContext'
import { Badge, LiveDot, Spinner } from '../components/ui'
import AgendaInteligente from '../components/AgendaInteligente'
import ExplorarLigas from '../components/ExplorarLigas'
import { backdropFade, dialogScale, tabFade } from '../lib/motion'

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
          className="text-[10px] font-bold px-2 py-1 rounded-lg border border-green-500/40 text-green-500 hover:bg-green-500/10 transition-colors shrink-0 ml-0.5">
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

function isLive(status: string)     { return ['1H', 'HT', '2H', 'ET', 'BT', 'P'].includes(status) }
function isFinished(status: string) { return ['FT', 'AET', 'PEN'].includes(status) }

const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null

const leagueLogo = (league_id: number) => `/api/proxy/league/${league_id}.png`

function TeamLogo({ id, name, side, size = 32 }: {
  id?: number; name: string
  /** Inverte a ordem no flex. Omitido, o escudo fica onde estiver no markup. */
  side?: 'left' | 'right'
  size?: number
}) {
  const src = TEAM_LOGO(id)
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
  status: string
  elapsed?: number | null
  home_goals: number | null
  away_goals: number | null
  has_pick?: boolean
  pick_market?: string | null
  pick_type_flag?: 'vip' | 'free' | null
}

interface LiveStats {
  home_corners: number
  away_corners: number
  home_shots_on: number
  away_shots_on: number
  home_yellow: number
  away_yellow: number
  home_possession: number
  away_possession: number
}

type PageTab = 'jogos' | 'agenda' | 'estatistica' | 'explorar'

export default function Fixtures() {
  const { isVip, isAdmin, user }   = useAuth()
  const canSeeStats = isVip || isAdmin || user?.plan === 'trial'
  const [pageTab, setPageTab]      = useState<PageTab>('jogos')
  const [date, setDate]            = useState(TODAY)
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
    if (!isDesktop || !canSeeStats) return
    // Só preenche o vazio. Trocar a seleção de quem já clicou seria a tela
    // desfazendo o que a pessoa fez.
    setStatsFixture(atual => atual ?? jogoDestaque)
  }, [jogoDestaque, isDesktop, canSeeStats])

  // Data nova, destaque novo: manter o jogo de ontem selecionado enquanto a
  // lista mostra hoje é a pior combinação possível.
  useEffect(() => { setStatsFixture(null) }, [date])
  const [lockPrompt, setLockPrompt]    = useState(false)
  const [collapsed, setCollapsed]      = useState<Set<string>>(new Set())
  const [liveStats, setLiveStats]      = useState<Record<number, LiveStats>>({})

  function fetchFixtures(d: string) {
    setLoading(true)
    api.get('/fixtures/today', { params: { date: d } })
      .then(r => setFixtures(r.data))
      .catch(() => setFixtures([]))
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

  useEffect(() => { fetchFixtures(TODAY) }, [])

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
    const ids = fixtures.filter(f => isLive(f.status)).map(f => f.fixture_id)
    if (ids.length === 0) return

    const fetchAll = () => {
      if (document.hidden) return
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

  // Agrupa por liga (preserva ordem de aparição)
  const grouped: { key: string; league_id: number; logo?: string; flag?: string; country?: string; games: Fixture[] }[] = []
  const seen = new Set<string>()
  for (const f of fixtures) {
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
  const liveCount  = fixtures.filter(f => isLive(f.status)).length
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
                <span className="text-accent text-xs font-bold">{liveCount} ao vivo</span>
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
                { key: 'jogos',       label: 'Jogos' },
                { key: 'agenda',      label: 'Agenda' },
                { key: 'estatistica', label: 'Estatísticas' },
                // Explorar fica DEPOIS de Estatísticas de propósito: as duas
                // respondem a mesma pergunta, mas Estatísticas fala das ligas
                // que a IA cobre, que é o que quase todo mundo quer. Explorar é
                // o passo seguinte, pra quem foi atrás de liga ou ano que o
                // banco não tem.
                { key: 'explorar',    label: 'Explorar' },
              ] as { key: PageTab; label: string }[]).map(t => (
                <motion.button
                  key={t.key}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setPageTab(t.key)}
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
      {pageTab === 'agenda' && (
        <motion.div key="agenda" variants={tabFade} initial="hidden" animate="visible" exit="exit">
          <AgendaInteligente />
        </motion.div>
      )}

      {pageTab === 'estatistica' && (
        <motion.div key="estatistica" variants={tabFade} initial="hidden" animate="visible" exit="exit">
          <EstatisticasContent />
        </motion.div>
      )}

      {pageTab === 'explorar' && (
        <motion.div key="explorar" variants={tabFade} initial="hidden" animate="visible" exit="exit">
          {/* O gate VIP mora dentro do componente, igual ao de
              EstatisticasContent · assim as duas abas irmãs recusam do mesmo
              jeito e ninguém precisa lembrar de repetir a checagem aqui. */}
          <ExplorarLigas />
        </motion.div>
      )}

      {pageTab === 'jogos' && <motion.div key="jogos" variants={tabFade} initial="hidden" animate="visible" exit="exit">

        {/* Banner informativo */}
        <div className="flex items-start gap-3 bg-surface-1 border border-line rounded-lg px-4 py-3 mb-5">
          <svg className="w-4 h-4 text-ink-3 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p className="text-ink-2 text-xs leading-relaxed">
              Exibindo apenas jogos das <span className="text-ink-1 font-semibold">ligas monitoradas pela IA</span>.
              Os picks são gerados automaticamente antes de cada rodada e aparecem com o badge <span className="text-green-400 font-semibold">Pick IA</span> no jogo correspondente.
            </p>
          </div>
        </div>

        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : fixtures.length === 0 ? (
          <div className="card p-12 text-center border-dashed">
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
          <div className="grid gap-5 items-start lg:w-[420px] xl:w-[460px] lg:shrink-0">
            {grouped.map(({ key: league, league_id, logo, flag, country, games }) => {
              const isCopa = league_id === 1
              return (
              <div key={league} className={`card overflow-hidden ${isCopa ? 'border border-yellow-500/20' : ''}`}>

                {/* Cabeçalho da liga com logo + bandeira (clicável para recolher) */}
                <div
                  className={`px-4 py-3 border-b flex items-center gap-2.5 cursor-pointer select-none ${isCopa ? 'bg-yellow-950/40 border-yellow-700/30' : 'bg-surface-2/60 border-line'}`}
                  onClick={() => toggleCollapse(league)}
                >
                  {logo && (
                    <img src={logo} alt={league} width={24} height={24}
                      className="w-6 h-6 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')}
                      />
                  )}
                  <span className={`text-xs font-bold ${isCopa ? 'text-yellow-300' : 'text-ink-2'}`}>{league}</span>
                  {country && (
                    <span className={`text-xs font-normal ${isCopa ? 'text-yellow-700' : 'text-ink-4'}`}>{country}</span>
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
                        className={`flex items-center gap-3 px-3 sm:px-4 py-2.5 transition-colors cursor-pointer ${
                          f.has_pick ? 'border-l-2 border-green-500/40' : ''} ${
                          // Selecionado fica marcado: com o painel ao lado, sem
                          // isso não dá pra saber de qual jogo ele fala.
                          statsFixture?.fixture_id === f.fixture_id
                            ? 'bg-surface-2/60' : 'hover:bg-surface-2/30'}`}
                        onClick={() => canSeeStats ? setStatsFixture(f) : setLockPrompt(true)}
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

                        <div className="flex-1 min-w-0 space-y-1">
                          {([
                            ['home', f.home_team, f.home_team_id, f.home_goals, f.away_goals] as const,
                            ['away', f.away_team, f.away_team_id, f.away_goals, f.home_goals] as const,
                          ]).map(([lado, nome, id, gols, golsAdv]) => {
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
                                {(finished || live) && (
                                  <span className={`font-mono text-sm font-black tabular-nums shrink-0 w-5 text-right ${
                                    live ? 'text-green-400' : perdeu ? 'text-ink-4' : 'text-ink-1'}`}>
                                    {gols ?? 0}
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
          <div className="hidden lg:block flex-1 min-w-0">
            {statsFixture ? (
              <FixtureStatsModal
                key={statsFixture.fixture_id}
                fixture={statsFixture}
                onClose={() => setStatsFixture(null)}
                inline
              />
            ) : (
              <div className="card border-dashed p-12 text-center sticky top-4">
                <p className="text-sm text-ink-3">Clique em um jogo para ver a análise.</p>
                <p className="text-xs text-ink-4 mt-1.5">
                  Forma recente dos dois times, gols, escanteios e cartões.
                </p>
              </div>
            )}
          </div>
          </div>
        )}
      </motion.div>}
      </AnimatePresence>

      <AnimatePresence>
      {statsFixture && !isDesktop && (
        <FixtureStatsModal
          fixture={statsFixture}
          onClose={() => setStatsFixture(null)}
        />
      )}
      </AnimatePresence>

      {/* Lock modal para usuários free */}
      <AnimatePresence>
      {lockPrompt && (
        <motion.div
          variants={backdropFade} initial="hidden" animate="visible" exit="exit"
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4"
          onClick={() => setLockPrompt(false)}>
          <motion.div variants={dialogScale} className="bg-surface-0 border border-line rounded-lg p-8 max-w-sm w-full text-center shadow-2xl overflow-y-auto max-h-[92dvh]"
            onClick={e => e.stopPropagation()}>
            <div className="w-14 h-14 rounded-full bg-yellow-400/10 border border-yellow-400/20 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <h3 className="text-ink-1 font-bold text-lg mb-2">Análise exclusiva VIP</h3>
            <p className="text-ink-2 text-sm mb-6 leading-relaxed">
              Médias de gols, escanteios, cartões, histórico H2H e estatísticas completas por time. Disponível para assinantes VIP.
            </p>
            <Link to="/checkout"
              className="block bg-yellow-400 hover:bg-yellow-300 text-black font-black px-6 py-3 rounded-md transition-colors text-sm mb-3">
              Assinar VIP
            </Link>
            <button onClick={() => setLockPrompt(false)}
              className="text-ink-4 hover:text-ink-2 text-xs transition-colors">
              Fechar
            </button>
          </motion.div>
        </motion.div>
      )}
      </AnimatePresence>
    </PageShell>
  )
}
