import { useEffect, useState, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { Trophy } from 'lucide-react'
import api from '../services/api'
import { rotuloDoMercado } from '../utils/marketTranslate'
import { Helmet } from 'react-helmet-async'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { winRate as calcWinRate, fmtUnits, STAKE_LABEL_PADRAO } from '../utils/format'
import { TeamLogo, LeagueLogo } from '../components/TeamLogo'
import { useAuth } from '../context/AuthContext'
import PageShell from '../components/PageShell'
import { nomeDoMes } from '../lib/periodo'
import CaminhosDaIA from '../components/CaminhosDaIA'
import { PAGE_WIDTH } from '../lib/pageWidth'
import { Button, SelectMenu, Spinner } from '../components/ui'
import SuggestionDetail from '../components/SuggestionDetail'
import PublicNav from '../components/PublicNav'
import DailyGreensChart from '../components/DailyGreensChart'
import PipelineProfitChart from '../components/PipelineProfitChart'
import LucroBarChart from '../components/LucroBarChart'
import { sinalizarNavegacao } from '../services/progressBus'

const GAMES_PAGE_SIZE = 10

interface Summary {
  total: number; greens: number; reds: number; push: number
  profit: number; stake_total: number; roi: number
}
interface DayResult { match_date: string; total: number; greens: number; reds: number; profit: number }
interface LeagueResult {
  league_id: number | null; league_name: string
  total: number; greens: number; reds: number; profit: number; stake_total: number
}
interface RecentTip {
  match_date: string
  /** Horário do jogo · só existe enquanto a partida está em `fixtures`. */
  match_datetime?: string | null
  home_team_name: string; away_team_name?: string
  home_team_id?: number; away_team_id?: number
  market?: string; line?: string; odd: number
  result: string; profit: number; source: string
  league_id?: number | null; league_name?: string
}
interface SourceResult {
  source: string
  total: number; greens: number; reds: number
  profit: number; stake_total: number
  win_rate: number; roi: number
}
/* Uma linha por dia E por pipeline. O backend ja manda a contagem completa
   (public.py::by_source_day); o front so' declarava `profit` porque a curva
   por produto era a unica coisa que lia isto. A aba Fechamento agrega o resto
   por mes sem nenhuma consulta nova. */
interface SourceDay {
  match_date: string; source: string; profit: number
  total?: number; greens?: number; reds?: number; stake_total?: number
}

interface PublicData {
  /** Legenda do plano de stake · montada em backend/stake_plan.py. */
  stake_label?: string
  /** Quebra por pipeline · uma consulta só, fora do caminho slim. */
  by_source?: SourceResult[]
  by_source_day?: SourceDay[]
  available_months: string[]
  summary: Summary
  by_day: DayResult[]
  by_league: LeagueResult[]
  recent: RecentTip[]
  recent_total: number
}

/* Os pipelines do placar. Faltas e defesas ficavam de fora daqui mesmo o
   backend ja incluindo os dois no agregado: o filtro nao os oferecia e o badge
   da lista caia no valor cru ("faltas" em vez de "Faltas"). Player Stats
   entrou em 27/08 pelo mesmo caminho, e `goleiros` fica: o motor parou de
   escrever nela, mas o passado dela continua no placar publico. */
const SRC_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multiplas: 'Múlt.', alavancagem: 'Alav.',
  faltas: 'Faltas', goleiros: 'Defesas', player_stats: 'Jogador',
  boost: 'Boost', live: 'Ao Vivo',
}
const SOURCE_LABELS: Record<string, string> = {
  all: 'Todos', vip: 'VIP', free: 'Free', multiplas: 'Múltiplas',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
  player_stats: 'Jogadores', boost: 'Pick Boost', live: 'Ao Vivo',
}

/*
 * Faixa de indicadores no topo de cada aba.
 *
 * Antes só a aba Resumo tinha números: "Por Liga" abria direto numa lista de 20
 * linhas, "Por Jogo" numa lista de picks e "Por Mês" numa tabela, todas sem
 * nenhuma leitura de conjunto. Quem entrava numa dessas abas tinha que somar de
 * cabeça para responder "e aí, foi bom?".
 *
 * Cada aba calcula a sua a partir dos dados que já baixou · nenhuma consulta
 * nova, nenhum número que não venha do backend.
 */
function AbaStats({ tiles }: {
  tiles: { label: string; value: string; tone?: 'green' | 'red' | 'default' }[]
}) {
  if (tiles.length === 0) return null
  const cor = { green: 'text-green-400', red: 'text-red-400', default: 'text-ink-1' }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
      {tiles.map(t => (
        <div key={t.label} className="stat-tile">
          <div className={`stat-value tabular-nums ${cor[t.tone ?? 'default']}`}>{t.value}</div>
          <div className="stat-label">{t.label}</div>
        </div>
      ))}
    </div>
  )
}

/* ── Fechamento mensal da IA ───────────────────────────────────────────────
 *
 * O site ja tinha fechamento mensal do USUARIO (Banca > Fechamentos) e ja tinha
 * o placar da IA por liga, por jogo e por mes. O que faltava era cruzar as duas
 * coisas: fechar o mes DA IA e dizer qual PRODUTO puxou o resultado.
 *
 * "Produto", nao "motor": quem analisa e' a IA, e o motor e' peca de dentro. O
 * que a tela compara sao VIP, Free, Multiplas, Faltas, Ao Vivo -- que e' a
 * palavra que o resto da pagina ja usa ("Comparativo por produto").
 *
 * "Por Mes" soma tudo e responde quanto a IA acertou no mes; "Por Jogo" soma o
 * historico inteiro e responde quem da mais green desde sempre. Nenhuma das
 * duas responde "em agosto, qual produto foi o mais forte" -- e essa e' a
 * pergunta que decide onde o assinante coloca dinheiro no mes seguinte.
 *
 * Tudo sai de `by_source_day`, que a pagina ja baixou (public.py monta a linha
 * com total/greens/reds/profit/stake_total). Nenhuma consulta nova, nenhum
 * numero que o backend nao tenha mandado.
 */
interface FechamentoFonte {
  source: string
  total: number; greens: number; reds: number
  profit: number; stake_total: number
  win_rate: number; roi: number
}
interface FechamentoMes {
  mes: string
  fontes: FechamentoFonte[]
  total: number; greens: number; reds: number
  profit: number; stake_total: number
  win_rate: number; roi: number
  /** Produto que puxou o mes. Null quando o mes nao tem fonte elegivel. */
  campeao: FechamentoFonte | null
  /** O campeao saiu abaixo do piso de amostra e a tela precisa dizer isso. */
  amostraCurta: boolean
}

/* Piso de amostra pra eleger o produto do mes. Um pipeline com 1 green em 1 pick
   nao e' "o mais forte de agosto", e' sorte de calendario -- mesmo piso que a
   aba Por Liga e o card "Mais certeiro" ja usam. */
/* Rotulo do produto no fechamento.
 *
 * SOURCE_LABELS e' o mapa do FILTRO, e a chave dele e' o valor que a API
 * aceita em `?source=` ("multiplas"). `by_source_day.source` vem do UNION do
 * backend e usa o singular ("multipla"), entao o filtro nao servia de legenda:
 * a linha da multipla saia escrita "multipla", em minuscula e sem acento. */
const PRODUTO_LABELS: Record<string, string> = {
  ...SOURCE_LABELS, multipla: 'Múltiplas',
}
const rotuloProduto = (src: string) => PRODUTO_LABELS[src] ?? src

const PISO_AMOSTRA = 5

/* Rotulos de mes ja' capitalizados na fonte. A classe `capitalize` do Tailwind
   sobe a inicial de CADA palavra, e "setembro de 2026" virava "Setembro De
   2026" -- errado em portugues. */
const capitalizar = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)

/** So' o mes, sem o ano. O ano ja' esta' na pilha de meses logo acima, e o
 *  titulo inteiro nao cabia numa linha de celular. */
function soOMes(mes: string): string {
  const [y, mo] = mes.split('-').map(Number)
  return new Date(y, mo - 1).toLocaleDateString('pt-BR', { month: 'long' })
}

/* Alavancagem tem stake_total zerado de proposito (backend/stake_plan.py): ela
   e' um caminho, nao uma unidade, e so' vira dinheiro na banca de quem apostou.
   Ela continua no fechamento com picks e taxa de acerto, mas nao disputa o
   posto de produto do mes nem move o lucro. */
const contaUnidade = (f: FechamentoFonte) => f.stake_total > 0

function agregarFechamentos(linhas: SourceDay[]): FechamentoMes[] {
  const porMes = new Map<string, Map<string, FechamentoFonte>>()

  for (const d of linhas) {
    const mes = String(d.match_date).slice(0, 7)
    if (mes.length !== 7) continue
    const fontes = porMes.get(mes) ?? new Map<string, FechamentoFonte>()
    porMes.set(mes, fontes)
    const acc = fontes.get(d.source) ?? {
      source: d.source, total: 0, greens: 0, reds: 0,
      profit: 0, stake_total: 0, win_rate: 0, roi: 0,
    }
    acc.total       += Number(d.total ?? 0)
    acc.greens      += Number(d.greens ?? 0)
    acc.reds        += Number(d.reds ?? 0)
    acc.profit      += Number(d.profit ?? 0)
    acc.stake_total += Number(d.stake_total ?? 0)
    fontes.set(d.source, acc)
  }

  const meses: FechamentoMes[] = []
  for (const [mes, mapa] of porMes) {
    const fontes = [...mapa.values()].map(f => ({
      ...f,
      profit: Math.round(f.profit * 100) / 100,
      win_rate: f.total > 0 ? Math.round((f.greens / f.total) * 1000) / 10 : 0,
      roi: f.stake_total > 0 ? Math.round((f.profit / f.stake_total) * 1000) / 10 : 0,
    })).sort((a, b) => b.profit - a.profit)

    const somaLucro = fontes.filter(contaUnidade).reduce((a, f) => a + f.profit, 0)
    const somaStake = fontes.reduce((a, f) => a + f.stake_total, 0)
    const total     = fontes.reduce((a, f) => a + f.total, 0)
    const greens    = fontes.reduce((a, f) => a + f.greens, 0)
    const reds      = fontes.reduce((a, f) => a + f.reds, 0)

    // O produto do mes e' o de maior LUCRO, nao o de maior taxa de acerto: taxa
    // alta com odd baixa perde dinheiro, e o placar aqui e' de resultado.
    const elegiveis = fontes.filter(contaUnidade)
    const comPiso   = elegiveis.filter(f => f.total >= PISO_AMOSTRA)
    const campeao   = comPiso[0] ?? elegiveis[0] ?? null

    meses.push({
      mes, fontes, total, greens, reds,
      profit: Math.round(somaLucro * 100) / 100,
      stake_total: somaStake,
      win_rate: total > 0 ? Math.round((greens / total) * 1000) / 10 : 0,
      roi: somaStake > 0 ? Math.round((somaLucro / somaStake) * 1000) / 10 : 0,
      campeao,
      amostraCurta: comPiso.length === 0 && campeao != null,
    })
  }
  return meses.sort((a, b) => b.mes.localeCompare(a.mes))
}

/** Uma linha do ranking de produtos do mes. */
function LinhaProduto({ f, maxAbs }: { f: FechamentoFonte; maxAbs: number }) {
  const unidade = contaUnidade(f)
  const largura = maxAbs > 0 ? Math.max(3, (Math.abs(f.profit) / maxAbs) * 100) : 3
  return (
    <div className="flex items-center gap-3 px-4 sm:px-5 py-3">
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 w-[82px] text-center ${PICK_TYPE_CLS[f.source] ?? 'bg-surface-2 text-ink-3'}`}>
        {rotuloProduto(f.source)}
      </span>

      <div className="flex-1 min-w-0">
        {/* Fonte sem unidade nao ganha barra: a barra e' de LUCRO, e desenhar
            uma pra quem nao entra no lucro (alavancagem) afirma um numero que
            a coluna da direita se recusa a estampar. */}
        {unidade ? (
          <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${f.profit >= 0 ? 'bg-accent' : 'bg-red-500/70'}`}
              style={{ width: `${largura}%` }}
            />
          </div>
        ) : (
          <div className="h-1.5 rounded-full border border-dashed border-line-strong/60" />
        )}
        <p className="text-[10px] text-ink-4 mt-1 truncate">
          {f.total} {f.total === 1 ? 'pick' : 'picks'}, {f.greens}G {f.reds}R
          {unidade ? <>, ROI {f.roi}%</> : <>, fora do lucro</>}
        </p>
      </div>

      <div className="text-right shrink-0 w-[62px]">
        <p className={`font-mono text-sm font-black tabular-nums ${
          !unidade ? 'text-ink-4' : f.profit >= 0 ? 'text-accent-ink' : 'text-red-400'
        }`}>
          {unidade ? fmtUnits(f.profit, 1) : '--'}
        </p>
        <p className={`font-mono text-[10px] tabular-nums ${f.win_rate >= 55 ? 'text-accent-ink/80' : 'text-ink-4'}`}>
          {f.win_rate}%
        </p>
      </div>
    </div>
  )
}

function AbaFechamento({ linhas, grafico, stakeLabel }: {
  linhas: SourceDay[]
  grafico: { label: string; value: number; meta: string }[]
  stakeLabel: string
}) {
  const meses = useMemo(() => agregarFechamentos(linhas), [linhas])
  const [mesSel, setMesSel] = useState<string>('')

  // O mes selecionado segue os dados: trocar o filtro de fonte pode fazer o mes
  // aberto deixar de existir, e uma tela vazia com um filtro aceso parece bug.
  const mesAtivo = meses.find(m => m.mes === mesSel) ?? meses[0] ?? null

  if (!mesAtivo) {
    return (
      <div className="text-center py-16 text-ink-3 text-sm">
        Nenhum mês fechado ainda para este recorte.
      </div>
    )
  }

  const campeao = mesAtivo.campeao
  const maxAbs = Math.max(0, ...mesAtivo.fontes.filter(contaUnidade).map(f => Math.abs(f.profit)))

  return (
    <>
      {/* Escolha do mes em MENU, nao em parede de pills: com dois anos de
          historico a fila de meses passava de quatro linhas e empurrava o
          fechamento pra fora da tela do celular. O menu ainda mostra o lucro de
          cada mes ao lado do nome, entao da' pra achar o mes bom sem abrir um
          por um. Mesmo componente do filtro longo do site (SelectMenu). */}
      {/* O SELETOR DE MES SUBIU pra cima das abas em 04/09 e vale pra pagina
          inteira · ter um aqui e outro la' era dois controles pro mesmo
          recorte. Quando a pagina esta' em "Todos os meses", esta aba precisa
          escolher UM pra montar o fechamento, e ai' ela usa o mais recente. */}

      <AbaStats tiles={[
        { label: 'Picks no mês', value: String(mesAtivo.total) },
        { label: 'Acerto', value: `${mesAtivo.win_rate}%`, tone: mesAtivo.win_rate >= 55 ? 'green' : 'default' },
        { label: 'Lucro', value: fmtUnits(mesAtivo.profit, 1), tone: mesAtivo.profit >= 0 ? 'green' : 'red' },
        { label: 'ROI', value: `${mesAtivo.roi}%`, tone: mesAtivo.roi >= 0 ? 'green' : 'red' },
      ]} />

      {/* Destaque do mes. O ranking abaixo tem o mesmo numero, mas quem abre a
          aba quer a resposta antes da tabela, nao depois dela. */}
      {campeao && (
        <div className="panel p-5 mb-5">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
              <Trophy className="w-4 h-4 text-accent-ink" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="panel-label">
                Produto mais forte de {soOMes(mesAtivo.mes)}
              </p>
              <p className="text-lg font-black text-ink-1 mt-1 truncate">
                {rotuloProduto(campeao.source)}
              </p>
              <p className="text-[11px] text-ink-4 mt-0.5">
                {campeao.total} {campeao.total === 1 ? 'pick' : 'picks'}, {campeao.greens}G {campeao.reds}R, ROI {campeao.roi}%
              </p>
              {mesAtivo.amostraCurta && (
                <p className="text-[11px] text-amber-400/90 mt-2">
                  Amostra curta: nenhum produto fechou o mês com {PISO_AMOSTRA} picks ou mais.
                </p>
              )}
            </div>
            <div className="text-right shrink-0">
              <p className={`font-mono text-2xl font-black tabular-nums ${campeao.profit >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
                {fmtUnits(campeao.profit, 1)}
              </p>
              <p className="font-mono text-xs text-ink-3 tabular-nums">{campeao.win_rate}% de acerto</p>
            </div>
          </div>
        </div>
      )}

      {/* Ranking completo do mes */}
      <div className="bg-surface-0 border border-line rounded-lg overflow-hidden mb-5">
        <div className="px-4 sm:px-5 py-3 border-b border-line flex items-baseline justify-between gap-3">
          <span className="text-xs font-bold text-ink-2">
            Produtos em {soOMes(mesAtivo.mes)}
          </span>
          <span className="text-[10px] text-ink-4">{stakeLabel}</span>
        </div>
        <div className="divide-y divide-line/50">
          {mesAtivo.fontes.map(f => <LinhaProduto key={f.source} f={f} maxAbs={maxAbs} />)}
        </div>
      </div>

      {grafico.length > 1 && (
        <div className="panel p-5 mb-5">
          <p className="panel-label mb-4">Lucro por mês, unidades</p>
          <LucroBarChart data={grafico} orientation="vertical" />
        </div>
      )}

      {/* Historico: quem ganhou cada mes. E' o que transforma o fechamento num
          placar de temporada em vez de uma foto do mes aberto. */}
      {meses.length > 1 && (
        <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
          <div className="px-4 sm:px-5 py-3 border-b border-line">
            <span className="text-xs font-bold text-ink-2">Produto do mês, mês a mês</span>
          </div>
          <div className="divide-y divide-line/50">
            {meses.map(m => (
              <button
                key={m.mes}
                onClick={() => setMesSel(m.mes)}
                className={`w-full flex items-center gap-3 px-4 sm:px-5 py-3 text-left transition-colors hover:bg-surface-1/50 ${m.mes === mesAtivo.mes ? 'bg-surface-1/40' : ''}`}
              >
                <span className="text-xs font-semibold text-ink-1 w-[74px] shrink-0 truncate">
                  {nomeDoMes(m.mes, true)}
                </span>
                {m.campeao ? (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${PICK_TYPE_CLS[m.campeao.source] ?? 'bg-surface-2 text-ink-3'}`}>
                    {rotuloProduto(m.campeao.source)}
                  </span>
                ) : (
                  <span className="text-[10px] text-ink-4 shrink-0">sem produto elegível</span>
                )}
                {/* No celular a linha sobrava vazia entre o selo e o numero:
                    o resumo do mes estava escondido em `hidden sm:block`. Ele
                    encolhe em vez de sumir. */}
                <span className="text-[11px] text-ink-4 flex-1 truncate">
                  <span className="hidden sm:inline">mês fechou {fmtUnits(m.profit, 1)} em {m.total} picks, </span>
                  {m.win_rate}% de acerto
                </span>
                {/* O numero da direita e' o do CAMPEAO, nao o do mes: a linha
                    inteira responde "quem puxou", e um total do mes colado no
                    selo de um produto le' como se fosse dele. */}
                <span className={`font-mono text-xs font-bold tabular-nums shrink-0 ml-auto sm:ml-0 ${(m.campeao?.profit ?? 0) >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
                  {m.campeao ? fmtUnits(m.campeao.profit, 1) : '--'}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

export default function ResultadosPublicos() {
  const [data, setData] = useState<PublicData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [source, setSource] = useState('all')
  const [month, setMonth] = useState('')
  const [recentLeagueFilter, setRecentLeagueFilter] = useState<string>('')

  const { user } = useAuth()
  const [tab, setTab] = useState<'resumo' | 'por_liga' | 'por_jogo' | 'por_mes' | 'alavancagem'>('resumo')

  // "Picks recentes" · paginação (server-side, ver recent_limit/recent_offset em /public/results)
  const RECENT_PAGE_SIZE = 30
  const [recentPage, setRecentPage] = useState(0)
  const handleMonthChange = (v: string) => { setMonth(v); setRecentPage(0); setRecentLeagueFilter('') }

  // "Por Jogo" · exige login (mesmos dados detalhados que antes só existiam em /results)
  const [games, setGames]           = useState<any[]>([])
  const [gamesTotal, setGamesTotal] = useState(0)
  const [gamesPage, setGamesPage]   = useState(0)
  const [gamesFilter, setGamesFilter] = useState('all')
  const [gamesLoading, setGamesLoading] = useState(false)
  const [detailPick, setDetailPick] = useState<{ id: number; pick_type: string } | null>(null)

  const monthDateRange = (m: string): { date_from?: string; date_to?: string } => {
    if (!m) return {}
    const [y, mo] = m.split('-').map(Number)
    const lastDay = new Date(y, mo, 0).getDate()
    return { date_from: `${m}-01`, date_to: `${m}-${String(lastDay).padStart(2, '0')}` }
  }

  const fetchGames = useCallback((page: number, resultado: string, src: string, m: string) => {
    setGamesLoading(true)
    const { date_from, date_to } = monthDateRange(m)
    const params: any = { limit: GAMES_PAGE_SIZE, offset: page * GAMES_PAGE_SIZE, source: src, days: 3650 }
    if (date_from) params.date_from = date_from
    if (date_to) params.date_to = date_to
    if (resultado !== 'all') params.resultado = resultado
    api.get('/suggestions/results/games', { params })
      .then(r => { setGames(r.data.items); setGamesTotal(r.data.total) })
      .catch(() => { setGames([]); setGamesTotal(0) })
      .finally(() => setGamesLoading(false))
  }, [])

  /* Sem `if (!user) return`: as duas abas sao o HISTORICO da IA, e pick
     encerrado nao e' produto. O que continua fechado e' o pendente -- o
     backend ignora `resultado=pending` sem sessao (ver get_results_games),
     senao a URL entregaria os picks de hoje com mercado, linha e odd. */
  useEffect(() => {
    if (tab === 'por_jogo') fetchGames(0, gamesFilter, source, month)
    setGamesPage(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, user, source, month])

  /* CADA ABA BAIXA O QUE ELA USA (2026-09-04).
     
     A página baixava os blocos das CINCO abas ao abrir, mesmo quem só ia olhar
     o Resumo. `by_league` é de uma aba, `by_source_day` de outra, e cada bloco
     é uma ida ao banco onde a consulta custa 0,4ms e ABRIR A CONEXÃO custa
     perto de 1s. Num container frio isso vira fila, a fila estoura o timeout de
     15s do cliente e aparece o alerta vermelho de "o servidor demorou" -- com o
     log do servidor mostrando 200 em tudo, porque ele respondeu, só que tarde.

     `available_months` entra SEMPRE: ele alimenta o filtro de mês, que fica
     acima das abas e vale pra todas. Pedir só na aba que o usa faria o filtro
     aparecer vazio e depois se preencher sozinho.

     A aba Alavancagem não pede nada daqui: ela tem rota própria. */
  const blocosDaAba = (t: typeof tab): string => {
    const comuns = ['months']
    if (t === 'resumo')    return [...comuns, 'by_day'].join(',')
    if (t === 'por_liga')  return [...comuns, 'by_league'].join(',')
    if (t === 'por_mes')   return [...comuns, 'by_source_day', 'by_day'].join(',')
    return comuns.join(',')
  }

  useEffect(() => {
    setLoading(true)
    setError(false)
    const params: Record<string, string | number> = {
      recent_limit:  RECENT_PAGE_SIZE,
      recent_offset: recentPage * RECENT_PAGE_SIZE,
      blocos: blocosDaAba(tab),
    }
    if (source !== 'all') params.source = source
    if (month) params.month = month
    api.get('/public/results', { params })
      .then(r => setData(r.data))
      .catch(() => { setData(null); setError(true) })
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, month, recentPage, tab])

  const s = data?.summary
  const winRatePct = calcWinRate(s?.greens ?? 0, s?.total ?? 0)
  const months   = data?.available_months ?? []
  const recent   = data?.recent ?? []
  const recentTotal = data?.recent_total ?? 0
  const byDay    = data?.by_day ?? []
  const byLeague = data?.by_league ?? []

  // Metricas derivadas de acerto e cobertura.
  //
  // UNIDADE ENTRA, DINHEIRO NAO. A regra antiga aqui era "nada vira dinheiro ou
  // unidade"; a parte da unidade caiu em 15/08 porque o publico desta pagina le
  // resultado em unidade, nao em porcentagem, e o numero ja existe no banco
  // (coluna `profit`, base de 1u, pesada pelo plano de backend/stake_plan.py).
  // Real continua fora: R$ depende da banca e da stake de cada um, e isso e' a
  // Banca que responde, por usuario. Toda tela que mostrar lucro em unidade tem
  // que exibir o plano de stake junto (`stake_label`), senao o numero nao bate
  // com o que o usuario ve na banca dele.
  const lucroUnidades  = Number(s?.profit ?? 0)
  const leaguesCovered = byLeague.length

  /* ── Indicadores por aba ────────────────────────────────────────────────
     Tudo derivado do que a aba já baixou. Nenhuma consulta nova. */

  const statsPorLiga = (() => {
    if (byLeague.length === 0) return []
    const comWr = byLeague.map(l => ({ ...l, wr: calcWinRate(l.greens, l.total) ?? 0 }))
    // Piso de 5 picks pra uma liga com 1 green em 1 pick nao virar "melhor".
    const elegiveis = comWr.filter(l => l.total >= 5)
    const melhor = [...elegiveis].sort((a, b) => b.wr - a.wr)[0]
    const pior   = [...elegiveis].sort((a, b) => a.wr - b.wr)[0]
    const maisAtiva = [...comWr].sort((a, b) => b.total - a.total)[0]
    const lucrativas = comWr.filter(l => Number(l.profit ?? 0) > 0).length
    return [
      { label: 'Ligas', value: String(byLeague.length) },
      ...(melhor ? [{ label: 'Melhor liga', value: `${melhor.wr}%`, tone: 'green' as const }] : []),
      ...(pior && pior.league_name !== melhor?.league_name
        ? [{ label: 'Pior liga', value: `${pior.wr}%`, tone: 'red' as const }] : []),
      ...(maisAtiva ? [{ label: 'Mais coberta', value: String(maisAtiva.total) }] : []),
    ]
  })()

  /* Aba "Por Jogo": os numeros sao do HISTORICO INTEIRO no filtro, nao da
     pagina aberta. Lucro de dez linhas nao diz nada sobre a IA -- diz sobre
     quais dez linhas calharam de estar na pagina 1. */
  const bySource = data?.by_source ?? []
  const bySourceDay = data?.by_source_day ?? []

  const statsPorJogo = (() => {
    if (bySource.length === 0) return []
    const lucroGeral = bySource.reduce((acc, f) => acc + Number(f.profit ?? 0), 0)
    const maisLucro = [...bySource].sort((a, b) => Number(b.profit) - Number(a.profit))[0]
    // Piso de 5 picks: um pipeline com 1 green em 1 pick nao e' "o mais certeiro".
    const maisCerteiro = [...bySource].filter(f => f.total >= 5)
      .sort((a, b) => b.win_rate - a.win_rate)[0]
    return [
      {
        label: 'Lucro geral', value: fmtUnits(lucroGeral, 1),
        tone: (lucroGeral >= 0 ? 'green' : 'red') as 'green' | 'red',
      },
      ...(maisLucro ? [{
        label: 'Mais lucro', value: fmtUnits(Number(maisLucro.profit), 1),
        tone: 'green' as const,
      }] : []),
      ...(maisCerteiro ? [{
        label: 'Mais certeiro', value: `${maisCerteiro.win_rate}%`,
        tone: 'green' as const,
      }] : []),
      {
        label: 'Produtos', value: String(bySource.length),
      },
    ]
  })()

  /* Lucro por mês e por liga, em unidades · derivados do que a página já
     baixou. O do mês sai de `by_source_day` (que já vem com o peso do plano de
     stake) e NÃO de /results/monthly, que soma na base de 1u: dois números da
     mesma tela discordando é pior que um número a menos. */
  const lucroPorMes = (() => {
    const porMes = new Map<string, number>()
    for (const d of bySourceDay) {
      const mes = String(d.match_date).slice(0, 7)
      porMes.set(mes, (porMes.get(mes) ?? 0) + Number(d.profit ?? 0))
    }
    return [...porMes.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([mes, v]) => {
      const [y, mo] = mes.split('-')
      return {
        label: new Date(Number(y), Number(mo) - 1).toLocaleDateString('pt-BR', { month: 'short' }).replace('.', ''),
        value: Math.round(v * 100) / 100,
        meta: new Date(Number(y), Number(mo) - 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' }),
      }
    })
  })()

  const lucroPorLiga = [...byLeague]
    .map(l => ({
      label: l.league_name,
      value: Math.round(Number(l.profit ?? 0) * 100) / 100,
      meta: `${l.total} picks, ${l.greens}G ${l.reds}R`,
    }))
    .sort((a, b) => b.value - a.value)

  const daysWithPicks  = byDay.length
  const avgPerDay = daysWithPicks > 0 && s ? s.total / daysWithPicks : null
  // Liga com melhor aproveitamento. Piso de 5 picks pra uma liga com 1 green
  // em 1 pick nao aparecer como "melhor" em 100%.
  const bestLeague = byLeague
    .filter(l => l.total >= 5)
    .map(l => ({ name: l.league_name, id: l.league_id, wr: calcWinRate(l.greens, l.total) ?? 0 }))
    .sort((a, b) => b.wr - a.wr)[0] ?? null
  // Maior sequencia de dias seguidos com saldo positivo (mais greens que reds).
  const bestStreak = (() => {
    let cur = 0, best = 0
    for (const d of [...byDay].sort((a, b) => a.match_date.localeCompare(b.match_date))) {
      if (d.greens > d.reds) { cur += 1; best = Math.max(best, cur) } else { cur = 0 }
    }
    return best
  })()

  return (
    <PageShell
      title="Resultados | Pick IA"
      description="Histórico completo dos picks da IA com win rate auditável por liga, por jogo e por mês. Todos os picks registrados, qualquer pessoa pode conferir."
      canonical="https://pickia.com.br/resultados"
      width="full"
      nav={user ? true : <PublicNav width="full" />}
      bar={{
        back: true,
        title: 'Resultados da IA',
        sub: 'Histórico auditável de todos os picks. Atualizado automaticamente.',
      }}
    >
        <AnimatePresence>
        {detailPick && (
          <SuggestionDetail
            id={detailPick.id}
            pickType={detailPick.pick_type}
            onClose={() => setDetailPick(null)}
          />
        )}
        </AnimatePresence>

          {/* FILTRO DE MES, E SO' ELE (2026-09-04, pedido do usuario).
     
              Aqui havia um painel de filtros com Fonte, Mes e (na aba Por Jogo)
              Resultado, dentro de um acordeao "Filtros" que abria por cima das
              abas. Duas coisas competiam pela mesma regiao da tela: o painel
              aberto empurrava as abas pra baixo, e a aba Por Mes ainda tinha o
              PROPRIO seletor de mes logo abaixo -- dois controles de mes na
              mesma tela, um deles escondido atras de um clique.
     
              Ficou um so', no lugar do que estava embaixo: o mesmo `SelectMenu`
              que a aba Por Mes ja' usava, agora valendo pra pagina inteira. Ele
              mostra o lucro de cada mes ao lado do nome, entao da' pra achar o
              mes bom sem abrir um por um.
     
              O FILTRO DE FONTE SAIU. Ele existia pra ler um produto de cada vez,
              e a aba Por Mes ja' faz isso melhor: ela quebra o mes por produto
              numa lista so', sem obrigar a escolher um e recarregar. */}
          {months.length > 0 && (
            <div className="mb-5">
              <SelectMenu
                ariaLabel="Mês"
                options={[{ value: '', label: 'Todos os meses' },
                          ...months.map((m: string) => ({ value: m, label: nomeDoMes(m) }))]}
                value={month}
                onChange={handleMonthChange}
              />
            </div>
          )}

          {/* Abas · Por Liga e' publica; Por Jogo/Por Mes exigem login (dado detalhado por usuario) */}
          <div className="flex border-b border-line mb-6 overflow-x-auto">
            {/* Por Jogo/Por Mes exigem login, mas a aba aparece pra todo mundo:
                sumir da barra sem explicacao fazia parecer que a pagina estava
                quebrada. Deslogado, a aba abre um convite pra entrar. */}
            {([
              ['resumo', 'Resumo'], ['por_liga', 'Por Liga'],
              ['por_jogo', 'Por Jogo'], ['por_mes', 'Por Mês'],
              /* Alavancagem tem aba PRÓPRIA porque ela não cabe nas outras: as
                 quatro somam pick a pick, e a alavancagem só faz sentido
                 caminho a caminho. Ela aparece no total desta página (desde
                 04/09 o placar a conta pelo caminho fechado), mas o "como foi"
                 dela é uma leitura diferente da dos outros produtos. */
              ['alavancagem', 'Alavancagem'],
            ] as [typeof tab, string][]).map(([k, l]) => (
              <button key={k} onClick={() => { if (k !== tab) sinalizarNavegacao(); setTab(k) }}
                className={`tab px-5 py-3 text-sm font-semibold ${tab === k ? 'tab-active' : ''}`}>{l}</button>
            ))}
          </div>

          {tab === 'alavancagem' && (
            <div className="space-y-5">
              <CaminhosDaIA />
              <div className="card p-5">
                <p className="text-xs text-ink-3 font-semibold mb-2">Por que ela conta diferente</p>
                <p className="text-[11px] text-ink-3 leading-relaxed">
                  Os outros produtos são pick independente: cada um arrisca a
                  própria stake e o lucro do período é a soma deles. A
                  alavancagem é um caminho, o dinheiro entra uma vez e rola de
                  pick em pick, então ela entra no placar por caminho encerrado:
                  1u de entrada, o multiplicador menos 1 quando bate a meta, e
                  1u de custo quando morre no meio. Caminho em andamento vale
                  zero até fechar.
                </p>
              </div>
            </div>
          )}

          {tab === 'resumo' && (loading ? (
            <div className="flex justify-center py-20">
              <Spinner size="lg" />
            </div>
          ) : error ? (
            <div className="text-center py-16 text-ink-3">
              Não foi possível carregar os resultados agora. Tente novamente em instantes.
            </div>
          ) : !s || s.total === 0 ? (
            <div className="text-center py-16 text-ink-3">Nenhum resultado encontrado para os filtros selecionados.</div>
          ) : (
            <>
              {/* Stats · lucro em unidades na frente, mesmo tratamento da faixa
                  da Home e do topo de /picks: primeiro tile, linha inteira no
                  mobile. O filtro de fonte/mes vale pra ele igual aos outros,
                  porque sai do mesmo `summary`. */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-8">
                <div className="stat-tile col-span-2 sm:col-span-1">
                  <div className={`stat-value tabular-nums ${lucroUnidades >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {fmtUnits(lucroUnidades, 1)}
                  </div>
                  <div className="stat-label">Lucro</div>
                  <div className="text-[10px] text-ink-4 mt-0.5">unidades</div>
                </div>
                {[
                  { label: 'Win Rate', value: `${winRatePct}%`,   color: (winRatePct ?? 0) >= 55 ? 'text-accent-ink' : 'text-ink-2' },
                  { label: 'Picks',    value: String(s.total),    color: 'text-ink-1' },
                  { label: 'Greens',   value: String(s.greens),   color: 'text-green-400' },
                  { label: 'Reds',     value: String(s.reds),     color: 'text-red-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="stat-tile">
                    <div className={`stat-value ${color}`}>{value}</div>
                    <div className="stat-label">{label}</div>
                  </div>
                ))}
              </div>

              {/* Cobertura e consistencia · segunda leva de numeros, todos de
                  volume/acerto. Nenhum deles vira dinheiro (ver comentario das
                  metricas derivadas: unidade sim, real nao). */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
                {[
                  { label: 'Ligas',        value: String(leaguesCovered), color: 'text-ink-1' },
                  { label: 'Dias com pick', value: String(daysWithPicks),  color: 'text-ink-1' },
                  { label: 'Picks por dia', value: avgPerDay != null ? avgPerDay.toFixed(1) : '-', color: 'text-ink-1' },
                  { label: 'Seq. positiva', value: bestStreak > 0 ? `${bestStreak}d` : '-', color: bestStreak > 0 ? 'text-green-400' : 'text-ink-2' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="stat-tile">
                    <div className={`stat-value ${color}`}>{value}</div>
                    <div className="stat-label">{label}</div>
                  </div>
                ))}
              </div>

              {/* Gráfico por dia */}
              {byDay.length > 1 && (
                <div className="panel p-5 mb-8">
                  <p className="panel-label mb-4">Picks por dia</p>
                  <DailyGreensChart data={byDay} />
                </div>
              )}

              {/* Liga com melhor aproveitamento */}
              {bestLeague && (
                <div className="panel mb-8">
                  <div className="panel-head">
                    <span className="panel-label">Melhor aproveitamento</span>
                    <span className="panel-meta">mín. 5 picks</span>
                  </div>
                  <div className="flex items-center gap-3 px-5 py-4">
                    {bestLeague.id != null
                      ? <LeagueLogo id={bestLeague.id} name={bestLeague.name} />
                      : <div className="w-4.5 h-4.5 rounded-full bg-surface-2 shrink-0" />}
                    <span className="text-sm font-semibold text-ink-1 flex-1 min-w-0 truncate">{bestLeague.name}</span>
                    <span className="font-mono text-xl font-black text-green-400 shrink-0">{bestLeague.wr}%</span>
                  </div>
                </div>
              )}

              {/* Aproveitamento por liga · barra em vez de so' numero, pra dar
                  leitura visual de quais ligas a IA acerta mais. */}
              {byLeague.length > 1 && (
                <div className="panel mb-8">
                  <div className="panel-head">
                    <span className="panel-label">Aproveitamento por liga</span>
                    <span className="panel-meta">{byLeague.length} ligas</span>
                  </div>
                  <div className="px-5 py-4 space-y-3">
                    {[...byLeague]
                      .map(lg => ({ ...lg, wr: calcWinRate(lg.greens, lg.total) ?? 0 }))
                      .sort((a, b) => b.wr - a.wr)
                      .map(lg => (
                        <div key={`bar-${lg.league_id ?? lg.league_name}`} className="flex items-center gap-3">
                          {/* Escudo junto do nome · o "Melhor aproveitamento"
                              logo acima já tem, e a lista inteira não tinha.
                              Numa lista de 16 competições o brasão é o que a
                              olhada rápida pega; o nome truncado em 28px
                              sozinho ("Conmebol Sudameri...") não identifica. */}
                          <span className="flex items-center gap-2 w-32 shrink-0 min-w-0">
                            {lg.league_id != null
                              ? <LeagueLogo id={lg.league_id} name={lg.league_name} />
                              : <span className="w-4.5 h-4.5 rounded-full bg-surface-2 shrink-0" />}
                            <span className="text-[11px] text-ink-3 truncate">{lg.league_name}</span>
                          </span>
                          <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${lg.wr >= 55 ? 'bg-green-500' : 'bg-ink-4'}`}
                              style={{ width: `${Math.max(2, Math.min(100, lg.wr))}%` }}
                            />
                          </div>
                          <span className="font-mono text-[11px] font-bold text-ink-2 w-9 text-right shrink-0">{lg.wr}%</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Lista recente */}
              {recent.length > 0 && (() => {
                const recentLeagues = Array.from(new Set(recent.map(t => t.league_name).filter(Boolean))) as string[]
                const filteredRecent = recentLeagueFilter ? recent.filter(t => t.league_name === recentLeagueFilter) : recent
                const totalPages = Math.ceil(recentTotal / RECENT_PAGE_SIZE)
                return (
                <div className="panel">
                  <div className="panel-head">
                    <span className="panel-label">Picks recentes</span>
                    <span className="panel-meta">{recentTotal} picks, ordenados por data e hora</span>
                  </div>
                  {recentLeagues.length > 1 && (
                    <div className="flex gap-2 flex-wrap px-4 pt-3">
                      <button
                        onClick={() => setRecentLeagueFilter('')}
                        className={`pill ${!recentLeagueFilter ? 'pill-active' : ''}`}
                      >
                        Todas
                      </button>
                      {recentLeagues.map(lg => (
                        <button
                          key={lg}
                          onClick={() => setRecentLeagueFilter(lg === recentLeagueFilter ? '' : lg)}
                          className={`pill ${recentLeagueFilter === lg ? 'pill-active' : ''}`}
                        >
                          {lg}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="divide-y divide-line/50">
                    {filteredRecent.map((tip, i) => (
                      <div key={i} className="flex items-center gap-2 px-4 py-3">
                        {/* Data e hora da partida: ordenados cronologicamente,
                            mais recente no topo. Hora vem de `fixtures`
                            (efêmera), picks antigos mostram só a data. */}
                        <span className="text-[10px] text-ink-4 shrink-0 w-12 leading-tight">
                          <span className="block">
                            {new Date(tip.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                          </span>
                          {tip.match_datetime && (
                            <span className="block font-mono text-ink-3">{tip.match_datetime.slice(11, 16)}</span>
                          )}
                        </span>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[tip.source] ?? ''}`}>
                          {SRC_LBL[tip.source] ?? tip.source}
                        </span>
                        <div className="flex items-center gap-1.5 flex-1 min-w-0">
                          <div className="flex items-center gap-1 min-w-0 shrink">
                            <TeamLogo id={tip.home_team_id} name={tip.home_team_name} size={16} />
                            <span className="text-xs text-ink-2 truncate">{tip.home_team_name}</span>
                          </div>
                          {tip.away_team_name && (
                            <>
                              <span className="text-[10px] text-ink-4 shrink-0">x</span>
                              <div className="flex items-center gap-1 min-w-0 shrink">
                                <TeamLogo id={tip.away_team_id} name={tip.away_team_name} size={16} />
                                <span className="text-xs text-ink-2 truncate">{tip.away_team_name}</span>
                              </div>
                            </>
                          )}
                        </div>
                        <span className="text-[11px] text-ink-3 shrink-0 hidden sm:block truncate max-w-[100px]">
                          {tip.market?.split(' ').slice(0, 3).join(' ')} {tip.line ?? ''}
                        </span>
                        <span className="font-mono text-xs font-bold text-ink-2 shrink-0">{Number(tip.odd).toFixed(2)}</span>
                        {(() => {
                          const rs = getResultStyle(tip.result)
                          return (
                            <span className={`text-xs font-black px-2 py-0.5 rounded border shrink-0 ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-ink-3'}`}>
                              {rs ? rs.label : tip.result}
                            </span>
                          )
                        })()}
                      </div>
                    ))}
                  </div>
                  {/* Paginação */}
                  <div className="px-4 py-3 border-t border-line flex items-center justify-between gap-2 flex-wrap">
                    <button
                      disabled={recentPage === 0 || loading}
                      onClick={() => setRecentPage(p => p - 1)}
                      className="text-xs font-semibold px-3 py-1.5 rounded-md border border-line text-ink-3 hover:text-ink-2 hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      ← Anterior
                    </button>
                    <span className="text-[11px] text-ink-4 tabular-nums">
                      {totalPages > 0 ? `Pág. ${recentPage + 1} de ${totalPages}` : ''}
                    </span>
                    <button
                      disabled={recentPage >= totalPages - 1 || loading}
                      onClick={() => setRecentPage(p => p + 1)}
                      className="text-xs font-semibold px-3 py-1.5 rounded-md border border-line text-ink-3 hover:text-ink-2 hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      Próxima →
                    </button>
                  </div>
                </div>
                )
              })()}
            </>
          ))}

          {tab === 'por_liga' && (loading ? (
            <div className="flex justify-center py-20">
              <Spinner size="lg" />
            </div>
          ) : error ? (
            <div className="text-center py-16 text-ink-3">
              Não foi possível carregar os resultados agora. Tente novamente em instantes.
            </div>
          ) : byLeague.length === 0 ? (
            <div className="text-center py-16 text-ink-3">Nenhum resultado de liga encontrado para os filtros selecionados.</div>
          ) : (
            <>
            <AbaStats tiles={statsPorLiga} />
            {lucroPorLiga.length > 1 && (
              <div className="panel p-5 mb-5">
                <p className="panel-label mb-4">Lucro por liga, unidades</p>
                <LucroBarChart data={lucroPorLiga} orientation="horizontal" />
              </div>
            )}
            <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
              <div className="px-5 py-3 border-b border-line">
                <span className="text-xs font-bold text-ink-2">Resultados por liga</span>
              </div>
              <div className="divide-y divide-line/50">
                {byLeague.map((lg) => {
                  const wr = calcWinRate(lg.greens, lg.total)
                  return (
                    <div key={`${lg.league_id ?? lg.league_name}`} className="flex items-center gap-3 px-5 py-3">
                      {lg.league_id != null
                        ? <LeagueLogo id={lg.league_id} name={lg.league_name} />
                        : <div className="w-4.5 h-4.5 rounded-full bg-surface-2 shrink-0" />}
                      <span className="text-sm font-semibold text-ink-1 flex-1 min-w-0 truncate">{lg.league_name}</span>
                      <span className="text-[11px] text-ink-4 shrink-0 hidden sm:block">{lg.total} picks</span>
                      <span className="font-mono text-[11px] text-ink-4 w-16 text-right shrink-0 hidden sm:block">
                        {lg.greens}G, {lg.reds}R
                      </span>
                      <span className={`font-mono text-xs font-black w-12 text-right shrink-0 ${(wr ?? 0) >= 55 ? 'text-green-400' : 'text-ink-2'}`}>
                        {wr}%
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
            </>
          ))}

          {tab === 'por_jogo' && (
            <div>
              <AbaStats tiles={statsPorJogo} />

              {/* Curva por produto · responde "quem está puxando o resultado",
                  que nenhuma tela do site respondia: os números existiam
                  somados ou espalhados por pick, nunca por produto no tempo. */}
              {bySourceDay.length > 0 && (
                <div className="panel p-5 mb-5">
                  <div className="flex items-baseline justify-between gap-3 mb-4">
                    <p className="panel-label">Lucro acumulado por produto</p>
                    <span className="text-[10px] text-ink-4">
                      {data?.stake_label ?? STAKE_LABEL_PADRAO}
                    </span>
                  </div>
                  <PipelineProfitChart data={bySourceDay} />
                </div>
              )}

              {/* Placar por produto · o "quem dá mais green" em tabela, para
                  quem quer o número exato que a curva mostra de relance. */}
              {bySource.length > 0 && (
                <div className="bg-surface-0 border border-line rounded-lg overflow-hidden mb-5">
                  <div className="px-5 py-3 border-b border-line">
                    <span className="text-xs font-bold text-ink-2">Comparativo por produto</span>
                  </div>
                  <div className="divide-y divide-line/50">
                    {bySource.map(f => (
                      <div key={f.source} className="flex items-center gap-3 px-5 py-3">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${PICK_TYPE_CLS[f.source] ?? 'bg-surface-2 text-ink-3'}`}>
                          {rotuloProduto(f.source)}
                        </span>
                        <span className="text-[11px] text-ink-4 shrink-0 hidden sm:block">{f.total} picks</span>
                        <span className="font-mono text-[11px] text-ink-4 w-16 text-right shrink-0 hidden sm:block">
                          {f.greens}G, {f.reds}R
                        </span>
                        <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden min-w-[40px]">
                          <div
                            className={`h-full rounded-full ${f.win_rate >= 55 ? 'bg-accent' : 'bg-ink-4'}`}
                            style={{ width: `${Math.max(2, Math.min(100, f.win_rate))}%` }}
                          />
                        </div>
                        <span className="font-mono text-[11px] font-bold text-ink-2 w-10 text-right shrink-0 tabular-nums">
                          {f.win_rate}%
                        </span>
                        {/* Fonte com stake_total zerado não entra no lucro em
                            unidades do placar (hoje: alavancagem, que é um
                            caminho e só vira unidade na banca de quem apostou
                            · ver backend/stake_plan.py). Estampar "+0,0u" aí
                            leria como "não deu lucro", que é outra coisa. */}
                        {Number(f.stake_total) > 0 ? (
                          <span className={`font-mono text-xs font-black w-16 text-right shrink-0 tabular-nums ${Number(f.profit) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {fmtUnits(Number(f.profit), 1)}
                          </span>
                        ) : (
                          <span className="font-mono text-[10px] text-ink-4 w-16 text-right shrink-0" title="Só conta em unidades na banca de quem apostou">
                            n/a
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <p className="text-ink-4 text-xs mb-4">{gamesTotal} picks no filtro</p>
              {gamesLoading ? (
                <div className="flex justify-center py-16">
                  <Spinner size="lg" />
                </div>
              ) : games.length === 0 ? (
                <div className="text-center py-16 text-ink-3 text-sm">Nenhum pick encontrado.</div>
              ) : (
                <>
                  <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
                    <div className="divide-y divide-line/50">
                      {games.map(g => {
                        const rs = getResultStyle(g.result)
                        const badge = rs ? `${rs.bg} ${rs.text} ${rs.border}` : 'bg-surface-3/50 text-ink-2 border-line-strong'
                        return (
                          <div key={`${g.pick_type}-${g.id}`}
                            className="flex items-center gap-2 px-4 py-3 hover:bg-surface-1/50 transition-colors cursor-pointer"
                            onClick={() => setDetailPick({ id: g.id, pick_type: g.pick_type })}>
                            <span className="text-[10px] text-ink-4 shrink-0 w-12">
                              {new Date(g.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                            </span>
                            {g.pick_type && source === 'all' && (
                              <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[g.pick_type] ?? ''}`}>
                                {g.pick_type === 'alavancagem' ? 'Alav.' : g.pick_type === 'multipla' ? 'Múlt.' : g.pick_type.toUpperCase()}
                              </span>
                            )}
                            <div className="flex items-center gap-1.5 flex-1 min-w-0">
                              <div className="flex items-center gap-1 min-w-0 shrink">
                                <TeamLogo id={g.home_team_id} name={g.home_team_name} size={16} />
                                <span className="text-xs text-ink-2 truncate">{g.home_team_name}</span>
                              </div>
                              {g.away_team_name && g.pick_type !== 'multipla' && (
                                <>
                                  <span className="text-[10px] text-ink-4 shrink-0">x</span>
                                  <div className="flex items-center gap-1 min-w-0 shrink">
                                    <TeamLogo id={g.away_team_id} name={g.away_team_name} size={16} />
                                    <span className="text-xs text-ink-2 truncate">{g.away_team_name}</span>
                                  </div>
                                </>
                              )}
                            </div>
                            <span className="text-[11px] text-ink-3 shrink-0 hidden sm:block truncate max-w-[120px]">
                              {rotuloDoMercado(g.market, g.line)}
                            </span>
                            <span className="font-mono text-xs font-bold text-ink-2 shrink-0">{g.odd ? Number(g.odd).toFixed(2) : ''}</span>
                            {g.result ? (
                              <span className={`text-xs font-black px-2 py-0.5 rounded border shrink-0 ${badge}`}>{rs ? rs.label : g.result}</span>
                            ) : (
                              <span className="text-ink-4 text-xs shrink-0">Pendente</span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                  {gamesTotal > GAMES_PAGE_SIZE && (() => {
                    const totalPages = Math.ceil(gamesTotal / GAMES_PAGE_SIZE)
                    const goTo = (p: number) => { setGamesPage(p); fetchGames(p, gamesFilter, source, month) }
                    return (
                      <div className="flex items-center justify-center gap-1 mt-4 flex-wrap">
                        <button disabled={gamesPage === 0} onClick={() => goTo(gamesPage - 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors">Ant</button>
                        <span className="text-xs text-ink-3 px-2">{gamesPage + 1} / {totalPages}</span>
                        <button disabled={(gamesPage + 1) * GAMES_PAGE_SIZE >= gamesTotal} onClick={() => goTo(gamesPage + 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors">Próx</button>
                      </div>
                    )
                  })()}
                </>
              )}
            </div>
          )}

          {/* Por Mês · o FECHAMENTO MENSAL da IA.
              Era uma tabela de mês/picks/greens/reds/win%, que responde
              "quanto a IA acertou no mês" e para aí. Faltava o lucro do mês e,
              principalmente, QUAL PRODUTO puxou o resultado -- que é a pergunta
              que decide onde o assinante coloca dinheiro no mês seguinte.

              Passou a sair de `by_source_day` (que a página já baixa) em vez
              de /suggestions/results/monthly. Uma fonte só: aquele endpoint
              soma na base de 1u e este bloco mostra unidade pesada pelo plano
              de stake -- os dois na mesma tela discordariam em silêncio. De
              quebra a aba deixou de exigir login, já que histórico encerrado
              não é produto. */}
          {tab === 'por_mes' && (
            loading ? (
              <div className="flex justify-center py-16"><Spinner size="lg" /></div>
            ) : error ? (
              <div className="text-center py-16 text-ink-3 text-sm">
                Não foi possível carregar o fechamento agora. Tente novamente em instantes.
              </div>
            ) : (
              <AbaFechamento
                linhas={bySourceDay}
                grafico={lucroPorMes}
                stakeLabel={data?.stake_label ?? STAKE_LABEL_PADRAO}
              />
            )
          )}

          {/* CTA · só faz sentido pra quem ainda não tem conta */}
          {!user && (
          <div className="mt-12 text-center">
            <p className="text-ink-3 text-sm mb-4">Quer receber esses picks antes de acontecerem?</p>
            <Button to="/login?mode=register" size="lg">
              Testar o VIP grátis por 2 dias
            </Button>
          </div>
          )}
    </PageShell>
  )
}
