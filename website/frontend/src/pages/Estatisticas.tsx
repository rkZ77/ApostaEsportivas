import { useEffect, useState, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock, ChevronDown } from 'lucide-react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/cn'
import PageShell from '../components/PageShell'
import { SpinnerBlock, EmptyState, ErrorState, Skeleton } from '../components/ui'
import { TeamLogo } from '../components/TeamLogo'
import Classificacao from '../components/jogos/Classificacao'
import LeituraDaLiga from '../components/ligas/LeituraDaLiga'
import LinhasDaLiga from '../components/ligas/LinhasDaLiga'
import { nomeDaLigaPt, paisDaLiga } from '../lib/paisDaLiga'
import { aoVivo, encerrado } from '../lib/aoVivo'
import { linkDoRaioX, type JogoParaRaioX } from '../lib/linkDoRaioX'

/*
 * ABA LIGAS DE /jogos (refeita em 15/10/2026, pedido do usuário: "melhorar a
 * aba de liga, mostrar números da liga, a leitura da IA e trazer as novidades
 * da aba Jogos").
 *
 * Antes era uma grade de 9 cartões iguais com ícone colorido no topo, o
 * ranking escondido atrás de um clique e o seletor de liga dentro de um menu
 * "Filtros". Agora:
 *   - as ligas ficam numa faixa à vista (como as datas da aba Jogos);
 *   - a liga abre em abas, como o Raio-X: Resumo, Tabela, Times, Árbitros,
 *     Resultados;
 *   - o Resumo traz os jogos de hoje da liga, a Leitura da IA, os números num
 *     placar só e a taxa por linha;
 *   - o ranking por time saiu do modal e virou a aba Times.
 * Nada aqui chama a API-Football: tudo é banco, e os jogos de hoje vêm do
 * mesmo /fixtures/today que a aba Jogos já busca (cache de 10 min no servidor).
 */

const LEAGUE_LOGO = (id: number) => `/api/proxy/league/${id}.png`
const TODAY = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
const CHAVE_LIGA = 'ligas:liga'

interface League { league_id: number; name: string; season: number; logo_url: string; ativa?: boolean }
interface Game {
  fixture_id: number; match_date: string
  home_team: string; away_team: string
  home_goals: number; away_goals: number; total_goals: number
  total_corners: number; total_yellow_cards: number; total_red_cards: number
  home_shots_on: number; away_shots_on: number; total_shots_on: number
  home_fouls: number; away_fouls: number; total_fouls: number
  total_saves: number | null
  referee: string | null
  home_team_id?: number; away_team_id?: number
}
interface Summary {
  total_games: number
  avg_goals: number; avg_corners: number
  avg_yellow_cards: number; avg_red_cards: number
  avg_fouls: number; avg_shots_on: number
  btts_pct: number; over25_pct: number
  /** null quando nenhum jogo da amostra tem o contador de defesas. */
  avg_saves: number | null
  jogos_com_defesa: number
  /** Folha cheia (finalização, passe, xG...): média só nos jogos com o dado. */
  folha?: Record<string, MediaComAmostra>
}
interface MediaComAmostra { media: number; jogos: number }
interface Arbitro {
  referee: string; jogos: number
  avg_yellow: number; avg_red: number; avg_fouls: number
  /** amarelo + 2x vermelho, a mesma conta que o motor usa. */
  avg_card_points: number
}
interface TeamRank {
  team_id: number; team_name: string; games: number
  avg_goals: number; avg_corners: number
  avg_yellows: number; avg_reds: number
  avg_fouls: number; avg_shots_on: number
  folha?: Record<string, MediaComAmostra>
}
export interface JogoDoDia extends JogoParaRaioX {
  elapsed?: number | null
  has_pick?: boolean
  pick_type_flag?: 'vip' | 'free' | null
  pick_market?: string | null
}

type Aba = 'resumo' | 'tabela' | 'times' | 'arbitros' | 'resultados'
type RankField = 'avg_goals' | 'avg_corners' | 'avg_yellows' | 'avg_reds' | 'avg_fouls' | 'avg_shots_on'
type Context = 'all' | 'home' | 'away'

/*
 * Os números da liga. `alto`/`baixo` são os cortes que a tela antiga já usava.
 * "Baixo" NÃO é vermelho: vermelho no site é só RED de pick, e liga de poucos
 * gols não é erro de ninguém.
 */
const NUMEROS: { chave: keyof Summary; rotulo: string; alto: number; baixo: number; pct?: boolean }[] = [
  { chave: 'avg_goals',        rotulo: 'Gols',          alto: 2.5, baixo: 1.5 },
  { chave: 'avg_corners',      rotulo: 'Escanteios',    alto: 10,  baixo: 7 },
  { chave: 'avg_yellow_cards', rotulo: 'Amarelos',      alto: 3.5, baixo: 2 },
  { chave: 'avg_red_cards',    rotulo: 'Vermelhos',     alto: 0.3, baixo: 0 },
  { chave: 'avg_fouls',        rotulo: 'Faltas',        alto: 25,  baixo: 18 },
  { chave: 'avg_shots_on',     rotulo: 'Chutes no gol', alto: 10,  baixo: 6 },
  { chave: 'btts_pct',         rotulo: 'Ambas marcam',  alto: 55,  baixo: 35, pct: true },
  { chave: 'over25_pct',       rotulo: 'Mais de 2,5',   alto: 55,  baixo: 35, pct: true },
]

/*
 * FOLHA CHEIA DA TEMPORADA (15/10/2026, pedido do usuário: "coloca tudo,
 * finalização, passe"). Média só nos jogos com o dado (xG e passe faltam em
 * parte das ligas); abaixo de 10 jogos a média não se sustenta e não aparece.
 */
const MIN_JOGOS_FOLHA = 10
const FOLHA_DA_LIGA: { chave: string; rotulo: string; pct?: boolean }[] = [
  { chave: 'chutes',            rotulo: 'Finalizações' },
  { chave: 'chutes_fora',       rotulo: 'Pra fora' },
  { chave: 'chutes_bloqueados', rotulo: 'Bloqueadas' },
  { chave: 'chutes_na_area',    rotulo: 'Dentro da área' },
  { chave: 'chutes_de_fora',    rotulo: 'De fora da área' },
  { chave: 'xg',                rotulo: 'Gols esperados (xG)' },
  { chave: 'impedimentos',      rotulo: 'Impedimentos' },
  { chave: 'passes',            rotulo: 'Passes' },
  { chave: 'passes_certos',     rotulo: 'Passes certos', pct: true },
  // Da folha dos jogadores, somada por time (estatisticas_de_jogadores.py).
  { chave: 'passes_decisivos',  rotulo: 'Passes decisivos' },
  { chave: 'desarmes',          rotulo: 'Desarmes' },
  { chave: 'interceptacoes',    rotulo: 'Interceptações' },
  { chave: 'duelos_ganhos',     rotulo: 'Duelos ganhos' },
  { chave: 'dribles_certos',    rotulo: 'Dribles certos' },
]

/* O ranking: os números de sempre e os da folha cheia. `valor` devolve null
   quando o time não tem o dado, e ele sai da lista daquele número. */
interface Ranking { id: string; rotulo: string; pct?: boolean; valor: (t: TeamRank) => number | null }
const doTime = (campo: RankField) => (t: TeamRank) => t[campo] ?? null
const daFolha = (chave: string) => (t: TeamRank) => {
  const f = t.folha?.[chave]
  return f && f.jogos >= 3 ? f.media : null
}
const RANKINGS: Ranking[] = [
  { id: 'gols',          rotulo: 'Gols',           valor: doTime('avg_goals') },
  { id: 'chutes',        rotulo: 'Finalizações',   valor: daFolha('chutes') },
  { id: 'no_gol',        rotulo: 'Chutes no gol',  valor: doTime('avg_shots_on') },
  { id: 'na_area',       rotulo: 'Dentro da área', valor: daFolha('chutes_na_area') },
  { id: 'xg',            rotulo: 'xG',             valor: daFolha('xg') },
  { id: 'escanteios',    rotulo: 'Escanteios',     valor: doTime('avg_corners') },
  { id: 'posse',         rotulo: 'Posse',          valor: daFolha('posse'), pct: true },
  { id: 'passes',        rotulo: 'Passes',         valor: daFolha('passes') },
  { id: 'passes_certos', rotulo: 'Passes certos',  valor: daFolha('passes_certos'), pct: true },
  { id: 'decisivos',     rotulo: 'Passes decisivos', valor: daFolha('passes_decisivos') },
  { id: 'dribles',       rotulo: 'Dribles certos', valor: daFolha('dribles_certos') },
  { id: 'duelos',        rotulo: 'Duelos ganhos',  valor: daFolha('duelos_ganhos') },
  { id: 'desarmes',      rotulo: 'Desarmes',       valor: daFolha('desarmes') },
  { id: 'intercept',     rotulo: 'Interceptações', valor: daFolha('interceptacoes') },
  { id: 'amarelos',      rotulo: 'Amarelos',       valor: doTime('avg_yellows') },
  { id: 'vermelhos',     rotulo: 'Vermelhos',      valor: doTime('avg_reds') },
  { id: 'faltas',        rotulo: 'Faltas',         valor: doTime('avg_fouls') },
  { id: 'impedimentos',  rotulo: 'Impedimentos',   valor: daFolha('impedimentos') },
  { id: 'defesas',       rotulo: 'Defesas',        valor: daFolha('defesas') },
]

const RECORTES = [
  { valor: 10, rotulo: '10' },
  { valor: 20, rotulo: '20' },
  { valor: 0,  rotulo: 'Todos' },
]

/** Jogos por bloco na lista de resultados. */
const PAGINA = 20

function nivel(v: number, alto: number, baixo: number): { rotulo: string; cls: string; ponto: string } {
  if (v >= alto) return { rotulo: 'Alto', cls: 'text-accent-ink', ponto: 'bg-accent' }
  if (v <= baixo) return { rotulo: 'Baixo', cls: 'text-sky-300', ponto: 'bg-sky-400' }
  return { rotulo: 'Médio', cls: 'text-ink-3', ponto: 'bg-ink-4' }
}

const decimal = (v: number, casas = 2) =>
  v.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: casas })

/*
 * DD/MM a partir do texto cru, sem `new Date`: `match_date` já está no fuso de
 * Brasília e qualquer parse reintroduz fuso (era "Invalid Date" em toda linha).
 */
function diaMes(valor?: string | null): string {
  if (!valor) return ''
  const [ano, mes, dia] = valor.slice(0, 10).split('-')
  return dia && mes && ano ? `${dia}/${mes}` : ''
}

function lerLigaGuardada(): number | null {
  try { const v = Number(localStorage.getItem(CHAVE_LIGA)); return v > 0 ? v : null } catch { return null }
}
function guardarLiga(id: number) {
  try { localStorage.setItem(CHAVE_LIGA, String(id)) } catch { /* aba anônima */ }
}

export function EstatisticasContent({ onAbrirJogo }: {
  /** Quem hospeda a aba decide como abrir o Raio-X. Sem isso, navega. */
  onAbrirJogo?: (f: JogoDoDia) => void
} = {}) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isVip = user?.plan === 'vip' || user?.plan === 'admin' || user?.plan === 'trial'

  const [leagues, setLeagues]       = useState<League[]>([])
  const [leagueId, setLeagueId]     = useState<number | null>(null)
  const [leaguesLoading, setLeaguesLoading] = useState(true)
  const [aba, setAba]               = useState<Aba>('resumo')
  const [limit, setLimit]           = useState(0)
  const [games, setGames]           = useState<Game[]>([])
  const [summary, setSummary]       = useState<Summary | null>(null)
  const [loading, setLoading]       = useState(false)
  const [erro, setErro]             = useState(false)
  /** Mudar o valor reexecuta a carga ("tentar de novo"). */
  const [tentativa, setTentativa]   = useState(0)
  const [ranking, setRanking]       = useState<TeamRank[] | null>(null)
  const [context, setContext]       = useState<Context>('all')
  const [campo, setCampo]           = useState('gols')
  const [arbitros, setArbitros]     = useState<Arbitro[] | null>(null)
  const [hoje, setHoje]             = useState<JogoDoDia[]>([])
  const [visiveis, setVisiveis]     = useState(PAGINA)

  useEffect(() => {
    if (!isVip) return
    api.get('/public/leagues')
      .then(r => {
        const ls: League[] = r.data
        setLeagues(ls)
        /* Abre na última liga vista; senão numa EM ANDAMENTO, não na primeira
           da lista (a Copa do Mundo é o id 1 e acabou em agosto de 2026). */
        const guardada = lerLigaGuardada()
        const inicial = ls.find(l => l.league_id === guardada) ?? ls.find(l => l.ativa !== false) ?? ls[0]
        if (inicial) setLeagueId(inicial.league_id)
      })
      .catch(() => {})
      .finally(() => setLeaguesLoading(false))
  }, [isVip])

  /* Jogos de hoje: o mesmo pedido da aba Jogos, cacheado no servidor. Um só
     pra todas as ligas · trocar de liga só refiltra. */
  useEffect(() => {
    if (!isVip) return
    api.get('/fixtures/today', { params: { date: TODAY } })
      .then(r => setHoje(r.data ?? []))
      .catch(() => setHoje([]))
  }, [isVip])

  useEffect(() => {
    if (!leagueId || !isVip) return
    setLoading(true)
    setErro(false)
    api.get('/suggestions/liga/tendencias', { params: { league_id: leagueId, limit: limit === 0 ? 500 : limit } })
      .then(r => { setGames(r.data.games ?? []); setSummary(r.data.summary ?? null) })
      .catch(() => { setGames([]); setSummary(null); setErro(true) })
      .finally(() => setLoading(false))
  }, [leagueId, limit, isVip, tentativa])

  // Árbitros e ranking só quando a aba deles abre: quem só olha o Resumo não
  // paga as duas consultas.
  useEffect(() => {
    if (!leagueId || !isVip || aba !== 'arbitros') return
    setArbitros(null)
    api.get('/suggestions/liga/arbitros', { params: { league_id: leagueId } })
      .then(r => setArbitros(r.data?.arbitros ?? []))
      .catch(() => setArbitros([]))
  }, [leagueId, isVip, aba])

  useEffect(() => {
    if (!leagueId || !isVip || aba !== 'times') return
    setRanking(null)
    api.get('/suggestions/liga/ranking', { params: { league_id: leagueId, context } })
      .then(r => setRanking(r.data ?? []))
      .catch(() => setRanking([]))
  }, [leagueId, context, isVip, aba])

  useEffect(() => { setVisiveis(PAGINA) }, [leagueId, limit])

  const liga = leagues.find(l => l.league_id === leagueId)
  const hojeDaLiga = useMemo(() => hoje.filter(f => f.league_id === leagueId), [hoje, leagueId])

  function escolherLiga(id: number) {
    setLeagueId(id)
    guardarLiga(id)
  }

  function abrir(f: JogoDoDia) {
    if (onAbrirJogo) onAbrirJogo(f)
    else navigate(linkDoRaioX(f))
  }

  if (!isVip) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <div className="w-14 h-14 rounded-full bg-surface-1 flex items-center justify-center">
          <Lock className="w-6 h-6 text-ink-3" />
        </div>
        <h2 className="text-ink-1 font-bold text-lg">Recurso para assinantes</h2>
        <p className="text-ink-3 text-sm text-center max-w-xs">
          Os números de cada liga são exclusivos para assinantes.
        </p>
        <a href="/planos" className="btn-primary px-6 py-2 text-sm">Ver planos</a>
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-[1200px]">
      {leaguesLoading ? (
        <div className="flex gap-2">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-11 w-36 shrink-0" />)}
        </div>
      ) : (
        <SeletorDeLiga ligas={leagues} valor={leagueId} hoje={hoje} onChange={escolherLiga} />
      )}

      {liga && (
        <div className="flex items-center gap-3 pt-1">
          <img src={LEAGUE_LOGO(liga.league_id)} alt="" width={44} height={44}
            className="w-11 h-11 object-contain shrink-0"
            onError={e => (e.currentTarget.style.display = 'none')} />
          <div className="min-w-0">
            <h2 className="text-2xl leading-tight text-ink-1 truncate">{nomeDaLigaPt(liga.league_id, liga.name)}</h2>
            <p className="text-xs text-ink-3 mt-0.5">
              {[paisDaLiga(liga.league_id)?.pais, `Temporada ${liga.season}`,
                liga.ativa === false ? 'encerrada' : null].filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>
      )}

      {/* As cinco abas À VISTA no celular (o público é mais celular): numa
          faixa que rola de lado, "Resultados" ficava fora da tela, e aba
          escondida é aba que ninguém descobre · mesma solução do Raio-X. */}
      <div role="tablist" className="grid grid-cols-5 sm:flex border-b border-line">
        {([
          ['resumo', 'Resumo'], ['tabela', 'Tabela'], ['times', 'Times'],
          ['arbitros', 'Árbitros'], ['resultados', 'Resultados'],
        ] as [Aba, string][]).map(([k, rotulo]) => (
          <button key={k} type="button" role="tab" aria-selected={aba === k} onClick={() => setAba(k)}
            className={cn('relative h-11 sm:px-5 text-xs min-[400px]:text-[13px] sm:text-sm font-bold transition-colors whitespace-nowrap',
              aba === k ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2')}>
            {rotulo}
            {k === 'resumo' && hojeDaLiga.some(f => aoVivo(f.status ?? '')) && (
              <span className="absolute top-2 right-1 w-1.5 h-1.5 rounded-full bg-accent animate-pulse" aria-label="jogo ao vivo" />
            )}
            {aba === k && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      {aba === 'tabela' && leagueId && <Classificacao leagueId={leagueId} />}

      {aba === 'times' && (
        <RankingDosTimes ranking={ranking} campo={campo} onCampo={setCampo}
          context={context} onContext={setContext} />
      )}

      {aba === 'arbitros' && <ArbitrosDaLiga arbitros={arbitros} />}

      {(aba === 'resumo' || aba === 'resultados') && (
        loading ? <SpinnerBlock className="py-20" /> : erro ? (
          <div className="card">
            <ErrorState title="Não deu pra carregar os números desta liga" onRetry={() => setTentativa(t => t + 1)} />
          </div>
        ) : !summary ? (
          <div className="card">
            <EmptyState title="Sem jogos desta liga ainda"
              description="Assim que houver jogos encerrados nesta temporada, os números aparecem aqui." />
          </div>
        ) : aba === 'resumo' ? (
          <div className="space-y-4">
            {hojeDaLiga.length > 0 && <HojeNaLiga jogos={hojeDaLiga} onAbrir={abrir} />}
            {leagueId && <LeituraDaLiga leagueId={leagueId} />}
            <PlacarDaLiga summary={summary} limit={limit} onLimit={setLimit} />
            <LinhasDaLiga jogos={games} />
          </div>
        ) : (
          <Resultados games={games} visiveis={visiveis} onMais={() => setVisiveis(v => v + PAGINA)} />
        )
      )}
    </div>
  )
}

/* ─────────────────────────── Seletor de liga ─────────────────────────── */

/*
 * As ligas à vista numa faixa que rola de lado, como as datas da aba Jogos.
 * Antes ficavam num menu "Filtros": trocar de liga custava dois toques e não
 * se via qual estava aberta. A liga com jogo hoje ganha a contagem; as
 * encerradas vão pro fim, apagadas (o histórico serve, mas não é a porta).
 */
function SeletorDeLiga({ ligas, valor, hoje, onChange }: {
  ligas: League[]; valor: number | null; hoje: JogoDoDia[]; onChange: (id: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const ordenadas = useMemo(() => [
    ...ligas.filter(l => l.ativa !== false),
    ...ligas.filter(l => l.ativa === false),
  ], [ligas])
  const jogosHoje = useMemo(() => {
    const n = new Map<number, number>()
    for (const f of hoje) n.set(f.league_id, (n.get(f.league_id) ?? 0) + 1)
    return n
  }, [hoje])

  // A liga aberta sempre à vista, mesmo quando é a 15ª da faixa.
  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>('[aria-pressed="true"]')
    el?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [valor])

  return (
    <div ref={ref} className="-mx-4 px-4 sm:mx-0 sm:px-0 flex gap-2 overflow-x-auto scrollbar-none pb-1">
      {ordenadas.map(l => {
        const ativa = l.league_id === valor
        const n = jogosHoje.get(l.league_id)
        return (
          <button key={l.league_id} type="button" aria-pressed={ativa}
            onClick={() => onChange(l.league_id)}
            className={cn(
              'h-11 shrink-0 flex items-center gap-2 pl-2.5 pr-3.5 rounded-full border text-sm font-semibold transition-colors',
              ativa ? 'bg-surface-3 border-line-strong text-ink-1' : 'bg-surface-1 border-line text-ink-2 hover:text-ink-1',
              l.ativa === false && !ativa && 'opacity-60',
            )}>
            <img src={LEAGUE_LOGO(l.league_id)} alt="" width={20} height={20} loading="lazy"
              className="w-5 h-5 object-contain" onError={e => (e.currentTarget.style.visibility = 'hidden')} />
            <span className="whitespace-nowrap">{nomeDaLigaPt(l.league_id, l.name)}</span>
            {n ? <span className="font-mono text-[11px] text-accent-ink">{n} hoje</span> : null}
          </button>
        )
      })}
    </div>
  )
}

/* ─────────────────────────── Hoje na liga ─────────────────────────── */

function HojeNaLiga({ jogos, onAbrir }: { jogos: JogoDoDia[]; onAbrir: (f: JogoDoDia) => void }) {
  return (
    <section className="card overflow-hidden">
      <div className="px-4 py-2.5 border-b border-line flex items-center justify-between">
        <h3 className="text-sm font-bold text-ink-1">Hoje na liga</h3>
        <span className="text-[11px] text-ink-3">Toque pra abrir o Raio-X</span>
      </div>
      <ul className="divide-y divide-line/60">
        {jogos.map(f => {
          const live = aoVivo(f.status ?? '')
          const fim = encerrado(f.status ?? '')
          const hora = f.match_datetime
            ? new Date(f.match_datetime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
            : '--:--'
          return (
            <li key={f.fixture_id}>
              <button type="button" onClick={() => onAbrir(f)}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/40 transition-colors">
                <span className={cn('w-12 shrink-0 font-mono text-[13px] font-bold',
                  live ? 'text-accent-ink' : fim ? 'text-ink-4' : 'text-ink-2')}>
                  {live ? (f.elapsed ? `${f.elapsed}'` : 'Ao vivo') : fim ? 'Fim' : hora}
                </span>
                <span className="flex-1 min-w-0 space-y-0.5">
                  {([[f.home_team, f.home_team_id, f.home_goals], [f.away_team, f.away_team_id, f.away_goals]] as const)
                    .map(([nome, id, gols], i) => (
                      <span key={i} className="flex items-center gap-2">
                        <TeamLogo id={id} name={nome} size={18} />
                        <span className="text-[13px] font-semibold text-ink-1 truncate flex-1">{nome}</span>
                        {(live || fim) && (
                          <span className={cn('font-mono font-black text-base w-5 text-right', live ? 'text-accent-ink' : 'text-ink-1')}>
                            {gols ?? 0}
                          </span>
                        )}
                      </span>
                    ))}
                </span>
                {f.has_pick && (
                  <span className={cn('shrink-0 text-[10px] font-black px-1.5 py-0.5 rounded border',
                    f.pick_type_flag === 'vip'
                      ? 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
                      : 'text-accent-ink bg-green-500/10 border-green-500/20')}>
                    Pick IA
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/* ─────────────────────────── Placar de números ─────────────────────────── */

/*
 * Os números da liga num placar só, como a faixa de estatística de uma
 * transmissão: número grande em fonte de placar, rótulo curto, e o nível num
 * ponto + palavra. Sem ícone colorido em cada um (era a "cara de template").
 */
function PlacarDaLiga({ summary, limit, onLimit }: {
  summary: Summary; limit: number; onLimit: (n: number) => void
}) {
  const celulas = NUMEROS.map(n => ({ ...n, valor: Number(summary[n.chave] ?? 0) }))
  // Defesas só com amostra: o dado tem muito buraco na API e média de 3 jogos engana.
  const defesas = summary.avg_saves != null && summary.jogos_com_defesa >= 10 ? summary.avg_saves : null

  return (
    <section className="card overflow-hidden">
      <div className="px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="mr-auto">
          <h3 className="text-sm font-bold text-ink-1">Média por jogo</h3>
          <p className="text-[11px] text-ink-3">
            {limit === 0 ? `Todos os ${summary.total_games} jogos analisados` : `Últimos ${summary.total_games} jogos`}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-ink-3">Últimos</span>
          <div className="flex rounded-lg border border-line p-0.5 bg-surface-1">
            {RECORTES.map(r => (
              <button key={r.valor} type="button" aria-pressed={limit === r.valor} onClick={() => onLimit(r.valor)}
                className={cn('h-10 min-w-[48px] px-3 rounded-md text-sm font-bold transition-colors',
                  limit === r.valor ? 'bg-surface-3 text-ink-1' : 'text-ink-3 hover:text-ink-2')}>
                {r.rotulo}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 min-[420px]:grid-cols-4 lg:grid-cols-8 gap-px bg-line/60 border-t border-line/60">
        {celulas.map(c => {
          const nv = nivel(c.valor, c.alto, c.baixo)
          return (
            <div key={c.chave} className="bg-surface-1 px-3 py-3">
              <div className="text-[11px] text-ink-3 leading-tight">{c.rotulo}</div>
              <div className="font-mono font-black text-3xl leading-none text-ink-1 mt-1.5">
                {c.pct ? `${Math.round(c.valor)}%` : decimal(c.valor)}
              </div>
              <div className={cn('mt-1.5 flex items-center gap-1 text-[11px] font-semibold', nv.cls)}>
                <span className={cn('w-1.5 h-1.5 rounded-full', nv.ponto)} aria-hidden />
                {nv.rotulo}
              </div>
            </div>
          )
        })}
      </div>
      {(() => {
        /* Finalizações e passes: média só nos jogos com o dado, e a amostra
           aparece quando não é a liga inteira (xG fora das ligas grandes). */
        const folha = FOLHA_DA_LIGA
          .map(f => ({ ...f, m: summary.folha?.[f.chave] }))
          .filter((f): f is typeof f & { m: MediaComAmostra } => !!f.m && f.m.jogos >= MIN_JOGOS_FOLHA)
          .map(f => ({ ...f, valor: f.m.media, jogos: f.m.jogos }))
        if (defesas != null) folha.push({ chave: 'defesas', rotulo: 'Defesas do goleiro', valor: defesas,
          jogos: summary.jogos_com_defesa, m: { media: defesas, jogos: summary.jogos_com_defesa } })
        if (!folha.length) return null
        return (
          <>
            <div className="px-4 pt-3 pb-2 border-t border-line/60">
              <h4 className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Finalizações, passes e duelos</h4>
            </div>
            <div className="grid grid-cols-2 min-[420px]:grid-cols-4 lg:grid-cols-5 gap-px bg-line/60 border-t border-line/60">
              {folha.map(f => (
                <div key={f.chave} className="bg-surface-1 px-3 py-3">
                  <div className="text-[11px] text-ink-3 leading-tight">{f.rotulo}</div>
                  <div className="font-mono font-black text-3xl leading-none text-ink-1 mt-1.5">
                    {f.pct ? `${Math.round(f.valor)}%` : decimal(f.valor)}
                  </div>
                  {f.jogos < summary.total_games && (
                    <div className="mt-1.5 text-[11px] text-ink-4">em {f.jogos} jogos</div>
                  )}
                </div>
              ))}
            </div>
          </>
        )
      })()}
    </section>
  )
}

/* ─────────────────────────── Times ─────────────────────────── */

/*
 * O ranking por time, que antes abria num modal a partir de um cartão. Aqui é
 * a aba inteira: escolhe o número e o mando, e a lista vem com uma barra
 * proporcional ao maior, pra ver a distância entre o 1º e o 10º sem fazer conta.
 */
function RankingDosTimes({ ranking, campo, onCampo, context, onContext }: {
  ranking: TeamRank[] | null
  campo: string; onCampo: (c: string) => void
  context: Context; onContext: (c: Context) => void
}) {
  // Só os números que algum time da liga tem (xG e passe faltam em parte delas).
  const opcoes = useMemo(
    () => RANKINGS.filter(r => ranking == null || ranking.some(t => r.valor(t) != null)),
    [ranking])
  const atual = opcoes.find(r => r.id === campo) ?? RANKINGS[0]
  const ordenado = useMemo(() => (ranking ?? [])
    .map(t => ({ t, v: atual.valor(t) }))
    .filter((x): x is { t: TeamRank; v: number } => x.v != null)
    .sort((a, b) => b.v - a.v), [ranking, atual])
  const maior = Math.max(0.01, ...ordenado.map(x => x.v))

  return (
    <section className="space-y-3">
      <div className="flex gap-2 overflow-x-auto scrollbar-none -mx-4 px-4 sm:mx-0 sm:px-0">
        {opcoes.map(r => (
          <button key={r.id} type="button" aria-pressed={atual.id === r.id} onClick={() => onCampo(r.id)}
            className={cn('h-10 px-4 shrink-0 rounded-full border text-sm font-semibold transition-colors',
              atual.id === r.id ? 'bg-accent text-on-fill border-accent' : 'bg-surface-1 text-ink-2 border-line')}>
            {r.rotulo}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-3 rounded-lg border border-line p-0.5 bg-surface-1 max-w-sm">
        {([['all', 'Todos'], ['home', 'Em casa'], ['away', 'Fora']] as [Context, string][]).map(([k, r]) => (
          <button key={k} type="button" aria-pressed={context === k} onClick={() => onContext(k)}
            className={cn('h-10 rounded-md text-sm font-bold transition-colors', context === k ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
            {r}
          </button>
        ))}
      </div>

      <div className="card overflow-hidden">
        <div className="px-4 py-2.5 border-b border-line text-[11px] text-ink-3">
          Média por jogo do próprio time{context === 'home' ? ', só jogando em casa' : context === 'away' ? ', só jogando fora' : ''}
        </div>
        {ranking == null ? (
          <div className="p-4 space-y-2">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
        ) : ordenado.length === 0 ? (
          <div className="p-8 text-center text-ink-3 text-sm">Sem dados de ranking ainda.</div>
        ) : (
          <ol className="divide-y divide-line/60">
            {ordenado.map(({ t, v }, i) => {
              return (
                <li key={t.team_id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className={cn('w-6 shrink-0 text-right font-mono font-black text-lg leading-none',
                    i < 3 ? 'text-ink-1' : 'text-ink-4')}>{i + 1}</span>
                  <TeamLogo id={t.team_id} name={t.team_name} size={22} />
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm font-semibold text-ink-1 truncate">{t.team_name}</span>
                    <span className="mt-1 block h-1 rounded-full bg-surface-3 overflow-hidden max-w-[240px]">
                      <span className="block h-full rounded-full bg-accent" style={{ width: `${(v / maior) * 100}%` }} />
                    </span>
                  </span>
                  <span className="font-mono text-[11px] text-ink-4 shrink-0">{t.games}j</span>
                  <span className="w-14 text-right font-mono font-black text-xl leading-none text-ink-1 shrink-0">
                    {atual.pct ? `${Math.round(v)}%` : decimal(v)}
                  </span>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </section>
  )
}

/* ─────────────────────────── Árbitros ─────────────────────────── */

/*
 * Amarelo e vermelho separados de propósito: o motor pontua vermelho como 2,
 * então 3,0 amarelos + 0,6 vermelhos pesa igual a 4,2 amarelos sem vermelho, e
 * os dois dão jogos bem diferentes. A coluna de pontos é a que o motor usa.
 */
function ArbitrosDaLiga({ arbitros }: { arbitros: Arbitro[] | null }) {
  if (arbitros == null) {
    return <div className="card p-4 space-y-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
  }
  if (!arbitros.length) {
    return <div className="card"><EmptyState title="Sem árbitros com jogos suficientes nesta liga" compact /></div>
  }
  return (
    <section className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-line">
        <h3 className="text-sm font-bold text-ink-1">Cartões por árbitro</h3>
        <p className="text-[11px] text-ink-3 mt-0.5">Média por jogo apitado nesta competição, do mais rigoroso pro menos.</p>
      </div>
      <div className="flex items-center gap-2 px-4 py-2 text-[11px] font-semibold text-ink-3 border-b border-line/60">
        <span className="flex-1">Árbitro</span>
        <span className="w-10 text-center">Jogos</span>
        <span className="w-12 text-center">Amar.</span>
        <span className="w-12 text-center">Verm.</span>
        <span className="w-12 text-center">Pontos</span>
      </div>
      <ul className="divide-y divide-line/60">
        {arbitros.map(a => (
          <li key={a.referee} className="flex items-center gap-2 px-4 py-2.5">
            <span className="flex-1 min-w-0 text-sm text-ink-1 font-semibold truncate">
              {a.referee.replace(/,\s*[A-Za-z ]+$/, '')}
            </span>
            <span className="w-10 text-center font-mono text-xs text-ink-3">{a.jogos}</span>
            <span className="w-12 text-center font-mono text-xs text-ink-2">{decimal(Number(a.avg_yellow), 1)}</span>
            <span className="w-12 text-center font-mono text-xs text-ink-2">{decimal(Number(a.avg_red), 2)}</span>
            <span className={cn('w-12 text-center font-mono font-black text-lg leading-none',
              Number(a.avg_card_points) >= 5 ? 'text-accent-ink' : 'text-ink-1')}>
              {decimal(Number(a.avg_card_points), 1)}
            </span>
          </li>
        ))}
      </ul>
      <p className="px-4 py-2.5 text-[11px] text-ink-4 border-t border-line/60 leading-relaxed">
        Pontos = amarelo + 2 x vermelho, a mesma conta que o motor usa. Árbitro com menos de 2 jogos na liga fica de fora.
      </p>
    </section>
  )
}

/* ─────────────────────────── Resultados ─────────────────────────── */

function Resultados({ games, visiveis, onMais }: { games: Game[]; visiveis: number; onMais: () => void }) {
  return (
    <section className="card overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 text-[11px] font-semibold text-ink-3 border-b border-line">
        <span className="flex-1">Jogo</span>
        <span className="w-8 text-center">Esc.</span>
        <span className="w-8 text-center">Cart.</span>
        <span className="hidden sm:block w-10 text-center">Faltas</span>
      </div>
      <ul className="divide-y divide-line/60">
        {games.slice(0, visiveis).map(g => {
          const casaVenceu = g.home_goals > g.away_goals, foraVenceu = g.away_goals > g.home_goals
          return (
            <li key={g.fixture_id} className="flex items-center gap-2 px-4 py-2.5">
              <span className="w-11 shrink-0 font-mono text-[11px] text-ink-4">{diaMes(g.match_date)}</span>
              <span className="flex-1 min-w-0 space-y-0.5">
                {([[g.home_team, g.home_team_id, g.home_goals, foraVenceu], [g.away_team, g.away_team_id, g.away_goals, casaVenceu]] as const)
                  .map(([nome, id, gols, perdeu], i) => (
                    <span key={i} className="flex items-center gap-2">
                      <TeamLogo id={id} name={nome} size={16} />
                      <span className={cn('text-[13px] truncate flex-1', perdeu ? 'text-ink-3' : 'text-ink-1 font-semibold')}>{nome}</span>
                      <span className={cn('font-mono font-black text-base w-4 text-right', perdeu ? 'text-ink-3' : 'text-ink-1')}>{gols ?? '-'}</span>
                    </span>
                  ))}
              </span>
              <span className="w-8 text-center font-mono text-xs text-ink-2">{g.total_corners ?? '-'}</span>
              <span className="w-8 flex flex-col items-center gap-0.5 font-mono text-xs text-ink-2">
                {g.total_yellow_cards ?? '-'}
                {(g.total_red_cards || 0) > 0 && (
                  <span className="flex items-center gap-0.5 text-[10px] text-ink-3" title={`${g.total_red_cards} vermelho(s)`}>
                    <span className="w-1.5 h-2 rounded-[1px] bg-red-500" aria-hidden />{g.total_red_cards}
                  </span>
                )}
              </span>
              <span className="hidden sm:block w-10 text-center font-mono text-xs text-ink-3">{g.total_fouls ?? '-'}</span>
            </li>
          )
        })}
      </ul>
      {games.length > visiveis && (
        <button type="button" onClick={onMais}
          className="w-full h-12 text-sm font-semibold text-ink-2 hover:text-ink-1 border-t border-line/60 flex items-center justify-center gap-1.5">
          <ChevronDown className="w-4 h-4" />
          Ver mais {Math.min(PAGINA, games.length - visiveis)} de {games.length - visiveis}
        </button>
      )}
    </section>
  )
}

export default function Estatisticas() {
  return (
    <PageShell
      title="Ligas"
      description="Números, tabela, times e árbitros de cada liga que a IA analisa."
      noindex
      width="full"
      bar={{ title: 'Ligas', sub: 'Números, tabela, times e árbitros de cada liga' }}
    >
      <EstatisticasContent />
    </PageShell>
  )
}
