import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Check, Flag, Goal, Lock, Minus, Plus, Repeat, Shield, Square, Star, TrendingUp, Users } from 'lucide-react'
import { useTimesFavoritos } from '../../lib/timesFavoritos'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { FormaPontos } from './FormaPontos'
import { ErrorState, Skeleton, Tooltip } from '../ui'
import { LeagueLogo, PaisDaLigaTag, PlayerPhoto, preCarregarFotos, TeamLogo } from '../TeamLogo'
import { nomeDaLigaPt, rotuloDaRodada } from '../../lib/paisDaLiga'
import {
  ambasMarcam, ambosRecebemCartao, comPeriodo, ehGoleiro, ESTATS_DE_JOGADOR, fraseDoJogador, MERCADOS_DE_TIME, MERCADOS_PRINCIPAIS, numero,
  resultadoDoJogo, RESULTADOS_ACEITOS, ROTULO_PERIODO, rotuloDaLinha, serieDeResultado, taxa, taxaDoJogador, tomDaTaxa,
  filtrarPorMando, type EscolhaDeResultado, type PosicaoNaTabela, type EstatDeJogador, type Mando, type Jogador, type JogoCurto, type JogoDoTime, type Lado, type Periodo, type RaioX, type Taxa,
} from '../../lib/raioX'
import { alternar, trocarNoGrupo, useBilheteMontado, type Selecao } from '../../lib/bilheteMontado'
import { chanceDoResultado, oddDaSelecao, vantagem, type OddDaCasa } from '../../lib/oddsDoJogo'
import { rotuloDoTempo } from '../../lib/picksAgora'
import { aoVivo as estaAoVivo } from '../../lib/aoVivo'
import SelectMenu from '../ui/SelectMenu'
import Campinho from './Campinho'
import NumeroVivo from '../ui/NumeroVivo'
import Classificacao from './Classificacao'
import ResumoDaIA from './ResumoDaIA'
import EstatisticasDoJogo from './EstatisticasDoJogo'
import ArbitroDoJogo from './ArbitroDoJogo'

/*
 * Raio-X do jogo (2026-10-06) · o lugar de pesquisar antes de montar bilhete.
 *
 * DESENHADO PRO CELULAR PRIMEIRO, a pedido do usuário: uma coluna, controles
 * de 44px (o dedo, não o mouse), números grandes e a evidência em barra, que
 * se lê de relance. No computador o mesmo componente vive no painel ao lado da
 * lista de jogos, com mais respiro e nada a mais.
 *
 * A conta (linha, taxa, média) é toda de lib/raioX.ts · aqui é só desenho.
 */

/* A aba Forma saiu em 16/10/2026 (pedido do usuário: "coisas repetidas"): os
   últimos jogos de cada time já estão no Confronto, e a forma em bolinhas no
   topo do Raio-X. */
type Aba = 'mercados' | 'estatisticas' | 'ia' | 'jogadores' | 'escalacao' | 'tabela' | 'confronto'

export interface JogoBase {
  fixture_id: number
  home_team_id?: number
  away_team_id?: number
  league_id?: number
  /** Temporada do jogo · o Raio-X conta só a liga e a temporada dele. */
  season?: number | null
  /** O nome gravado; vale só pra liga fora do mapa de nomes em português. */
  league_name?: string
  home_team?: string
  away_team?: string
  match_datetime?: string | null
  forma_home?: string[]
  forma_away?: string[]
  /** Da lista de jogos · o placar do Raio-X trancado, que não pede dados. */
  status?: string
  home_goals?: number | null
  away_goals?: number | null
}

/*
 * TRANCADO (12/10/2026, pedido do usuário): o plano gratuito abre o Raio-X e
 * vê o placar do jogo e todas as abas, cada uma com cadeado · "pro pessoal ver
 * e ficar curioso". Tocar numa aba mostra o que ela tem e o convite. Nenhum
 * dado é pedido: o servidor recusa (fixtures._assinante) e a tela nem tenta.
 */
export default function RaioXDoJogo({ jogo, trancado = false }: { jogo: JogoBase; trancado?: boolean }) {
  const [dados, setDados] = useState<RaioX | null>(null)
  const [erro, setErro] = useState(false)
  const [aba, setAba] = useState<Aba>('mercados')

  const carregar = () => {
    setErro(false)
    setDados(null)
    if (trancado) return
    api.get(`/fixtures/${jogo.fixture_id}/raio-x`, {
      params: { home: jogo.home_team_id, away: jogo.away_team_id, league: jogo.league_id,
                season: jogo.season ?? undefined },
    })
      .then(r => setDados(r.data))
      .catch(() => setErro(true))
  }
  useEffect(carregar, [jogo.fixture_id])

  /* As fotos dos jogadores ANTES da aba abrir (12/10/2026): elas so' eram
     pedidas quando a pessoa clicava em Jogadores, e chegavam uma a uma. */
  useEffect(() => {
    if (!dados) return
    preCarregarFotos([...dados.jogadores.home.lista, ...dados.jogadores.away.lista]
      .map(j => j.player_id).filter(Boolean))
  }, [dados])

  /* Odds das casas · pedido à parte e sem travar a tela: sem odd o Raio-X
     funciona igual, só sem o preço ao lado da taxa. */
  const [odds, setOdds] = useState<OddDaCasa[]>([])
  /* Jogo rolando (09/10): a rota devolve a odd ao vivo, e ela é relida a cada
     3 minutos · o mesmo passo do cache do servidor, então não gasta a mais. */
  const [oddsAoVivo, setOddsAoVivo] = useState(false)
  useEffect(() => {
    setOdds([])
    setOddsAoVivo(false)
    let vivo = true
    let timer: ReturnType<typeof setTimeout> | undefined
    if (trancado) return
    const ler = () => api.get(`/fixtures/${jogo.fixture_id}/odds`).then(r => {
      if (!vivo) return
      setOdds(r.data?.odds ?? [])
      setOddsAoVivo(!!r.data?.ao_vivo)
      if (r.data?.ao_vivo) timer = setTimeout(ler, 180_000)
    }).catch(() => {})
    ler()
    return () => { vivo = false; clearTimeout(timer) }
  }, [jogo.fixture_id, trancado])

  /* O JOGO ROLANDO NO PLACAR (09/10/2026, pedido do usuário: "parece que não
     está ao vivo"). Lê o placar SÓ DO CACHE do servidor (`so_cache`), sem
     gastar cota: no computador quem o mantém fresco é a lista de Jogos ao
     lado, que já pergunta a cada 30s; no celular, a varredura dos picks.
     Sem nada no cache, o placar fica com o horário, como antes. */
  const [aoVivoAgora, setAoVivoAgora] = useState<PlacarAoVivo | null>(null)
  /* ACABOU COM A TELA ABERTA (15/10/2026): o placar final só vinha do Raio-X
     carregado na abertura, e quando o jogo terminava o topo voltava a mostrar
     o horário de início. O fim que o placar ao vivo informa fica guardado. */
  const [encerradoAgora, setEncerradoAgora] = useState<[number, number] | null>(null)
  useEffect(() => {
    setAoVivoAgora(null)
    setEncerradoAgora(null)
    let vivo = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const id = String(jogo.fixture_id)
    const ler = () => api.get('/live/live-stats', { params: { fixture_ids: id, so_cache: true } })
      .then(r => {
        if (!vivo) return
        const d = r.data?.[id] as PlacarAoVivo | undefined
        const rolando = !!d && estaAoVivo(d.status)
        setAoVivoAgora(rolando ? d! : null)
        if (d && ['FT', 'AET', 'PEN'].includes(d.status) && d.home_goals != null && d.away_goals != null) {
          setEncerradoAgora([d.home_goals, d.away_goals])
          return   // acabou: nada mais a acompanhar
        }
        timer = setTimeout(ler, rolando ? 30_000 : 120_000)
      })
      .catch(() => { if (vivo) timer = setTimeout(ler, 120_000) })
    ler()
    return () => { vivo = false; clearTimeout(timer) }
  }, [jogo.fixture_id])

  /* ABA ESTATÍSTICAS SÓ COM O QUE MOSTRAR (16/10/2026, pedido do usuário).
     Jogo que não começou não tem a aba · rolando, tem · encerrado, só se a
     estatística já existe. A pergunta do encerrado vai com `so_cache`: banco
     e cache, nunca a API. No plano gratuito a aba é vitrine trancada e
     aparece com o jogo começado, sem perguntar nada. */
  const rolando = !!aoVivoAgora || estaAoVivo(jogo.status)
  const encerrado = !!encerradoAgora || !!dados?.fixture.placar_final
    || (!!jogo.status && ['FT', 'AET', 'PEN'].includes(jogo.status))
  const [temEstatistica, setTemEstatistica] = useState(false)
  useEffect(() => {
    setTemEstatistica(false)
    if (!encerrado || trancado) return
    let vivo = true
    api.get(`/live/fixture/${jogo.fixture_id}/estatisticas`, { params: { so_cache: true } })
      .then(r => {
        const p = r.data?.periodos ?? {}
        if (vivo) setTemEstatistica(Object.values(p).some(l => Array.isArray(l) && l.length > 0))
      })
      .catch(() => {})
    return () => { vivo = false }
  }, [jogo.fixture_id, encerrado, trancado])
  const mostraEstatisticas = rolando || (encerrado && (trancado || temEstatistica))
  useEffect(() => {
    if (!mostraEstatisticas && aba === 'estatisticas') setAba('mercados')
  }, [mostraEstatisticas, aba])
  /* O botão do árbitro no placar abria a aba Estatísticas, onde o bloco dele
     mora. Com a aba escondida, ele aparece sozinho até a pessoa tocar numa aba. */
  const [soArbitro, setSoArbitro] = useState(false)
  useEffect(() => setSoArbitro(false), [jogo.fixture_id])

  /* Casa / Fora vale pras duas abas de taxa (Mercados e Jogadores) e fica
     escolhido ao trocar de uma pra outra · ver filtrarPorMando. */
  const [mando, setMando] = useState<Mando>('todos')
  const vistos = useMemo(() => (dados ? filtrarPorMando(dados, mando) : null), [dados, mando])

  const nomeJogo = `${dados?.fixture.home_team || jogo.home_team || 'Casa'} x ${dados?.fixture.away_team || jogo.away_team || 'Fora'}`

  return (
    <div className="min-w-0">
      <Placar jogo={jogo} dados={dados} aoVivo={aoVivoAgora} encerrado={encerradoAgora}
        onArbitro={() => {
          // Sem a aba (jogo que não começou), o árbitro abre sozinho: é antes
          // do apito que ele mais serve.
          if (!mostraEstatisticas) { setSoArbitro(true); return }
          setAba('estatisticas')
          // Espera a aba montar e o bloco do árbitro existir.
          setTimeout(() => document.getElementById('arbitro-do-jogo')
            ?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 400)
        }} />

      {/* Abas fixas ao rolar · no celular a lista de jogadores é longa e a
          troca de aba não pode exigir voltar ao topo. */}
      <div className="sticky top-0 z-20 -mx-4 px-4 sm:mx-0 sm:px-0 bg-surface-0/95 backdrop-blur border-b border-line">
        {/* Oito abas não cabem numa linha de celular, e aba escondida fora da
            tela é aba que ninguém descobre: no celular viram 4 + 4, todas à
            vista; do tablet pra cima, uma linha só. A Leitura da IA virou aba
            (12/10/2026, pedido do usuário) em vez de bloco acima delas, e as
            Estatísticas do jogo entraram em 15/10/2026. */}
        <div className="grid grid-cols-4 sm:flex" role="tablist">
          {([
            ['mercados', 'Mercados'], ['estatisticas', 'Estatísticas'], ['ia', 'Leitura IA'], ['jogadores', 'Jogadores'], ['escalacao', 'Escalação'],
            ['tabela', 'Tabela'], ['confronto', 'Confronto'],
          ] as [Aba, string][]).filter(([k]) => k !== 'estatisticas' || mostraEstatisticas).map(([k, rotulo]) => (
            <button key={k} role="tab" aria-selected={aba === k && !soArbitro}
              onClick={() => { setAba(k); setSoArbitro(false) }}
              className={cn(
                // 13px do tablet pra cima: oito abas numa linha ficavam coladas
                // ("Mercados Estatísticas") no painel ao lado da lista.
                'relative sm:flex-1 h-11 sm:h-12 px-1 sm:px-1.5 text-sm sm:text-[13px] xl:text-sm font-bold transition-colors whitespace-nowrap',
                aba === k ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2',
              )}>
              {rotulo}
              {trancado && <Lock className="inline w-3 h-3 ml-1 -mt-0.5 text-ink-4" aria-label="trancada" />}
              {aba === k && <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
        </div>
      </div>

      <div className="pt-4 pb-28 md:pb-6">
        {trancado ? (
          <AbaTrancada aba={aba} />
        ) : erro ? (
          <div className="card"><ErrorState title="Não deu pra carregar o Raio-X" onRetry={carregar} /></div>
        ) : !dados ? (
          <div className="space-y-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-36 w-full" />
          </div>
        ) : soArbitro && !mostraEstatisticas ? (
          <ArbitroDoJogo fixtureId={dados.fixture.fixture_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id}
            homeNome={dados.fixture.home_team} awayNome={dados.fixture.away_team} />
        ) : aba === 'mercados' ? (
          <AbaMercados dados={vistos!} nomeJogo={nomeJogo} odds={odds} oddsAoVivo={oddsAoVivo} mando={mando} setMando={setMando} />
        ) : aba === 'estatisticas' ? (
          <EstatisticasDoJogo fixtureId={dados.fixture.fixture_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id}
            homeNome={dados.fixture.home_team} awayNome={dados.fixture.away_team} />
        ) : aba === 'ia' ? (
          /* Pedida só ao abrir a aba: na primeira vez do dia é ela que faz o
             servidor gerar, então quem não olha não gasta IA. */
          <ResumoDaIA fixtureId={dados.fixture.fixture_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id}
            homeNome={dados.fixture.home_team} awayNome={dados.fixture.away_team} />
        ) : aba === 'jogadores' ? (
          <AbaJogadores dados={vistos!} nomeJogo={nomeJogo} mando={mando} setMando={setMando} />
        ) : aba === 'escalacao' ? (
          /* Pedida só ao abrir a aba: é a parte do Raio-X que fala com a
             API-Football, e quem não olha a escalação não gasta cota. */
          <Campinho fixtureId={dados.fixture.fixture_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id}
            homeNome={dados.fixture.home_team} awayNome={dados.fixture.away_team} />
        ) : aba === 'tabela' ? (
          <Classificacao fixtureId={dados.fixture.fixture_id} leagueId={dados.fixture.league_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id} />
        ) : (
          <AbaConfronto dados={dados} />
        )}
      </div>
    </div>
  )
}

/* ── Estrela do time favorito (12/10/2026) ────────────────────────────────
   Marcar faz os jogos do time subirem para "Seus times" na aba Jogos. Botão
   de 36px com rótulo: o dedo acerta e a pessoa sabe o que a estrela faz. */
function EstrelaDoTime({ id, nome }: { id: number; nome: string }) {
  const { ehFavorito, alternar } = useTimesFavoritos()
  const ativo = ehFavorito(id)
  return (
    <button type="button" onClick={() => alternar(id)} aria-pressed={ativo}
      aria-label={ativo ? `Tirar ${nome} dos favoritos` : `Seguir ${nome}`}
      className={cn('h-9 px-2.5 -mt-1 inline-flex items-center gap-1 rounded-full text-[11px] font-bold transition-colors',
        ativo ? 'text-yellow-300' : 'text-ink-4 hover:text-ink-2')}>
      <Star className={cn('w-3.5 h-3.5', ativo && 'fill-yellow-300')} aria-hidden />
      {ativo ? 'Seguindo' : 'Seguir'}
    </button>
  )
}

/* ── Aba trancada (plano gratuito) ───────────────────────────────────────── */

const O_QUE_TEM: Record<Aba, [string, string[]]> = {
  mercados: ['Quantas vezes cada linha bateu', ['Gols, escanteios, cartões e chutes, linha a linha', 'Mandante em casa e visitante fora separados', 'A odd das casas ao lado da taxa']],
  estatisticas: ['As estatísticas do jogo, ao vivo', ['Posse, xG, finalizações, escanteios e cartões', 'Jogo inteiro, 1º e 2º tempo, atualizando sozinha', 'O árbitro: faltas, cartões e VAR, e os jogos dele com cada time']],
  ia: ['A leitura da IA sobre este jogo', ['Os mercados de over e under em que os dois times concordam', 'Tabela, técnico e o peso de liga ou mata-mata', 'O alerta quando a amostra é curta']],
  jogadores: ['Cada jogador, jogo a jogo', ['Chutes, chutes no alvo, faltas e cartões', 'Quem começa jogando hoje', 'Separe seleções de jogador com um toque']],
  escalacao: ['O campinho do jogo', ['Escalação oficial ou provável', 'Desfalques e suspensos', 'Técnico e formação']],
  tabela: ['A tabela da liga', ['Posição, pontos e saldo', 'Campanha em casa e fora', 'Zona de classificação e rebaixamento']],
  confronto: ['O confronto direto', ['Vitórias de cada lado e empates', 'Gols e escanteios por jogo', 'Os últimos jogos entre os dois']],
}

function AbaTrancada({ aba }: { aba: Aba }) {
  const [titulo, itens] = O_QUE_TEM[aba]
  return (
    <div className="card p-6 text-center relative overflow-hidden">
      {/* Linhas de mentira, borradas: dá a forma do que está atrás do
          cadeado sem entregar nenhum número de verdade. */}
      <div aria-hidden className="absolute inset-x-6 top-6 space-y-3 blur-[3px] opacity-40 select-none pointer-events-none">
        {[78, 64, 88, 52, 70].map((w, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="h-3 rounded bg-surface-3" style={{ width: `${w}%` }} />
            <div className="h-3 w-10 rounded bg-accent/40" />
          </div>
        ))}
      </div>
      <div className="relative pt-28">
        <div className="w-11 h-11 rounded-full bg-yellow-400/10 border border-yellow-400/25 flex items-center justify-center mx-auto mb-3">
          <Lock className="w-5 h-5 text-yellow-400" aria-hidden />
        </div>
        <h3 className="text-base font-bold text-ink-1">{titulo}</h3>
        <ul className="mt-3 space-y-1.5 text-sm text-ink-2 inline-block text-left">
          {itens.map(i => (
            <li key={i} className="flex items-start gap-2">
              <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" aria-hidden />{i}
            </li>
          ))}
        </ul>
        <p className="text-xs text-ink-3 mt-4">Todas as abas do Raio-X são do plano Pro.</p>
        <Link to="/checkout"
          className="mt-3 inline-flex h-11 items-center px-6 rounded-lg bg-yellow-400 hover:bg-yellow-300 text-on-fill font-black text-sm transition-colors">
          Desbloquear o Raio-X
        </Link>
      </div>
    </div>
  )
}

/* ── Placar ─────────────────────────────────────────────────────────────── */

/** O que /live/live-stats devolve de um jogo (ver live.py::_montar_live_stats). */
interface PlacarAoVivo {
  status: string; elapsed: number | null
  home_goals: number | null; away_goals: number | null
  home_corners: number; away_corners: number
  home_shots_on: number; away_shots_on: number
  home_yellow: number; away_yellow: number
  home_possession: number; away_possession: number
}

function Placar({ jogo, dados, aoVivo, encerrado, onArbitro }: {
  jogo: JogoBase; dados: RaioX | null; aoVivo: PlacarAoVivo | null; encerrado?: [number, number] | null
  /** Tocar no nome do árbitro abre o bloco dele, na aba Estatísticas. */
  onArbitro?: () => void
}) {
  const f = dados?.fixture
  const ligaId = f?.league_id ?? jogo.league_id
  const quando = f?.match_datetime ?? jogo.match_datetime
  const hora = quando ? new Date(quando).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '--:--'
  const dia = quando ? new Date(quando).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' }) : ''
  const placarFinal = encerrado ?? f?.placar_final ?? (jogo.status && ['FT', 'AET', 'PEN'].includes(jogo.status)
    && jogo.home_goals != null && jogo.away_goals != null ? [jogo.home_goals, jogo.away_goals] : null)
  const formaHome = jogo.forma_home ?? dados?.times.home.jogos.slice(0, 5).map(resultadoDoJogo).filter(Boolean) as string[] ?? []
  const formaAway = jogo.forma_away ?? dados?.times.away.jogos.slice(0, 5).map(resultadoDoJogo).filter(Boolean) as string[] ?? []

  /* POSIÇÃO NA TABELA (16/10/2026, pedido do usuário). Só em jogo de liga ou
     de grupos: no mata-mata a tabela da fase anterior não diz nada do jogo. */
  const formato = dados?.competicao?.formato
  const comTabela = formato !== 'mata-mata' && formato !== 'mata-mata ida e volta'
  const Time = ({ id, nome, forma, pos }: { id?: number; nome?: string; forma: string[]; pos?: PosicaoNaTabela | null }) => (
    <div className="flex-1 min-w-0 flex flex-col items-center text-center gap-2">
      <TeamLogo id={id} name={nome ?? ''} size={52} />
      <span className="text-sm font-bold text-ink-1 leading-tight line-clamp-2">{nome}</span>
      {comTabela && pos && (
        <span className="-mt-1 text-[11px] text-ink-3 tabular-nums">
          <b className="text-ink-1">{pos.posicao}º</b> de {pos.de}, {pos.pontos} pts
        </span>
      )}
      <FormaPontos forma={forma} />
      {id && <EstrelaDoTime id={id} nome={nome ?? ''} />}
    </div>
  )

  return (
    <div className="card p-4 mb-3 relative overflow-hidden">
      <div aria-hidden className="absolute inset-0 bg-data-grid bg-[length:24px_24px] opacity-60 [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
      <div className="relative">
        {/* LIGA E RODADA EM PORTUGUÊS (2026-10-07, pedido do usuário). Antes era
            só o escudo e o texto cru do provedor, "Regular Season - 29". */}
        <div className="flex flex-col items-center gap-0.5 mb-3 text-center">
          <div className="flex items-center justify-center gap-1.5 min-w-0">
            <LeagueLogo id={ligaId} size={16} />
            <span className="text-xs font-bold text-ink-1 truncate">{nomeDaLigaPt(ligaId, jogo.league_name)}</span>
            <PaisDaLigaTag id={ligaId} soBandeira />
          </div>
          {f?.round && <span className="text-[11px] text-ink-3">{rotuloDaRodada(f.round)}</span>}
          {/* FORMATO DA COMPETIÇÃO E PLACAR DA IDA (14/10/2026, pedido do
              usuário): pontos corridos e mata-mata se jogam diferente, e no
              jogo de volta quem está na frente muda tudo. */}
          {(() => {
            const c = dados?.competicao
            const rotulo = !c?.formato ? null
              : c.formato === 'liga' ? 'Pontos corridos'
              : c.formato === 'grupos' ? 'Fase de grupos'
              : c.formato === 'mata-mata ida e volta'
                ? (c.perna === 'volta' || c.ida ? 'Mata-mata, jogo de volta'
                  : c.perna === 'ida' ? 'Mata-mata, jogo de ida' : 'Mata-mata, ida e volta')
              : c.formato === 'mata-mata' ? 'Mata-mata' : null
            if (!rotulo) return null
            return (
              <div className="mt-1 flex flex-col items-center gap-1">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-2 border border-line rounded-full px-2 py-0.5">
                  {rotulo}
                </span>
                {c?.ida && f && (
                  <span className="text-[11px] text-ink-3 tabular-nums">
                    Ida: {f.home_team} <b className="text-ink-1">{c.ida.gols_mandante} x {c.ida.gols_visitante}</b> {f.away_team}
                  </span>
                )}
                {c?.perna === 'ida' && c.volta_em && (
                  <span className="text-[11px] text-ink-3">
                    Volta em {new Date(c.volta_em).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                  </span>
                )}
              </div>
            )
          })()}
        </div>
        <div className="flex items-start gap-2">
          <Time id={f?.home_team_id ?? jogo.home_team_id} nome={f?.home_team || jogo.home_team} forma={formaHome} pos={dados?.posicoes?.home} />
          {aoVivo ? (
            /* Rolando: o placar no lugar do horário, e o tempo e o minuto
               embaixo, no azul do Ao Vivo do site. */
            <div className="shrink-0 pt-2 text-center">
              <div className="font-mono text-3xl font-black text-ink-1 tabular-nums">
                {/* Gol com a tela aberta: o dígito rola, como placar. */}
                <NumeroVivo valor={aoVivo.home_goals ?? 0} /><span className="text-ink-4 mx-1.5">-</span><NumeroVivo valor={aoVivo.away_goals ?? 0} />
              </div>
              <div className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-bold text-sky-300 tabular-nums">
                <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" aria-hidden />
                {rotuloDoTempo({ status: aoVivo.status, minuto: aoVivo.elapsed })}
              </div>
            </div>
          ) : placarFinal ? (
            /* Encerrado: o placar final, e não o horário de um jogo que já
               acabou (09/10/2026, pedido do usuário). */
            <div className="shrink-0 pt-2 text-center">
              <div className="font-mono text-3xl font-black text-ink-1 tabular-nums">
                {placarFinal[0]}<span className="text-ink-4 mx-1.5">-</span>{placarFinal[1]}
              </div>
              <div className="mt-1 text-[11px] font-semibold text-ink-3">Encerrado</div>
            </div>
          ) : (
            <div className="shrink-0 pt-3 text-center">
              <div className="font-mono text-2xl font-black text-ink-1 tabular-nums">{hora}</div>
              <div className="text-[11px] text-ink-3 capitalize mt-0.5">{dia}</div>
            </div>
          )}
          <Time id={f?.away_team_id ?? jogo.away_team_id} nome={f?.away_team || jogo.away_team} forma={formaAway} pos={dados?.posicoes?.away} />
        </div>
        {/* QUEM APITA (16/10/2026, pedido do usuário). O toque leva aos números
            dele na aba Estatísticas. A escala sai 1 ou 2 dias antes do jogo. */}
        {dados?.arbitro?.nome && (
          <button type="button" onClick={onArbitro}
            className="mt-3 mx-auto flex items-center gap-1.5 h-9 px-3 rounded-full border border-line bg-surface-2/60 text-xs text-ink-2 hover:text-ink-1 transition-colors">
            <span className="text-ink-3">Árbitro</span>
            <b className="text-ink-1 font-semibold">{dados.arbitro.nome.split(',')[0]}</b>
            <span aria-hidden className="text-ink-3">›</span>
          </button>
        )}
        {/* Quatro números do jogo, e só: o resto mora nas abas. */}
        {aoVivo && (
          <div className="mt-4 pt-3 border-t border-line grid grid-cols-4 text-center">
            {([
              ['Escanteios', aoVivo.home_corners, aoVivo.away_corners, ''],
              ['No alvo', aoVivo.home_shots_on, aoVivo.away_shots_on, ''],
              ['Cartões', aoVivo.home_yellow, aoVivo.away_yellow, ''],
              ['Posse', aoVivo.home_possession, aoVivo.away_possession, '%'],
            ] as const).map(([rotulo, c, fo, suf]) => (
              <div key={rotulo} className="min-w-0">
                <div className="text-[10px] text-ink-4">{rotulo}</div>
                <div className="font-mono text-sm font-bold text-ink-1 tabular-nums">
                  {c}{suf}<span className="text-ink-4 mx-1">-</span>{fo}{suf}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Peças comuns ───────────────────────────────────────────────────────── */

/*
 * LISTA SUSPENSA NO LUGAR DA FILEIRA DE BOTÕES (09/10/2026, pedido do usuário).
 *
 * Nove mercados e onze estatísticas de jogador em botões quebravam em duas
 * linhas e empurravam o conteúdo pra baixo. Agora é o mesmo menu do filtro de
 * ligas (SelectMenu): uma linha, a escolha à vista, o resto a um toque.
 *
 * Ao lado, o recorte de jogos: todos, ou "Casa / Fora", em que cada time conta
 * só os jogos do lado em que joga ESTE jogo (ver filtrarPorMando).
 */
function SeletoresDoRaioX({ opcoes, valor, onChange, rotulo, mando, setMando }: {
  opcoes: Array<{ id: string; rotulo: string }>; valor: string; onChange: (v: string) => void
  rotulo: string; mando: Mando; setMando: (m: Mando) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SelectMenu ariaLabel={rotulo} value={valor} onChange={onChange}
        options={opcoes.map(o => ({ value: o.id, label: o.rotulo }))} />
      <SelectMenu ariaLabel="Jogos" value={mando} onChange={v => setMando(v as Mando)}
        options={[
          { value: 'todos', label: 'Todos os jogos' },
          { value: 'mando', label: 'Casa / Fora', meta: 'mando' },
        ]} />
    </div>
  )
}
function Passo({ rotulo, onMenos, onMais, desabilitaMenos }: {
  rotulo: string; onMenos: () => void; onMais: () => void; desabilitaMenos?: boolean
}) {
  const botao = 'w-11 h-11 grid place-items-center rounded-lg border border-line bg-surface-1 text-ink-1 hover:border-line-strong disabled:opacity-30 active:scale-95 transition'
  return (
    <div className="flex items-center gap-2">
      <button className={botao} onClick={onMenos} disabled={desabilitaMenos} aria-label="Diminuir linha"><Minus size={18} /></button>
      <span className="min-w-[124px] text-center font-mono font-black text-base text-ink-1 tabular-nums">{rotulo}</span>
      <button className={botao} onClick={onMais} aria-label="Aumentar linha"><Plus size={18} /></button>
    </div>
  )
}

const TOM: Record<ReturnType<typeof tomDaTaxa>, string> = {
  bom: 'text-accent-ink', medio: 'text-amber-400', ruim: 'text-red-400', nenhum: 'text-ink-4',
}

/* MÉDIA EM DESTAQUE (17/10/2026, pedido do usuário): "a média é o que
   importa", e ela vinha miúda no rodapé do X/N. Agora são duas colunas do
   mesmo tamanho: Média por jogo e Bateu X/N. */
/* MÉDIA RECENTE (17/10/2026): com a temporada inteira, a média esconde time
   em queda ou em alta. `recente` é a média dos 5 últimos de cada série, e
   aparece embaixo da média quando há mais que isso. Sem peso escondido: são
   dois números que a pessoa lê. */
function NumeroDaTaxa({ t, grande, semMedia, recente }: {
  t: Taxa; grande?: boolean; semMedia?: boolean; recente?: number | null
}) {
  const valor = cn('font-mono font-black tabular-nums leading-none', grande ? 'text-2xl' : 'text-lg')
  const rotulo = 'text-[10px] font-semibold uppercase tracking-wide text-ink-3 mb-1'
  if (!semMedia && t.media != null) {
    return (
      <div className="flex items-start gap-4 shrink-0 text-right">
        <div>
          <div className={rotulo}>Média</div>
          <div className={cn(valor, 'text-ink-1')}>{t.media.toFixed(1)}</div>
          <div className="text-[11px] text-ink-3 mt-1 tabular-nums whitespace-nowrap">
            {recente != null
              ? <>últ. 5: <b className="text-ink-1">{recente.toFixed(1)}</b>{' '}
                  {recente > t.media + 0.05 ? '▲' : recente < t.media - 0.05 ? '▼' : ''}</>
              : 'por jogo'}
          </div>
        </div>
        <div>
          <div className={rotulo}>Bateu</div>
          <div className={cn(valor, TOM[tomDaTaxa(t.pct)])}>{t.n ? `${t.bateu}/${t.n}` : '—'}</div>
          <div className="text-[11px] text-ink-3 mt-1 tabular-nums">
            {t.pct != null ? `${Math.round(t.pct * 100)}%` : 'sem dado'}
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className="text-right shrink-0">
      <div className={cn('font-mono font-black tabular-nums leading-none', grande ? 'text-2xl' : 'text-lg', TOM[tomDaTaxa(t.pct)])}>
        {t.n ? `${t.bateu}/${t.n}` : '—'}
      </div>
      <div className="text-[11px] text-ink-3 mt-1 tabular-nums">
        {t.pct != null ? `${Math.round(t.pct * 100)}%` : 'sem dado'}
        {t.media != null && !semMedia && <>, média {t.media.toFixed(1)}</>}
      </div>
    </div>
  )
}

/**
 * Uma barra por jogo, do mais antigo pro mais recente, com a linha desenhada.
 * Verde = bateu. É o gráfico que responde "bate sempre ou bateu duas vezes
 * muito?" melhor que qualquer média.
 */
function Barras({ valores, linha, lado, rotulos, max: maxFixo, topo, dicas: dicasDoJogo }: {
  valores: Array<number | null>; linha: number; lado: Lado
  /** Legenda de cada jogo (mesma ordem de `valores`), mostrada no toque/hover. */
  rotulos?: string[]
  /** Escala comum, pra duas metades lado a lado terem barras comparáveis. */
  max?: number
  /** Jogo contra time do top 6 da tabela (mesma ordem de `valores`). */
  topo?: boolean[]
  /** A dica de cada barra (mesma ordem de `valores`): escudos, dia e placar. */
  dicas?: ReactNode[]
}) {
  const serie = [...valores].reverse()
  const legendas = rotulos ? [...rotulos].reverse() : []
  const marcas = topo ? [...topo].reverse() : []
  const dicas = dicasDoJogo ? [...dicasDoJogo].reverse() : []
  /* Bolinha embaixo da barra = jogo contra o top 6 da tabela. */
  const max = maxFixo ?? Math.max(linha + 1, ...serie.map(v => v ?? 0))
  const yLinha = 100 - (linha / max) * 100
  /* Temporada inteira dá 20+ barras: o número em cima de cada uma não cabe
     no celular. Some o número, fica a legenda no toque e a linha da média. */
  const muitas = serie.length > 12
  const validos = serie.filter((v): v is number => v != null)
  const media = validos.length ? validos.reduce((a, b) => a + b, 0) / validos.length : null
  return (
    <div>
    {/* Com muitos jogos o gráfico cresce: em 56px trinta barras ficavam
        achatadas e 7 escanteios parecia 12 (17/10/2026). */}
    <div className={cn('relative flex items-end', muitas ? 'h-24 gap-px' : 'h-14 gap-[3px]')}>
      {serie.map((v, i) => {
        const bateu = v != null && v !== linha && (lado === 'mais' ? v > linha : v < linha)
        const dica = dicas[i]
        const legenda = legendas[i]
          ? `${legendas[i]}: ${v ?? 'sem dado'}`
          : String(v ?? 'sem dado')
        const coluna = (
          <div title={dica ? undefined : legenda} aria-label={legenda}
            className="w-full h-full flex flex-col justify-end items-center gap-0.5">
            {!muitas && <span className="text-[9px] font-mono text-ink-3 tabular-nums leading-none">{v ?? ''}</span>}
            {marcas[i] !== undefined && (
              <span className={cn('order-last w-1 h-1 rounded-full shrink-0', marcas[i] ? 'bg-ink-2' : 'bg-transparent')} />
            )}
            <div
              className={cn('w-full rounded-sm', v == null ? 'bg-surface-3/40' : bateu ? 'bg-green-500' : 'bg-surface-3')}
              style={{ height: `${v == null ? 6 : Math.max(6, (v / max) * 78)}%` }}
            />
          </div>
        )
        /* Com a dica, a barra abre o balão com escudo e placar; sem ela,
           fica o title de texto. */
        if (!dica) return <div key={i} className="flex-1 h-full min-w-0 flex">{coluna}</div>
        return <Tooltip key={i} className="flex-1 h-full min-w-0" text={dica}>{coluna}</Tooltip>
      })}
      <div className="absolute inset-x-0 border-t border-dashed border-ink-3/60 pointer-events-none"
        style={{ top: `${yLinha * 0.78 + 22}%` }} />
      {/* Linha cheia = a média da série, pra ver de relance onde ela cai
          em relação à linha da aposta (tracejada). */}
      {media != null && (
        <div className="absolute inset-x-0 border-t-2 border-ink-1/70 pointer-events-none"
          style={{ top: `${(100 - (Math.min(media, max) / max) * 100) * 0.78 + 22}%` }} />
      )}
    </div>
    {/* Sem o número em cada barra, a legenda diz o que é cada linha e pra
        que lado o tempo corre. */}
    {muitas && (
      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-ink-4">
        <span>mais antigo</span>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1"><span className="w-3 border-t-2 border-ink-1/70" />média</span>
          <span className="flex items-center gap-1"><span className="w-3 border-t border-dashed border-ink-3" />linha</span>
          {marcas.some(Boolean) && <span className="flex items-center gap-1"><span className="w-1 h-1 rounded-full bg-ink-2" />top 6</span>}
        </span>
        <span>mais recente</span>
      </div>
    )}
    </div>
  )
}

/* DICA DO JOGO (18/10/2026, pedido do usuário): passar o mouse (ou tocar)
   num resultado ou numa barra mostra com quem foi, o dia e o placar, com os
   escudos · antes era um title de texto puro. Mandante sempre à esquerda. */
interface LadoDaPartida { id: number; nome: string; gols: number | null }

function DicaDoJogo({ j, timeId, timeNome, rank, valor }: {
  j: JogoDoTime; timeId: number; timeNome: string; rank?: number
  /** "Escanteios no jogo: 13" · o número da barra, quando a dica é de mercado. */
  valor?: string
}) {
  const nos = { id: timeId, nome: timeNome, gols: j.gols_pro }
  const eles = { id: j.adversario_id, nome: j.adversario || 'Adversário', gols: j.gols_contra }
  const [casa, fora] = j.em_casa ? [nos, eles] : [eles, nos]
  return <DicaDePartida casa={casa} fora={fora} valor={valor}
    detalhe={`${dataCurta(j.data)}, ${j.em_casa ? 'em casa' : 'fora'}${rank ? `, adversário ${rank}º` : ''}`} />
}

/** A partida sem lado (jogos do árbitro): mandante x visitante. */
function DicaDePartida({ casa, fora, detalhe, valor }: {
  casa: LadoDaPartida; fora: LadoDaPartida; detalhe: string; valor?: string
}) {
  const lado = (t: LadoDaPartida) => (
    <div className="flex-1 min-w-0 flex flex-col items-center gap-1 text-center">
      <TeamLogo id={t.id} name={t.nome} size={24} />
      <span className="text-[10px] font-semibold text-ink-2 truncate w-full">{t.nome}</span>
    </div>
  )
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        {lado(casa)}
        <span className="font-mono font-black text-base text-ink-1 tabular-nums shrink-0">
          {casa.gols ?? '-'} x {fora.gols ?? '-'}
        </span>
        {lado(fora)}
      </div>
      <div className="text-center text-[10px] text-ink-3">{detalhe}</div>
      {valor && <div className="text-center text-[11px] text-ink-1 font-semibold">{valor}</div>}
    </div>
  )
}

const BARRA: Record<ReturnType<typeof tomDaTaxa>, string> = {
  bom: 'bg-accent', medio: 'bg-amber-400', ruim: 'bg-red-400', nenhum: 'bg-ink-4',
}

/* Um número com rótulo em cima · os três do quadro ficam do mesmo tamanho,
   lado a lado, no padrão de cartão de indicador (Tremor). */
function Indicador({ rotulo, valor, detalhe }: { rotulo: string; valor: string; detalhe?: ReactNode }) {
  return (
    <div className="rounded-lg bg-surface-1 border border-line/60 px-2.5 py-2 min-w-0">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-ink-3 truncate">{rotulo}</div>
      <div className="font-mono font-black text-ink-1 text-base tabular-nums leading-tight mt-0.5">{valor}</div>
      {detalhe && <div className="text-[10px] text-ink-3 truncate">{detalhe}</div>}
    </div>
  )
}

function BotaoBilhete({ selecao, cheio }: { selecao: Selecao; cheio?: boolean }) {
  const bilhete = useBilheteMontado()
  const dentro = bilhete.some(s => s.id === selecao.id)
  return (
    <button
      onClick={() => alternar(selecao)}
      aria-pressed={dentro}
      aria-label={dentro ? 'Tirar das minhas seleções' : 'Separar nas minhas seleções'}
      className={cn(
        'flex items-center justify-center rounded-lg border font-bold transition active:scale-95',
        cheio ? 'w-full h-12 gap-2 text-sm' : 'w-11 h-11 shrink-0',
        dentro
          ? 'bg-accent/15 border-accent/50 text-accent-ink'
          : cheio ? 'bg-accent text-on-fill border-accent hover:bg-accent-hover' : 'bg-surface-1 border-line text-ink-2 hover:border-accent/50',
      )}>
      {dentro ? <Check size={18} /> : <Plus size={18} />}
      {cheio && <span>{dentro ? 'Separada' : 'Separar seleção'}</span>}
    </button>
  )
}

/**
 * "Odd 1.85 · Betano" e o veredito: com valor, justa ou sem valor, pela taxa
 * dos últimos jogos. A conta é a do tipster (chance × odd − 1) e a tela diz
 * de onde vem a chance · não é a probabilidade do motor.
 */
function LinhaDaOdd({ odd, bateu, n }: { odd: OddDaCasa | null; bateu: number; n: number }) {
  if (!odd) return null
  const v = vantagem(bateu, n, odd.odd)
  const selo = v == null ? null
    : v >= 0.05 ? { txt: `Valor +${Math.round(v * 100)}%`, cls: 'bg-accent/15 text-accent-ink border-accent/40' }
    : v > -0.05 ? { txt: 'Odd justa', cls: 'bg-surface-2 text-ink-2 border-line' }
    : { txt: 'Sem valor', cls: 'bg-red-500/10 text-red-400 border-red-500/30' }
  return (
    <div className="mt-3 flex items-center gap-2 flex-wrap text-sm">
      <span className="text-ink-3">Odd</span>
      <span className="font-mono font-black text-ink-1 tabular-nums">{odd.odd.toFixed(2)}</span>
      {odd.casa && <span className="text-ink-3 text-xs">na {odd.casa}</span>}
      {selo && <span className={cn('ml-auto text-[11px] font-bold px-2 py-0.5 rounded border', selo.cls)}>{selo.txt}</span>}
    </div>
  )
}

/* ── Mercados ───────────────────────────────────────────────────────────── */

function AbaMercados({ dados, nomeJogo, odds, oddsAoVivo, mando, setMando }: {
  dados: RaioX; nomeJogo: string; odds: OddDaCasa[]; oddsAoVivo: boolean; mando: Mando; setMando: (m: Mando) => void
}) {
  /* Mercado + DE QUEM (os dois somados, ou um time só) · ver MERCADOS_PRINCIPAIS. */
  /* Abre no Resultado: é a primeira pergunta de quem olha um jogo. */
  const [principal, setPrincipal] = useState('resultado')
  const [quem, setQuem] = useState<'jogo' | 'home' | 'away'>('jogo')
  /* "Resultado" não é mercado de linha e tem quadro próprio (QuadrosDeResultado);
     o par de cima continua valendo pra os hooks não mudarem de ordem. */
  const ehResultado = principal === 'resultado'
  const par = MERCADOS_PRINCIPAIS.find(p => p.id === principal) ?? MERCADOS_PRINCIPAIS[0]
  const id = quem === 'jogo' ? par.jogo : par.time
  const mercado = MERCADOS_DE_TIME.find(m => m.id === id)!
  const [periodoEscolhido, setPeriodo] = useState<Periodo>('total')
  /* Faltas só existem no jogo todo · o seletor fica, desligado, e a conta
     usa "total" sem perder a escolha da pessoa pros outros mercados. */
  const periodo: Periodo = mercado.soTotal ? 'total' : periodoEscolhido
  const [linhas, setLinhas] = useState<Record<string, number>>({})
  const [lado, setLado] = useState<Lado>('mais')
  const timeFoco: 'home' | 'away' = quem === 'away' ? 'away' : 'home'
  const chaveLinha = `${id}:${periodo}`
  const linha = linhas[chaveLinha] ?? (periodo === 'total' ? mercado.linhaPadrao : mercado.linhaPadraoTempo)
  const mudarLinha = (d: number) => setLinhas(l => ({ ...l, [chaveLinha]: Math.max(0.5, linha + d) }))

  const { home, away } = dados.times
  const f = dados.fixture
  const base = {
    fixture_id: f.fixture_id, home_team_id: f.home_team_id, away_team_id: f.away_team_id,
    home: f.home_team, away: f.away_team,
  }
  const linhaTxt = rotuloDaLinha(linha, lado)

  /* "vs Palmeiras · 12/09/26" pra legenda de cada barra. */
  const rank = dados.rank_adversarios ?? {}
  const rotulosDe = (jogos: JogoDoTime[]) =>
    jogos.map(j => {
      const pos = rank[String(j.adversario_id)]
      return `${j.em_casa ? 'vs' : '@'} ${j.adversario || 'adversário'}${pos ? ` (${pos}º)` : ''}, ${dataCurta(j.data)}`
    })
  /* Sem tabela única (copa, grupos) volta undefined e a tela não marca nada. */
  const topoDe = (jogos: JogoDoTime[]) => Object.keys(rank).length
    ? jogos.map(j => (rank[String(j.adversario_id)] ?? 99) <= 6)
    : undefined

  /* "19 jogos na temporada" (a série é a temporada inteira nesta competição,
     ver _JOGOS_RAIO_X_TEMPORADA), ou quantos têm o dado de verdade · no 1º e
     2º tempo os jogos antigos não têm a folha do 1º tempo, e a barra vazia
     sem explicação parece jogo de zero. */
  const amostra = (valores: Array<number | null>) => {
    const com = valores.filter(v => v != null).length
    if (com === valores.length) return `${valores.length} ${valores.length === 1 ? 'jogo' : 'jogos'} na temporada`
    return `${com} de ${valores.length} jogos com dado ${periodo === 'total' ? '' : `do ${ROTULO_PERIODO[periodo]}`}`.trim()
  }

  interface Grupo { teamId: number; nome: string; valores: Array<number | null>; rotulos: string[]; topo?: boolean[]; jogos?: JogoDoTime[] }

  /* Uma série vira um quadro: barras jogo a jogo + "bateu X/N".
     Com `grupos`, a série é a soma de duas (os dois times, ou faz + cede), e o
     gráfico se divide em duas metades com escudo e nome · antes eram vinte
     barras seguidas e não dava pra saber de quem era cada uma. */
  /* A odd da casa pra exatamente esta seleção (mercado, de quem, tempo, linha). */
  const oddAtual = oddDaSelecao(odds, { mercado: id, quem, periodo, lado, linha })
  const comOdd = (s: Selecao, bateu: number, n: number, o: OddDaCasa | null): Selecao => ({
    ...s, bateu, n,
    ...(o ? { odd: o.odd, casa: o.casa, perna: s.perna ? { ...s.perna, odd: o.odd } : s.perna } : {}),
  })

  /* A dica de cada barra: os jogos daquela série e de qual time ela é. */
  const nomeDe = (id: number) => (id === f.home_team_id ? f.home_team : f.away_team)
  const dicaDe = (jogos: JogoDoTime[] | undefined, timeId: number | undefined, valores: Array<number | null>) =>
    jogos && timeId != null
      ? jogos.map((j, i) => (
          <DicaDoJogo key={j.fixture_id} j={j} timeId={timeId} timeNome={nomeDe(timeId)}
            rank={rank[String(j.adversario_id)]}
            valor={`${comPeriodo(mercado.frase, periodo)}: ${valores[i] ?? 'sem dado'}`} />
        ))
      : undefined

  const Quadro = ({ titulo, sub, teamId, nomeTime, valores, rotulos, topo, jogos, grupos, selecao, destaque }: {
    titulo: string; sub: string; teamId?: number; nomeTime?: string
    valores: Array<number | null>; rotulos?: string[]; topo?: boolean[]; jogos?: JogoDoTime[]; grupos?: Grupo[]
    selecao?: Selecao; destaque?: boolean
  }) => {
    const t = taxa(valores, linha, lado)
    /* Os 5 mais recentes de cada série (a lista vem do mais novo pro mais
       antigo) · só quando a série tem mais que 5, senão repetiria a média. */
    const ultimos = (grupos ? grupos.map(g => g.valores) : [valores]).flatMap(vs =>
      vs.length > 5 ? vs.filter(v => v != null).slice(0, 5) : [])
    const recente = ultimos.length ? taxa(ultimos, linha, lado).media : null
    /* CONTRA O TOP 6 (17/10/2026): a média só dos jogos contra os seis
       primeiros da tabela · time que só passa da linha contra os fracos
       aparece aqui. */
    const series = grupos ? grupos.map(g => [g.valores, g.topo] as const) : [[valores, topo] as const]
    const vsTopo = series.flatMap(([vs, tp]) => vs.filter((v, i): v is number => v != null && !!tp?.[i]))
    const mediaTopo = vsTopo.length ? vsTopo.reduce((a, b) => a + b, 0) / vsTopo.length : null
    const temTabela = series.some(([, tp]) => tp !== undefined)
    const maxComum = Math.max(linha + 1, ...valores.map(v => v ?? 0))
    return (
      <div className={cn('card p-4', destaque && 'border-accent/30')}>
        <div className="flex items-center gap-3 mb-3">
          {teamId != null && <TeamLogo id={teamId} name={nomeTime ?? ''} size={28} />}
          <div className="flex-1 min-w-0">
            <div className="text-sm font-bold text-ink-1 truncate">{titulo}</div>
            <div className="text-[11px] text-ink-3">{sub}</div>
          </div>
          <NumeroDaTaxa t={t} grande={destaque} semMedia />
          {selecao && !destaque && <BotaoBilhete selecao={{ ...selecao, bateu: t.bateu, n: t.n }} />}
        </div>
        {/* Taxa de acerto em barra: o X/N lido de relance. */}
        <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden mb-3">
          <div className={cn('h-full rounded-full', BARRA[tomDaTaxa(t.pct)])}
            style={{ width: `${Math.round((t.pct ?? 0) * 100)}%` }} />
        </div>
        {t.media != null && (
          <div className={cn('grid gap-2 mb-3', temTabela ? 'grid-cols-3' : 'grid-cols-2')}>
            <Indicador rotulo="Média" valor={t.media.toFixed(1)} detalhe="por jogo" />
            <Indicador rotulo="Últimos 5" valor={recente != null ? recente.toFixed(1) : '—'}
              detalhe={recente == null ? 'poucos jogos'
                : recente > t.media + 0.05 ? '▲ acima da média'
                : recente < t.media - 0.05 ? '▼ abaixo da média' : 'igual à média'} />
            {temTabela && (
              <Indicador rotulo="vs top 6" valor={mediaTopo != null ? mediaTopo.toFixed(1) : '—'}
                detalhe={vsTopo.length ? `${vsTopo.length} ${vsTopo.length === 1 ? 'jogo' : 'jogos'}` : 'nenhum jogo'} />
            )}
          </div>
        )}
        {grupos ? (
          /* Lado a lado só com poucos jogos: com a temporada inteira cada
             metade virava 30 barras de 4px. Aí um time embaixo do outro. */
          <div className={cn('grid gap-3', grupos.some(g => g.valores.length > 12) ? 'grid-cols-1 gap-y-4' : 'grid-cols-2')}>
            {grupos.map(g => {
              const tg = taxa(g.valores, linha, lado)
              return (
                <div key={g.nome} className="min-w-0">
                  <div className="flex items-center gap-1.5 mb-1.5 min-w-0">
                    <TeamLogo id={g.teamId} name={g.nome} size={16} />
                    <span className="text-[11px] font-semibold text-ink-2 truncate flex-1">{g.nome}</span>
                    {tg.media != null && (
                      <span className="font-mono text-[11px] text-ink-3 tabular-nums shrink-0">
                        média <b className="text-ink-1">{tg.media.toFixed(1)}</b>
                      </span>
                    )}
                    <span className={cn('font-mono text-[11px] font-black tabular-nums shrink-0', TOM[tomDaTaxa(tg.pct)])}>
                      {tg.n ? `${tg.bateu}/${tg.n}` : '—'}
                    </span>
                  </div>
                  <Barras valores={g.valores} rotulos={g.rotulos} topo={g.topo} dicas={dicaDe(g.jogos, g.teamId, g.valores)} linha={linha} lado={lado} max={maxComum} />
                </div>
              )
            })}
          </div>
        ) : (
          <Barras valores={valores} rotulos={rotulos} topo={topo} dicas={dicaDe(jogos, teamId, valores)} linha={linha} lado={lado} />
        )}
        {selecao && destaque && (
          <>
            <LinhaDaOdd odd={oddAtual} bateu={t.bateu} n={t.n} />
            <div className="mt-3"><BotaoBilhete cheio selecao={comOdd(selecao, t.bateu, t.n, oddAtual)} /></div>
          </>
        )}
      </div>
    )
  }

  /* Ambas marcam · Sim e · Não (14/10/2026): o "Não" é o mesmo histórico ao
     contrário · os jogos em que pelo menos um dos dois times passou em branco. */
  const btts = useMemo(() => {
    const serie = [...home.jogos, ...away.jogos].map(ambasMarcam).map(b => (b == null ? null : b ? 1 : 0))
    return { sim: taxa(serie, 0.5, 'mais'), nao: taxa(serie, 0.5, 'menos') }
  }, [home.jogos, away.jogos])

  /* Os dois times recebem cartão, 1+ e 2+ cada (17/10/2026, pedido do
     usuário) · a mesma conta do ambas marcam, com cartão no lugar de gol. */
  const cartaoDosDois = useMemo(() => ([1, 2] as const).map(minimo => {
    const serie = [...home.jogos, ...away.jogos].map(j => ambosRecebemCartao(j, minimo))
      .map(b => (b == null ? null : b ? 1 : 0))
    return { minimo, t: taxa(serie, 0.5, 'mais') }
  }), [home.jogos, away.jogos])

  /* ── mercado do JOGO: os dois times somados ── */
  const quadrosDoJogo = () => {
    const vHome = home.jogos.map(j => numero(j, mercado.contador, 'jogo', periodo))
    const vAway = away.jogos.map(j => numero(j, mercado.contador, 'jogo', periodo))
    const descricao = `${comPeriodo(mercado.frase, periodo)}, ${linhaTxt.toLowerCase()}`
    const selecao: Selecao = {
      id: `${f.fixture_id}:${id}:${periodo}:${lado}:${linha}`, fixture_id: f.fixture_id, jogo: nomeJogo,
      descricao, bateu: 0, n: 0,
      perna: { ...base, descricao, tipo: 'time', mercado: id, direcao: lado, linha, periodo },
    }
    return (
      <>
        <Quadro destaque titulo="Nos jogos dos dois times" sub={descricao}
          valores={[...vHome, ...vAway]} selecao={selecao}
          grupos={[
            { teamId: f.home_team_id, nome: f.home_team, valores: vHome, rotulos: rotulosDe(home.jogos), topo: topoDe(home.jogos), jogos: home.jogos },
            { teamId: f.away_team_id, nome: f.away_team, valores: vAway, rotulos: rotulosDe(away.jogos), topo: topoDe(away.jogos), jogos: away.jogos },
          ]} />
        <Quadro titulo={f.home_team} sub={amostra(vHome)} teamId={f.home_team_id}
          nomeTime={f.home_team} valores={vHome} rotulos={rotulosDe(home.jogos)} topo={topoDe(home.jogos)} jogos={home.jogos} />
        <Quadro titulo={f.away_team} sub={amostra(vAway)} teamId={f.away_team_id}
          nomeTime={f.away_team} valores={vAway} rotulos={rotulosDe(away.jogos)} topo={topoDe(away.jogos)} jogos={away.jogos} />
      </>
    )
  }

  /* ── mercado DO TIME: o que ele faz x o que o adversário cede ──
     É a leitura que quem aposta "escanteios do time" faz de cabeça: o mandante
     costuma ter quantos, e o visitante costuma deixar quantos. Os dois juntos
     são a amostra do confronto. */
  const quadrosDoTime = () => {
    const ehCasa = timeFoco === 'home'
    const time = ehCasa ? home : away
    const adv = ehCasa ? away : home
    const nomeTime = ehCasa ? f.home_team : f.away_team
    const nomeAdv = ehCasa ? f.away_team : f.home_team
    const faz = time.jogos.map(j => numero(j, mercado.contador, 'pro', periodo))
    const cede = adv.jogos.map(j => numero(j, mercado.contador, 'contra', periodo))
    const descricao = `${comPeriodo(`${mercado.frase} do ${nomeTime}`, periodo)}, ${linhaTxt.toLowerCase()}`
    const selecao: Selecao = {
      id: `${f.fixture_id}:${id}:${timeFoco}:${periodo}:${lado}:${linha}`, fixture_id: f.fixture_id,
      jogo: nomeJogo, descricao, bateu: 0, n: 0,
      perna: { ...base, descricao, tipo: 'time', mercado: id, direcao: lado, linha, periodo, lado_time: timeFoco },
    }
    return (
      <>
        <Quadro destaque titulo="No confronto" sub={`${nomeTime} faz + ${nomeAdv} cede`}
          valores={[...faz, ...cede]} selecao={selecao}
          grupos={[
            { teamId: ehCasa ? f.home_team_id : f.away_team_id, nome: `${nomeTime} faz`, valores: faz, rotulos: rotulosDe(time.jogos), topo: topoDe(time.jogos), jogos: time.jogos },
            { teamId: ehCasa ? f.away_team_id : f.home_team_id, nome: `${nomeAdv} cede`, valores: cede, rotulos: rotulosDe(adv.jogos), topo: topoDe(adv.jogos), jogos: adv.jogos },
          ]} />
        <Quadro titulo={`${nomeTime} faz`} sub={`${mercado.frase.toLowerCase()} a favor, ${amostra(faz)}`}
          teamId={ehCasa ? f.home_team_id : f.away_team_id} nomeTime={nomeTime} valores={faz} rotulos={rotulosDe(time.jogos)} topo={topoDe(time.jogos)} jogos={time.jogos} />
        <Quadro titulo={`${nomeAdv} cede`} sub={`${mercado.frase.toLowerCase()} contra, ${amostra(cede)}`}
          teamId={ehCasa ? f.away_team_id : f.home_team_id} nomeTime={nomeAdv} valores={cede} rotulos={rotulosDe(adv.jogos)} topo={topoDe(adv.jogos)} jogos={adv.jogos} />
      </>
    )
  }

  /* Resultado primeiro, depois Gols: a ordem de qualquer casa de aposta. */
  const chips = [{ id: 'resultado', rotulo: 'Resultado' }, ...MERCADOS_PRINCIPAIS.map(m => ({ id: m.id, rotulo: m.rotulo }))]

  if (ehResultado) {
    return (
      <div className="space-y-3">
        <SeletoresDoRaioX opcoes={chips} valor={principal} onChange={setPrincipal} rotulo="Mercado"
          mando={mando} setMando={setMando} />
        <QuadrosDeResultado dados={dados} nomeJogo={nomeJogo} odds={odds} oddsAoVivo={oddsAoVivo} />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <SeletoresDoRaioX opcoes={chips} valor={principal} onChange={setPrincipal} rotulo="Mercado"
        mando={mando} setMando={setMando} />

      <div className="card p-3 space-y-3">
        {/* DE QUEM: os dois times somados, ou um só (faz x cede). */}
        <div className="grid grid-cols-3 rounded-lg border border-line p-0.5 bg-surface-1">
          {([
            ['jogo', 'Os dois', null],
            ['home', f.home_team, f.home_team_id],
            ['away', f.away_team, f.away_team_id],
          ] as const).map(([k, rotulo, tid]) => (
            <button key={k} onClick={() => setQuem(k)} aria-pressed={quem === k}
              className={cn('h-10 rounded-md text-sm font-bold transition-colors flex items-center justify-center gap-1.5 px-1 min-w-0',
                quem === k ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
              {tid != null && <TeamLogo id={tid} name={rotulo} size={18} />}
              <span className="truncate">{rotulo}</span>
            </button>
          ))}
        </div>
        {/* Tempo do jogo · 1º e 2º tempo saem da folha do 1º tempo. */}
        <div className="grid grid-cols-3 rounded-lg border border-line p-0.5 bg-surface-1">
          {(['total', '1t', '2t'] as Periodo[]).map(p => (
            <button key={p} onClick={() => setPeriodo(p)} disabled={mercado.soTotal && p !== 'total'}
              className={cn('h-10 rounded-md text-sm font-bold transition-colors disabled:opacity-30',
                periodo === p ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
              {ROTULO_PERIODO[p]}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex rounded-lg border border-line p-0.5 bg-surface-1">
            {(['mais', 'menos'] as Lado[]).map(l => (
              <button key={l} onClick={() => setLado(l)}
                className={cn('h-10 px-4 rounded-md text-sm font-bold transition-colors',
                  lado === l ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
                {l === 'mais' ? 'Mais de' : 'Menos de'}
              </button>
            ))}
          </div>
          <Passo rotulo={linhaTxt} onMenos={() => mudarLinha(-1)} onMais={() => mudarLinha(1)}
            desabilitaMenos={linha <= 0.5} />
        </div>
        {mercado.soTotal && (
          <p className="text-[11px] text-ink-3">{par.rotulo} só no jogo todo.</p>
        )}
      </div>

      {mercado.escopo === 'jogo' ? quadrosDoJogo() : quadrosDoTime()}

      {mercado.contador === 'amarelos' && periodo === 'total' && dados.arbitro && (
        <CartaoDoArbitro arbitro={dados.arbitro} linha={linha} lado={lado} />
      )}

      {mercado.contador === 'amarelos' && periodo === 'total' && (
        <div className="card p-4 divide-y divide-line/60">
          {cartaoDosDois.map(({ minimo, t }) => {
            const descricao = minimo === 1 ? 'Os dois times recebem cartão' : 'Os dois times recebem 2+ cartões'
            /* Com este árbitro (17/10/2026): cartão depende muito de quem
               apita, e os jogos dele já vêm no Raio-X. */
            const doArbitro = taxa((dados.arbitro?.jogos ?? []).map(j => j.cartoes_menor ?? null), minimo - 0.5, 'mais')
            return (
              <div key={minimo} className={minimo === 2 ? 'pt-3 mt-3' : undefined}>
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    {minimo === 1 && (
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Também no jogo</div>
                    )}
                    <div className="text-base font-bold text-ink-1 mt-0.5">{descricao}</div>
                  </div>
                  <NumeroDaTaxa t={t} semMedia />
                  <BotaoBilhete selecao={{
                    id: `${f.fixture_id}:ambas_cartao:${minimo}`, fixture_id: f.fixture_id, jogo: nomeJogo,
                    descricao, bateu: t.bateu, n: t.n,
                    perna: { ...base, descricao, tipo: 'time', mercado: 'ambas_cartao', minimo },
                  }} />
                </div>
                {doArbitro.n > 0 && (
                  <div className="mt-1.5 text-[11px] text-ink-3 tabular-nums">
                    Com {dados.arbitro!.nome}: <b className={TOM[tomDaTaxa(doArbitro.pct)]}>{doArbitro.bateu}/{doArbitro.n}</b>
                    {doArbitro.pct != null && ` (${Math.round(doArbitro.pct * 100)}%)`}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {id === 'gols' && periodo === 'total' && (
        <div className="card p-4 divide-y divide-line/60">
          {(['sim', 'nao'] as const).map(escolha => {
            const t = btts[escolha]
            const descricao = `Ambas marcam: ${escolha === 'sim' ? 'Sim' : 'Não'}`
            const odd = oddDaSelecao(odds, { mercado: 'btts', quem: 'jogo', periodo: 'total', escolha })
            return (
              <div key={escolha} className={escolha === 'nao' ? 'pt-3 mt-3' : undefined}>
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    {escolha === 'sim' && (
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Também no jogo</div>
                    )}
                    <div className="text-base font-bold text-ink-1 mt-0.5">{descricao}</div>
                  </div>
                  {/* Sim/não: a "média" seria a de zeros e uns, não diz nada. */}
                  <NumeroDaTaxa t={t} semMedia />
                  <BotaoBilhete selecao={comOdd({
                    id: `${f.fixture_id}:btts${escolha === 'nao' ? ':nao' : ''}`, fixture_id: f.fixture_id, jogo: nomeJogo,
                    descricao, bateu: t.bateu, n: t.n,
                    perna: { ...base, descricao, tipo: 'time', mercado: 'btts',
                             ...(escolha === 'nao' ? { escolha: 'nao' } : {}) },
                  }, t.bateu, t.n, odd)} />
                </div>
                <LinhaDaOdd odd={odd} bateu={t.bateu} n={t.n} />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/*
 * Resultado final e chance dupla (2026-10-09, pedido do usuário).
 *
 * NO JEITO DA CASA DE APOSTA: três botões lado a lado, mandante · empate ·
 * visitante, cada um com a odd e a taxa dos últimos jogos, e o toque põe ou
 * tira do bilhete. Embaixo, a forma dos dois, que é de onde a taxa sai.
 *
 * Sem linha nem tempo: só o jogo todo, pelo placar dos 90 minutos, que é como
 * a casa liquida e como bilhete_pessoal.py confere. A taxa soma os dois lados
 * (o mandante vencendo nos jogos dele + o visitante perdendo nos dele).
 */
function QuadrosDeResultado({ dados, nomeJogo, odds, oddsAoVivo }: {
  dados: RaioX; nomeJogo: string; odds: OddDaCasa[]; oddsAoVivo: boolean
}) {
  const f = dados.fixture
  const { home, away } = dados.times
  const escudoCasa = <TeamLogo id={f.home_team_id} name={f.home_team} size={24} />
  const escudoFora = <TeamLogo id={f.away_team_id} name={f.away_team} size={24} />
  const xis = (
    <span className="w-6 h-6 grid place-items-center rounded-full bg-surface-3 text-ink-2 text-[11px] font-black">X</span>
  )
  const props = { f, home: home.jogos, away: away.jogos, nomeJogo, odds }

  /* Chance de cada lado: pelas odds (sem a margem da casa) quando as três
     existem; senão pelos últimos jogos, normalizado pra somar 100. */
  const pelasOdds = chanceDoResultado(odds)
  const pelaForma = (() => {
    const pct = (e: EscolhaDeResultado) => taxa([
      ...serieDeResultado(home.jogos, RESULTADOS_ACEITOS[e].home),
      ...serieDeResultado(away.jogos, RESULTADOS_ACEITOS[e].away)], 0.5, 'mais').pct ?? 0
    const [c, e, fo] = [pct('1'), pct('X'), pct('2')]
    const soma = c + e + fo
    return soma ? { casa: c / soma, empate: e / soma, fora: fo / soma } : null
  })()
  const chance = pelasOdds ?? pelaForma

  return (
    <>
      {chance && (
        <div className="card p-4">
          <div className="flex items-baseline justify-between gap-2 mb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Probabilidade de vitória</span>
            {pelasOdds && oddsAoVivo ? (
              <span className="flex items-center gap-1.5 text-[11px] font-bold text-red-400">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" /> odds ao vivo
              </span>
            ) : (
              <span className="text-[11px] text-ink-4">{pelasOdds ? 'pelas odds das casas' : 'pelos últimos jogos'}</span>
            )}
          </div>
          <div className="grid grid-cols-3 items-end text-center mb-2">
            {([
              [f.home_team_id, f.home_team, chance.casa, 'text-accent-ink'],
              [null, 'Empate', chance.empate, 'text-ink-2'],
              [f.away_team_id, f.away_team, chance.fora, 'text-sky-400'],
            ] as const).map(([id, nome, p, cor]) => (
              <div key={nome} className="min-w-0 flex flex-col items-center gap-1">
                {id != null ? <TeamLogo id={id} name={nome} size={28} /> : xis}
                <span className={cn('font-mono text-2xl font-black tabular-nums leading-none', cor)}>{Math.round(p * 100)}%</span>
                <span className="w-full text-[11px] text-ink-3 truncate px-1">{nome}</span>
              </div>
            ))}
          </div>
          <div className="flex h-2 rounded-full overflow-hidden gap-0.5" aria-hidden>
            <div className="bg-accent" style={{ width: `${chance.casa * 100}%` }} />
            <div className="bg-surface-3" style={{ width: `${chance.empate * 100}%` }} />
            <div className="bg-sky-400" style={{ width: `${chance.fora * 100}%` }} />
          </div>
        </div>
      )}

      <div className="card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3 mb-3">Resultado final</div>
        <div className="grid grid-cols-3 gap-2">
          <BotaoDeResultado {...props} escolha="1" prefixo="Resultado final" rotulo={`${f.home_team} vence`}
            curto={f.home_team} escudo={escudoCasa} />
          <BotaoDeResultado {...props} escolha="X" prefixo="Resultado final" rotulo="Empate"
            curto="Empate" escudo={xis} />
          <BotaoDeResultado {...props} escolha="2" prefixo="Resultado final" rotulo={`${f.away_team} vence`}
            curto={f.away_team} escudo={escudoFora} />
        </div>
      </div>

      <div className="card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3 mb-3">Chance dupla</div>
        <div className="grid grid-cols-3 gap-2">
          <BotaoDeResultado {...props} escolha="1X" prefixo="Chance dupla" rotulo={`${f.home_team} ou empate`}
            curto="Casa ou empate" escudo={<span className="flex -space-x-1.5">{escudoCasa}{xis}</span>} />
          <BotaoDeResultado {...props} escolha="12" prefixo="Chance dupla" rotulo={`${f.home_team} ou ${f.away_team}`}
            curto="Casa ou fora" escudo={<span className="flex -space-x-1.5">{escudoCasa}{escudoFora}</span>} />
          <BotaoDeResultado {...props} escolha="X2" prefixo="Chance dupla" rotulo={`Empate ou ${f.away_team}`}
            curto="Empate ou fora" escudo={<span className="flex -space-x-1.5">{xis}{escudoFora}</span>} />
        </div>
      </div>

      {/* De onde a taxa sai: a forma dos dois, do jogo mais antigo pro mais recente. */}
      <div className="card p-4 space-y-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Últimos jogos</div>
        {([['home', f.home_team_id, f.home_team, home.jogos], ['away', f.away_team_id, f.away_team, away.jogos]] as const)
          .map(([lado, id, nome, jogos]) => {
            const conta = { V: 0, E: 0, D: 0 }
            for (const j of jogos) { const r = resultadoDoJogo(j); if (r) conta[r]++ }
            return (
              <div key={lado} className="min-w-0">
                <div className="flex items-center gap-1.5 mb-1.5 min-w-0">
                  <TeamLogo id={id} name={nome} size={16} />
                  <span className="text-xs font-semibold text-ink-1 truncate flex-1">{nome}</span>
                  <span className="text-[11px] text-ink-3 tabular-nums shrink-0">{conta.V}V {conta.E}E {conta.D}D</span>
                </div>
                <div className="flex gap-[3px]">
                  {[...jogos].reverse().map(j => {
                    const r = resultadoDoJogo(j)
                    const legenda = `${j.em_casa ? 'vs' : '@'} ${j.adversario || 'adversário'}, ${dataCurta(j.data)}, ${j.gols_pro ?? '-'}-${j.gols_contra ?? '-'}`
                    return (
                      <Tooltip key={j.fixture_id} className="flex-1 max-w-[28px]"
                        text={<DicaDoJogo j={j} timeId={id} timeNome={nome} rank={dados.rank_adversarios?.[String(j.adversario_id)]} />}>
                        <button type="button" aria-label={legenda}
                          className={cn('w-full h-6 grid place-items-center rounded-sm text-[10px] font-black cursor-default',
                            r === 'V' ? 'bg-green-500 text-on-fill' : r === 'D' ? 'bg-red-500 text-on-fill'
                              : r === 'E' ? 'bg-surface-3 text-ink-2' : 'border border-line')}>
                          {r ?? ''}
                        </button>
                      </Tooltip>
                    )
                  })}
                </div>
              </div>
            )
          })}
        <p className="text-[11px] text-ink-3">
          Pelo placar dos 90 minutos.
        </p>
      </div>
    </>
  )
}

/** Um botão do jeito da casa: escudo, nome, odd grande e a taxa embaixo. O toque põe/tira do bilhete. */
function BotaoDeResultado({ f, home, away, nomeJogo, odds, escolha, prefixo, rotulo, curto, escudo }: {
  f: RaioX['fixture']; home: JogoDoTime[]; away: JogoDoTime[]; nomeJogo: string; odds: OddDaCasa[]
  escolha: EscolhaDeResultado; prefixo: string; rotulo: string; curto: string; escudo: ReactNode
}) {
  const bilhete = useBilheteMontado()
  const aceitos = RESULTADOS_ACEITOS[escolha]
  const t = taxa([...serieDeResultado(home, aceitos.home), ...serieDeResultado(away, aceitos.away)], 0.5, 'mais')
  const odd = oddDaSelecao(odds, { mercado: 'resultado', quem: 'jogo', periodo: 'total', escolha })
  const v = vantagem(t.bateu, t.n, odd?.odd)
  const descricao = `${prefixo}: ${rotulo}`
  const selecao: Selecao = {
    id: `${f.fixture_id}:resultado:${escolha}`, fixture_id: f.fixture_id, jogo: nomeJogo,
    descricao, bateu: t.bateu, n: t.n,
    ...(odd ? { odd: odd.odd, casa: odd.casa } : {}),
    perna: {
      fixture_id: f.fixture_id, home_team_id: f.home_team_id, away_team_id: f.away_team_id,
      home: f.home_team, away: f.away_team,
      descricao, tipo: 'time', mercado: 'resultado', escolha, ...(odd ? { odd: odd.odd } : {}),
    },
  }
  const dentro = bilhete.some(s => s.id === selecao.id)
  const legenda = `${rotulo}${odd ? `, odd ${odd.odd.toFixed(2)}${odd.casa ? ` (${odd.casa})` : ''}` : ''}, bateu ${t.bateu} de ${t.n}`

  return (
    <button onClick={() => trocarNoGrupo(selecao, `${f.fixture_id}:resultado:`)} aria-pressed={dentro} title={legenda}
      aria-label={`${dentro ? 'Tirar das minhas seleções' : 'Separar nas minhas seleções'}: ${legenda}`}
      className={cn(
        'relative min-w-0 rounded-lg border px-1.5 pt-2.5 pb-2 flex flex-col items-center gap-1 text-center transition active:scale-95',
        dentro ? 'bg-accent/15 border-accent' : 'bg-surface-1 border-line hover:border-line-strong',
      )}>
      {dentro && <Check size={14} className="absolute top-1.5 right-1.5 text-accent-ink" />}
      <span className="h-6 flex items-center">{escudo}</span>
      <span className="w-full text-[11px] font-semibold text-ink-2 truncate">{curto}</span>
      <span className={cn('font-mono text-lg font-black tabular-nums leading-none', dentro ? 'text-accent-ink' : 'text-ink-1')}>
        {odd ? odd.odd.toFixed(2) : '—'}
      </span>
      <span className={cn('text-[11px] font-bold tabular-nums', TOM[tomDaTaxa(t.pct)])}>
        {t.n ? `${t.bateu}/${t.n} (${Math.round((t.pct ?? 0) * 100)}%)` : 'sem dado'}
      </span>
      {v != null && v >= 0.05 && (
        <span className="text-[10px] font-bold px-1.5 rounded bg-accent/15 text-accent-ink border border-accent/40">
          Valor +{Math.round(v * 100)}%
        </span>
      )}
    </button>
  )
}

function CartaoDoArbitro({ arbitro, linha, lado }: { arbitro: NonNullable<RaioX['arbitro']>; linha: number; lado: Lado }) {
  const t = taxa(arbitro.jogos.map(j => j.amarelos), linha, lado)
  return (
    <div className="card p-4">
      <div className="flex items-center gap-3 mb-3">
        <span className="w-9 h-9 grid place-items-center rounded-full bg-yellow-400/15 text-yellow-400 shrink-0"><Flag size={18} /></span>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Árbitro</div>
          <div className="text-sm font-bold text-ink-1 truncate">{arbitro.nome}</div>
        </div>
        <NumeroDaTaxa t={t} />
      </div>
      {arbitro.jogos.length > 0
        ? <Barras valores={arbitro.jogos.map(j => j.amarelos)} linha={linha} lado={lado}
            dicas={arbitro.jogos.map((j, i) => j.home_team_id && j.away_team_id ? (
              <DicaDePartida key={i}
                casa={{ id: j.home_team_id, nome: j.home_team || 'Mandante', gols: j.home_goals ?? null }}
                fora={{ id: j.away_team_id, nome: j.away_team || 'Visitante', gols: j.away_goals ?? null }}
                detalhe={dataCurta(j.data ?? null)} valor={`Cartões amarelos: ${j.amarelos}`} />
            ) : null)} />
        : <p className="text-xs text-ink-3">Sem jogos dele no histórico das nossas ligas.</p>}
    </div>
  )
}

/* ── Jogadores ──────────────────────────────────────────────────────────── */

/* De onde veio o "titular provável", na língua de quem lê (o backend manda a
   chave sem acento). */
const FONTE_TITULARES: Record<string, string> = {
  'escalacao oficial': 'escalação oficial do jogo',
  'escalacao provavel': 'escalação provável do jogo',
  'escalacao do jogo': 'escalação do jogo',
  'ultima escalacao': 'última escalação do time',
}

function AbaJogadores({ dados, nomeJogo, mando, setMando }: {
  dados: RaioX; nomeJogo: string; mando: Mando; setMando: (m: Mando) => void
}) {
  const [time, setTime] = useState<'home' | 'away'>('home')
  const [estatId, setEstatId] = useState<EstatDeJogador['id']>('chutes_alvo')
  const estat = ESTATS_DE_JOGADOR.find(e => e.id === estatId)!
  const [minimos, setMinimos] = useState<Record<string, number>>({})
  const minimo = minimos[estatId] ?? estat.minimoPadrao
  const { fonte_titulares, lista } = dados.jogadores[time]
  const f = dados.fixture
  /* Os jogos do time por fixture, pra dica de cada quadradinho do jogador. */
  const doTime = useMemo(() => ({
    porFixture: new Map(dados.times[time].jogos.map(j => [j.fixture_id, j] as const)),
    timeId: time === 'home' ? f.home_team_id : f.away_team_id,
    timeNome: time === 'home' ? f.home_team : f.away_team,
    rank: dados.rank_adversarios ?? {},
  }), [dados, time, f])

  /* Goleiro só aparece em Defesas, e Defesas só mostra goleiro: zagueiro com
     "0 defesas" em dez jogos é uma linha inteira dizendo nada. Quem jogou um
     jogo só fica pro fim · 1/1 não é tendência, é anedota. */
  const jogadores = useMemo(() => {
    const filtrados = lista.filter(j => (estat.soGoleiro ? ehGoleiro(j) : !ehGoleiro(j)))
    return filtrados
      .map(j => ({ j, t: taxaDoJogador(j, estatId, minimo) }))
      .sort((a, b) =>
        Number(b.j.titular_provavel) - Number(a.j.titular_provavel)
        || Number(b.t.n >= 3) - Number(a.t.n >= 3)
        || (b.t.pct ?? -1) - (a.t.pct ?? -1)
        || b.j.minutos_total - a.j.minutos_total)
  }, [lista, estatId, minimo, estat.soGoleiro])

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {(['home', 'away'] as const).map(t => {
          const id = t === 'home' ? f.home_team_id : f.away_team_id
          const nome = t === 'home' ? f.home_team : f.away_team
          return (
            <button key={t} onClick={() => setTime(t)}
              className={cn('h-12 rounded-lg border flex items-center justify-center gap-2 px-2 text-sm font-bold transition-colors min-w-0',
                time === t ? 'bg-surface-2 border-line-strong text-ink-1' : 'bg-surface-1 border-line text-ink-3')}>
              <TeamLogo id={id} name={nome} size={22} />
              <span className="truncate">{nome}</span>
            </button>
          )
        })}
      </div>

      <SeletoresDoRaioX opcoes={ESTATS_DE_JOGADOR.map(e => ({ id: e.id, rotulo: e.rotulo }))} valor={estatId}
        onChange={v => setEstatId(v as EstatDeJogador['id'])} rotulo="Estatística" mando={mando} setMando={setMando} />

      <div className="card p-3 flex items-center justify-between gap-3">
        <span className="text-sm text-ink-2">Em cada jogo</span>
        <Passo rotulo={fraseDoJogador(estat, minimo)}
          onMenos={() => setMinimos(m => ({ ...m, [estatId]: Math.max(1, minimo - 1) }))}
          onMais={() => setMinimos(m => ({ ...m, [estatId]: minimo + 1 }))}
          desabilitaMenos={minimo <= 1} />
      </div>

      {fonte_titulares && (
        <p className="flex items-center gap-1.5 text-[11px] text-ink-3 px-1">
          <Shield size={12} /> Titular provável: {FONTE_TITULARES[fonte_titulares] ?? fonte_titulares}.
        </p>
      )}

      {jogadores.length === 0 ? (
        <div className="card p-8 text-center">
          <Users className="mx-auto text-ink-4 mb-2" size={22} />
          <p className="text-sm text-ink-2">Sem estatística de jogador desse time nos últimos jogos.</p>
          <p className="text-xs text-ink-3 mt-1">Por enquanto só nas ligas principais.</p>
        </div>
      ) : (
        <div className="card divide-y divide-line/60 overflow-hidden">
          {jogadores.map(({ j, t }) => (
            <div key={j.player_id} className="p-3 flex items-center gap-3">
              <PlayerPhoto id={j.player_id} name={j.nome} size={44} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="text-sm font-bold text-ink-1 truncate">{j.nome}</span>
                  {j.posicao && <span className="text-[10px] font-bold text-ink-3 border border-line rounded px-1 shrink-0">{j.posicao}</span>}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  {j.titular_provavel && <span className="text-[10px] font-bold text-accent-ink">Titular provável</span>}
                  <span className="text-[11px] text-ink-3">{j.jogos.length} jogos</span>
                </div>
                <div className="mt-1 max-w-[200px]"><MiniSerie jogos={j} estat={estatId} minimo={minimo} doTime={doTime} /></div>
              </div>
              <NumeroDaTaxa t={t} />
              <BotaoBilhete selecao={{
                id: `${f.fixture_id}:p${j.player_id}:${estatId}:${minimo}`, fixture_id: f.fixture_id, jogo: nomeJogo,
                descricao: `${j.nome}: ${fraseDoJogador(estat, minimo)}`, bateu: t.bateu, n: t.n, player_id: j.player_id,
                perna: {
                  fixture_id: f.fixture_id, home_team_id: f.home_team_id, away_team_id: f.away_team_id,
                  home: f.home_team, away: f.away_team, descricao: `${j.nome}: ${fraseDoJogador(estat, minimo)}`,
                  tipo: 'jogador', estat: estatId, minimo, player_id: j.player_id, player_name: j.nome,
                },
              }} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Quadradinhos por jogo do jogador: verde bateu, cinza não, vazado sem dado.
 *  Com `doTime`, cada um abre a dica do jogo (adversário, dia, placar). */
function MiniSerie({ jogos, estat, minimo, doTime }: {
  jogos: Jogador; estat: EstatDeJogador['id']; minimo: number
  doTime?: { porFixture: Map<number, JogoDoTime>; timeId: number; timeNome: string; rank: Record<string, number> }
}) {
  const rotulo = ESTATS_DE_JOGADOR.find(e => e.id === estat)?.rotulo ?? ''
  return (
    <div className="flex gap-[3px]">
      {[...jogos.jogos].reverse().map((g, i) => {
        const v = g[estat]
        const quadrado = (
          <span title={doTime ? undefined : v == null ? 'sem dado' : String(v)}
            className={cn('block w-full h-2 rounded-[2px]',
              v == null ? 'border border-line' : v >= minimo ? 'bg-green-500' : 'bg-surface-3')} />
        )
        const jogo = doTime?.porFixture.get(g.fixture_id)
        if (!jogo || !doTime) return <span key={i} className="flex-1 max-w-[14px] py-1">{quadrado}</span>
        return (
          /* py-1: o quadrado tem 8px, o toque precisa de mais. */
          <Tooltip key={i} className="flex-1 max-w-[14px]"
            text={<DicaDoJogo j={jogo} timeId={doTime.timeId} timeNome={doTime.timeNome}
              rank={doTime.rank[String(jogo.adversario_id)]}
              valor={`${rotulo}: ${v ?? 'sem dado'}${g.minutos ? `, ${g.minutos} min` : ''}`} />}>
            <button type="button" aria-label={`${jogo.adversario}: ${v ?? 'sem dado'}`} className="w-full py-1 cursor-default">
              {quadrado}
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}

/* ── Confronto ──────────────────────────────────────────────────────────── */

/* Por TEXTO, e não `new Date()`: "2025-03-10" sem hora é lido como meia-noite
   UTC, e no fuso de Brasília vira 09/03 · o jogo aparecia um dia antes. */
function dataCurta(iso: string | null): string {
  const m = iso?.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[3]}/${m[2]}/${m[1].slice(2)}` : ''
}

/*
 * CONFRONTO, NA LÓGICA DO SOFASCORE (14/10/2026, pedido do usuário).
 *
 * Três vistas: os últimos jogos do mandante, o confronto direto (H2H) e os
 * últimos jogos do visitante · quando os dois nunca se enfrentaram, a aba
 * ainda diz como cada um chega. Dois filtros: "esta competição" e o mando
 * (no estádio do mandante, no H2H; em casa / fora, na vista de um time). A
 * lista vem agrupada por competição, e os números de cima saem do recorte.
 */
type VistaConfronto = 'home' | 'h2h' | 'away'

function AbaConfronto({ dados }: { dados: RaioX }) {
  const f = dados.fixture
  const ultimos = dados.ultimos_todas ?? { home: [], away: [] }
  const [vista, setVista] = useState<VistaConfronto>(dados.h2h.length ? 'h2h' : 'home')
  const [soEsta, setSoEsta] = useState(false)
  const [noMando, setNoMando] = useState(false)

  const nomeTime = (id: number) =>
    id === f.home_team_id ? f.home_team : id === f.away_team_id ? f.away_team : (dados.nomes_times?.[id] ?? '')
  const nomeLiga = (id: number | null | undefined) =>
    id == null ? 'Outras competições' : nomeDaLigaPt(id, dados.nomes_ligas?.[id])

  /* De quem é o ponto de vista: no H2H, o mandante de hoje; numa vista de
     time, aquele time. */
  const foco = vista === 'away' ? f.away_team_id : f.home_team_id
  const base: JogoCurto[] = vista === 'h2h' ? dados.h2h : ultimos[vista]
  const jogos = base.filter(j =>
    (!soEsta || (f.league_id != null && j.league_id === f.league_id))
    && (!noMando || (vista === 'away' ? j.away_team_id === foco : j.home_team_id === foco)))

  const resultado = (j: JogoCurto): 'V' | 'E' | 'D' | null => {
    if (j.home_goals == null || j.away_goals == null) return null
    const pro = j.home_team_id === foco ? j.home_goals : j.away_goals
    const contra = j.home_team_id === foco ? j.away_goals : j.home_goals
    return pro > contra ? 'V' : pro < contra ? 'D' : 'E'
  }
  let v = 0, e = 0, d = 0
  for (const j of jogos) {
    const r = resultado(j)
    if (r === 'V') v++
    else if (r === 'D') d++
    else if (r === 'E') e++
  }
  const comPlacar = jogos.filter(j => j.home_goals != null && j.away_goals != null)
  const gols = comPlacar.map(j => j.home_goals! + j.away_goals!)
  const esc = jogos.map(j => j.escanteios).filter((x): x is number => x != null)
  const cart = jogos.map(j => j.amarelos).filter((x): x is number => x != null)
  const media = (xs: number[]) => (xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(1) : '—')
  const pct = (n: number) => (comPlacar.length ? `${Math.round((n / comPlacar.length) * 100)}%` : '—')
  const numeros: Array<[ReactNode, string, string]> = [
    [<Goal key="g" className="w-4 h-4" />, media(gols), 'gols/jogo'],
    [<Flag key="e" className="w-4 h-4" />, media(esc), 'escanteios/jogo'],
    [<Square key="c" className="w-4 h-4" />, media(cart), 'cartões/jogo'],
    [<Repeat key="a" className="w-4 h-4" />, pct(comPlacar.filter(j => j.home_goals! > 0 && j.away_goals! > 0).length), 'ambas marcam'],
    [<TrendingUp key="o" className="w-4 h-4" />, pct(gols.filter(g => g > 2.5).length), 'mais de 2.5'],
  ]

  /* Agrupa por competição, na ordem do jogo mais recente de cada uma. */
  const grupos: Array<{ liga: number | null; jogos: JogoCurto[] }> = []
  for (const j of jogos) {
    const liga = j.league_id ?? null
    const g = grupos.find(x => x.liga === liga)
    if (g) g.jogos.push(j)
    else grupos.push({ liga, jogos: [j] })
  }

  const rotuloMando = vista === 'h2h' ? `No estádio do ${f.home_team}`
    : vista === 'home' ? 'Só em casa' : 'Só fora de casa'
  const placarDe = vista === 'h2h' ? [[v, f.home_team, f.home_team_id], [e, 'Empates', null], [d, f.away_team, f.away_team_id]] as const
    : [[v, 'Vitórias', null], [e, 'Empates', null], [d, 'Derrotas', null]] as const

  const Caixa = ({ marcado, set, rotulo, desligado }: {
    marcado: boolean; set: (b: boolean) => void; rotulo: string; desligado?: boolean
  }) => (
    <button onClick={() => set(!marcado)} disabled={desligado} aria-pressed={marcado}
      className={cn('h-10 px-3 rounded-lg border text-sm font-semibold flex items-center gap-2 min-w-0 transition-colors disabled:opacity-30',
        marcado ? 'border-accent/50 bg-accent/10 text-ink-1' : 'border-line text-ink-3')}>
      <span className={cn('w-4 h-4 shrink-0 rounded grid place-items-center border',
        marcado ? 'bg-accent border-accent text-on-fill' : 'border-line-strong')} aria-hidden>
        {marcado && <Check className="w-3 h-3" />}
      </span>
      <span className="truncate">{rotulo}</span>
    </button>
  )

  return (
    <div className="space-y-3">
      <div className="card p-3 space-y-2">
        {/* [mandante] [H2H] [visitante] */}
        <div className="grid grid-cols-3 rounded-lg border border-line p-0.5 bg-surface-1">
          {([
            ['home', f.home_team, f.home_team_id],
            ['h2h', 'H2H', null],
            ['away', f.away_team, f.away_team_id],
          ] as const).map(([k, rotulo, id]) => (
            <button key={k} onClick={() => setVista(k)} aria-pressed={vista === k}
              className={cn('h-10 rounded-md text-sm font-bold transition-colors flex items-center justify-center gap-1.5 px-1 min-w-0',
                vista === k ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
              {id != null && <TeamLogo id={id} name={rotulo} size={18} />}
              <span className="truncate">{rotulo}</span>
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Caixa marcado={noMando} set={setNoMando} rotulo={rotuloMando} />
          <Caixa marcado={soEsta} set={setSoEsta} rotulo="Esta competição" desligado={f.league_id == null} />
        </div>
      </div>

      {!jogos.length ? (
        <div className="card p-8 text-center text-sm text-ink-2">
          {vista === 'h2h' && !dados.h2h.length
            ? 'Os dois ainda não se enfrentaram. Veja os últimos jogos de cada um nos escudos acima.'
            : 'Nenhum jogo neste recorte.'}
        </div>
      ) : (
        <>
          <div className="card p-4">
            <div className="grid grid-cols-3 text-center">
              {placarDe.map(([n, r, id], i) => (
                <div key={i} className="min-w-0 flex flex-col items-center">
                  {id != null && <TeamLogo id={id} name={r} size={22} />}
                  <div className={cn('font-mono text-3xl font-black tabular-nums', id != null && 'mt-1',
                    i === 1 ? 'text-ink-2' : 'text-ink-1')}>{n}</div>
                  <div className="text-[11px] text-ink-3 truncate px-1 max-w-full">{r}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-line grid grid-cols-2 sm:grid-cols-5 gap-3">
              {numeros.map(([icone, valor, rotulo]) => (
                <div key={rotulo} className="flex items-center gap-2 min-w-0">
                  <span className="w-8 h-8 shrink-0 grid place-items-center rounded-lg bg-surface-2 text-ink-2" aria-hidden>{icone}</span>
                  <div className="min-w-0">
                    <div className="font-mono font-black text-ink-1 tabular-nums leading-none">{valor}</div>
                    <div className="text-[11px] text-ink-3 truncate">{rotulo}</div>
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[11px] text-ink-4">
              {jogos.length} {jogos.length === 1 ? 'jogo' : 'jogos'}
              {vista === 'h2h' ? ' entre os dois' : ` do ${vista === 'home' ? f.home_team : f.away_team}`}
            </p>
          </div>

          {grupos.map(g => (
            <div key={g.liga ?? 'sem'} className="card overflow-hidden">
              <div className="px-4 py-2.5 flex items-center gap-2 border-b border-line bg-surface-2/40">
                {g.liga != null && <LeagueLogo id={g.liga} />}
                <span className="text-xs font-bold text-ink-1 truncate">{nomeLiga(g.liga)}</span>
              </div>
              <div className="divide-y divide-line/60">
                {g.jogos.map((j, i) => {
                  const r = resultado(j)
                  const venceu = (lado: 'home' | 'away') => j.home_goals != null && j.away_goals != null
                    && (lado === 'home' ? j.home_goals > j.away_goals : j.away_goals > j.home_goals)
                  const perdeu = (lado: 'home' | 'away') => j.home_goals != null && j.away_goals != null
                    && (lado === 'home' ? j.home_goals < j.away_goals : j.away_goals < j.home_goals)
                  return (
                    <div key={j.fixture_id ?? i} className="px-4 py-2.5 flex items-center gap-3">
                      <span className="text-[11px] text-ink-3 w-14 shrink-0 tabular-nums">{dataCurta(j.data)}</span>
                      <div className="flex-1 min-w-0 space-y-1">
                        {(['home', 'away'] as const).map(lado => {
                          const id = lado === 'home' ? j.home_team_id : j.away_team_id
                          const gols = lado === 'home' ? j.home_goals : j.away_goals
                          return (
                            <div key={lado} className={cn('flex items-center gap-2 text-sm',
                              venceu(lado) ? 'text-ink-1 font-bold' : perdeu(lado) ? 'text-ink-3' : 'text-ink-2')}>
                              <TeamLogo id={id} name={nomeTime(id)} size={16} />
                              <span className="truncate flex-1">{nomeTime(id)}</span>
                              <span className="font-mono tabular-nums">{gols ?? '-'}</span>
                            </div>
                          )
                        })}
                      </div>
                      <span className={cn('w-6 h-6 grid place-items-center rounded font-black text-[11px] shrink-0',
                        r === 'V' ? 'bg-green-500 text-on-fill' : r === 'D' ? 'bg-red-500 text-on-fill' : 'bg-surface-3 text-ink-2')}
                        title={`Resultado do ${nomeTime(foco)}`}>
                        {r ?? '?'}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </>
      )}
      {vista === 'h2h' && dados.h2h_fonte === 'api' && (
        <p className="text-[11px] text-ink-4 leading-relaxed px-1">
          Jogos de fora da nossa base: só o placar.
        </p>
      )}
    </div>
  )
}

/* Re-exportado: a aba Jogos importa daqui desde antes de o componente ganhar
 * arquivo próprio (a página pública de jogo não pode carregar o Raio-X inteiro). */
export { FormaPontos }
