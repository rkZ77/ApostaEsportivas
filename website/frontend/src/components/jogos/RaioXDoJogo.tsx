import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronLeft, ChevronRight, Flag, Minus, Plus, Shield, Users } from 'lucide-react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { ErrorState, Skeleton } from '../ui'
import { LeagueLogo, PaisDaLigaTag, PlayerPhoto, TeamLogo } from '../TeamLogo'
import { nomeDaLigaPt, rotuloDaRodada } from '../../lib/paisDaLiga'
import {
  ambasMarcam, comPeriodo, ehGoleiro, ESTATS_DE_JOGADOR, fraseDoJogador, MERCADOS_DE_TIME, MERCADOS_PRINCIPAIS, numero,
  resultadoDoJogo, ROTULO_PERIODO, rotuloDaLinha, taxa, taxaDoJogador, tomDaTaxa,
  type EstatDeJogador, type Jogador, type JogoDoTime, type Lado, type Periodo, type RaioX, type Taxa,
} from '../../lib/raioX'
import { alternar, useBilheteMontado, type Selecao } from '../../lib/bilheteMontado'
import { oddDaSelecao, vantagem, type OddDaCasa } from '../../lib/oddsDoJogo'
import Campinho from './Campinho'
import Classificacao from './Classificacao'

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

type Aba = 'mercados' | 'jogadores' | 'escalacao' | 'tabela' | 'confronto' | 'forma'

export interface JogoBase {
  fixture_id: number
  home_team_id?: number
  away_team_id?: number
  league_id?: number
  /** O nome gravado; vale só pra liga fora do mapa de nomes em português. */
  league_name?: string
  home_team?: string
  away_team?: string
  match_datetime?: string | null
  forma_home?: string[]
  forma_away?: string[]
}

export default function RaioXDoJogo({ jogo }: { jogo: JogoBase }) {
  const [dados, setDados] = useState<RaioX | null>(null)
  const [erro, setErro] = useState(false)
  const [aba, setAba] = useState<Aba>('mercados')

  const carregar = () => {
    setErro(false)
    setDados(null)
    api.get(`/fixtures/${jogo.fixture_id}/raio-x`, {
      params: { home: jogo.home_team_id, away: jogo.away_team_id, league: jogo.league_id },
    })
      .then(r => setDados(r.data))
      .catch(() => setErro(true))
  }
  useEffect(carregar, [jogo.fixture_id])

  /* Odds das casas · pedido à parte e sem travar a tela: sem odd o Raio-X
     funciona igual, só sem o preço ao lado da taxa. */
  const [odds, setOdds] = useState<OddDaCasa[]>([])
  useEffect(() => {
    setOdds([])
    api.get(`/fixtures/${jogo.fixture_id}/odds`).then(r => setOdds(r.data?.odds ?? [])).catch(() => {})
  }, [jogo.fixture_id])

  const nomeJogo = `${dados?.fixture.home_team || jogo.home_team || 'Casa'} x ${dados?.fixture.away_team || jogo.away_team || 'Fora'}`

  return (
    <div className="min-w-0">
      <Placar jogo={jogo} dados={dados} />

      {/* Abas fixas ao rolar · no celular a lista de jogadores é longa e a
          troca de aba não pode exigir voltar ao topo. */}
      <div className="sticky top-0 z-20 -mx-4 px-4 sm:mx-0 sm:px-0 bg-surface-0/95 backdrop-blur border-b border-line">
        {/* Seis abas não cabem numa linha de celular, e aba escondida fora da
            tela é aba que ninguém descobre: no celular viram 3 x 2, todas à
            vista; do tablet pra cima, uma linha só. */}
        <div className="grid grid-cols-3 sm:flex" role="tablist">
          {([
            ['mercados', 'Mercados'], ['jogadores', 'Jogadores'], ['escalacao', 'Escalação'], ['tabela', 'Tabela'],
            ['confronto', 'Confronto'], ['forma', 'Forma'],
          ] as [Aba, string][]).map(([k, rotulo]) => (
            <button key={k} role="tab" aria-selected={aba === k} onClick={() => setAba(k)}
              className={cn(
                'relative sm:flex-1 h-11 sm:h-12 px-1 text-sm font-bold transition-colors whitespace-nowrap',
                aba === k ? 'text-ink-1' : 'text-ink-3 hover:text-ink-2',
              )}>
              {rotulo}
              {aba === k && <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
        </div>
      </div>

      <div className="pt-4 pb-28 md:pb-6">
        {erro ? (
          <div className="card"><ErrorState title="Não deu pra carregar o Raio-X" onRetry={carregar} /></div>
        ) : !dados ? (
          <div className="space-y-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-36 w-full" />
          </div>
        ) : aba === 'mercados' ? (
          <AbaMercados dados={dados} nomeJogo={nomeJogo} odds={odds} />
        ) : aba === 'jogadores' ? (
          <AbaJogadores dados={dados} nomeJogo={nomeJogo} />
        ) : aba === 'escalacao' ? (
          /* Pedida só ao abrir a aba: é a parte do Raio-X que fala com a
             API-Football, e quem não olha a escalação não gasta cota. */
          <Campinho fixtureId={dados.fixture.fixture_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id}
            homeNome={dados.fixture.home_team} awayNome={dados.fixture.away_team} />
        ) : aba === 'tabela' ? (
          <Classificacao fixtureId={dados.fixture.fixture_id} leagueId={dados.fixture.league_id}
            homeId={dados.fixture.home_team_id} awayId={dados.fixture.away_team_id} />
        ) : aba === 'confronto' ? (
          <AbaConfronto dados={dados} />
        ) : (
          <AbaForma dados={dados} />
        )}
      </div>
    </div>
  )
}

/* ── Placar ─────────────────────────────────────────────────────────────── */

function Placar({ jogo, dados }: { jogo: JogoBase; dados: RaioX | null }) {
  const f = dados?.fixture
  const ligaId = f?.league_id ?? jogo.league_id
  const quando = f?.match_datetime ?? jogo.match_datetime
  const hora = quando ? new Date(quando).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '--:--'
  const dia = quando ? new Date(quando).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' }) : ''
  const formaHome = jogo.forma_home ?? dados?.times.home.jogos.slice(0, 5).map(resultadoDoJogo).filter(Boolean) as string[] ?? []
  const formaAway = jogo.forma_away ?? dados?.times.away.jogos.slice(0, 5).map(resultadoDoJogo).filter(Boolean) as string[] ?? []

  const Time = ({ id, nome, forma }: { id?: number; nome?: string; forma: string[] }) => (
    <div className="flex-1 min-w-0 flex flex-col items-center text-center gap-2">
      <TeamLogo id={id} name={nome ?? ''} size={52} />
      <span className="text-sm font-bold text-ink-1 leading-tight line-clamp-2">{nome}</span>
      <FormaPontos forma={forma} />
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
        </div>
        <div className="flex items-start gap-2">
          <Time id={f?.home_team_id ?? jogo.home_team_id} nome={f?.home_team || jogo.home_team} forma={formaHome} />
          <div className="shrink-0 pt-3 text-center">
            <div className="font-mono text-2xl font-black text-ink-1 tabular-nums">{hora}</div>
            <div className="text-[11px] text-ink-3 capitalize mt-0.5">{dia}</div>
          </div>
          <Time id={f?.away_team_id ?? jogo.away_team_id} nome={f?.away_team || jogo.away_team} forma={formaAway} />
        </div>
      </div>
    </div>
  )
}

export function FormaPontos({ forma, tamanho = 'md' }: { forma: string[]; tamanho?: 'sm' | 'md' }) {
  if (!forma.length) return null
  const cor: Record<string, string> = {
    V: 'bg-green-500 text-on-fill', E: 'bg-surface-3 text-ink-2', D: 'bg-red-500 text-on-fill',
  }
  return (
    <div className="flex gap-1" aria-label={`Últimos jogos: ${forma.join(' ')}`}>
      {/* Do mais antigo pro mais recente, da esquerda pra direita: é como
          qualquer placar mostra, e o último jogo fica na ponta onde o olho
          termina de ler. */}
      {[...forma].reverse().map((r, i) => (
        <span key={i} className={cn(
          'grid place-items-center rounded font-black',
          tamanho === 'md' ? 'w-5 h-5 text-[10px]' : 'w-3.5 h-3.5 text-[8px]',
          cor[r] ?? cor.E,
        )}>{r}</span>
      ))}
    </div>
  )
}

/* ── Peças comuns ───────────────────────────────────────────────────────── */

/*
 * Fileira de opções (2026-10-07, pedido do usuário: "fica ruim de ver, não tem
 * botão pra ir pro lado").
 *
 * COMPUTADOR: quebra em linhas, tudo à vista · lá não se arrasta com o dedo,
 * e uma fileira cortada escondia "Cartões do time" sem aviso nenhum.
 * CELULAR: continua deslizando (uma linha só poupa a altura da tela), mas com
 * seta e esmaecido na ponta que ainda tem opção escondida, e a opção escolhida
 * rola pra dentro da tela sozinha.
 */
function Chips<T extends string>({ opcoes, valor, onChange }: {
  opcoes: Array<{ id: T; rotulo: string }>; valor: T; onChange: (v: T) => void
}) {
  const trilho = useRef<HTMLDivElement>(null)
  const [sobra, setSobra] = useState({ esq: false, dir: false })

  const medir = () => {
    const el = trilho.current
    if (!el) return
    setSobra({ esq: el.scrollLeft > 4, dir: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 })
  }
  useEffect(() => {
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [opcoes.length])
  useEffect(() => {
    trilho.current?.querySelector<HTMLElement>('[aria-pressed="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
  }, [valor])

  const rolar = (dir: 1 | -1) =>
    trilho.current?.scrollBy({ left: dir * trilho.current.clientWidth * 0.7, behavior: 'smooth' })

  const seta = 'md:hidden absolute top-0 z-10 h-10 w-10 grid place-items-center rounded-full bg-surface-2 border border-line-strong text-ink-1 shadow-elev-sm'
  return (
    <div className="relative">
      <div ref={trilho} onScroll={medir}
        className="-mx-4 pl-4 pr-14 sm:mx-0 sm:pl-0 sm:pr-12 md:pr-0 flex gap-2 overflow-x-auto scrollbar-none pb-1
                   md:flex-wrap md:overflow-visible">
        {opcoes.map(o => (
          <button key={o.id} onClick={() => onChange(o.id)} aria-pressed={valor === o.id}
            className={cn(
              'shrink-0 h-10 px-4 rounded-full text-sm font-semibold border transition-colors',
              valor === o.id
                ? 'bg-accent text-on-fill border-accent'
                : 'bg-surface-1 text-ink-2 border-line hover:border-line-strong',
            )}>
            {o.rotulo}
          </button>
        ))}
      </div>
      {sobra.esq && (
        <>
          <div aria-hidden className="md:hidden pointer-events-none -left-4 sm:left-0 absolute top-0 h-10 w-20 bg-gradient-to-r from-surface-0 from-60% to-transparent" />
          <button className={cn(seta, 'left-0')} onClick={() => rolar(-1)} aria-label="Ver opções anteriores"><ChevronLeft size={18} /></button>
        </>
      )}
      {sobra.dir && (
        <>
          <div aria-hidden className="md:hidden pointer-events-none -right-4 sm:right-0 absolute top-0 h-10 w-20 bg-gradient-to-l from-surface-0 from-60% to-transparent" />
          <button className={cn(seta, 'right-0')} onClick={() => rolar(1)} aria-label="Ver mais opções"><ChevronRight size={18} /></button>
        </>
      )}
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

function NumeroDaTaxa({ t, grande }: { t: Taxa; grande?: boolean }) {
  return (
    <div className="text-right shrink-0">
      <div className={cn('font-mono font-black tabular-nums leading-none', grande ? 'text-2xl' : 'text-lg', TOM[tomDaTaxa(t.pct)])}>
        {t.n ? `${t.bateu}/${t.n}` : '—'}
      </div>
      <div className="text-[11px] text-ink-3 mt-1 tabular-nums">
        {t.pct != null ? `${Math.round(t.pct * 100)}%` : 'sem dado'}
        {t.media != null && <> · média {t.media.toFixed(1)}</>}
      </div>
    </div>
  )
}

/**
 * Uma barra por jogo, do mais antigo pro mais recente, com a linha desenhada.
 * Verde = bateu. É o gráfico que responde "bate sempre ou bateu duas vezes
 * muito?" melhor que qualquer média.
 */
function Barras({ valores, linha, lado, rotulos, max: maxFixo }: {
  valores: Array<number | null>; linha: number; lado: Lado
  /** Legenda de cada jogo (mesma ordem de `valores`), mostrada no toque/hover. */
  rotulos?: string[]
  /** Escala comum, pra duas metades lado a lado terem barras comparáveis. */
  max?: number
}) {
  const serie = [...valores].reverse()
  const legendas = rotulos ? [...rotulos].reverse() : []
  const max = maxFixo ?? Math.max(linha + 1, ...serie.map(v => v ?? 0))
  const yLinha = 100 - (linha / max) * 100
  return (
    <div className="relative h-14 flex items-end gap-[3px]">
      {serie.map((v, i) => {
        const bateu = v != null && v !== linha && (lado === 'mais' ? v > linha : v < linha)
        const legenda = legendas[i]
          ? `${legendas[i]}: ${v ?? 'sem dado'}`
          : String(v ?? 'sem dado')
        return (
          <div key={i} title={legenda} aria-label={legenda}
            className="flex-1 h-full flex flex-col justify-end items-center gap-0.5">
            <span className="text-[9px] font-mono text-ink-3 tabular-nums leading-none">{v ?? ''}</span>
            <div
              className={cn('w-full rounded-sm', v == null ? 'bg-surface-3/40' : bateu ? 'bg-green-500' : 'bg-surface-3')}
              style={{ height: `${v == null ? 6 : Math.max(6, (v / max) * 78)}%` }}
            />
          </div>
        )
      })}
      <div className="absolute inset-x-0 border-t border-dashed border-ink-3/60 pointer-events-none"
        style={{ top: `${yLinha * 0.78 + 22}%` }} />
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
      aria-label={dentro ? 'Tirar do bilhete' : 'Pôr no bilhete'}
      className={cn(
        'flex items-center justify-center rounded-lg border font-bold transition active:scale-95',
        cheio ? 'w-full h-12 gap-2 text-sm' : 'w-11 h-11 shrink-0',
        dentro
          ? 'bg-accent/15 border-accent/50 text-accent-ink'
          : cheio ? 'bg-accent text-on-fill border-accent hover:bg-accent-hover' : 'bg-surface-1 border-line text-ink-2 hover:border-accent/50',
      )}>
      {dentro ? <Check size={18} /> : <Plus size={18} />}
      {cheio && <span>{dentro ? 'No bilhete' : 'Pôr no bilhete'}</span>}
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
      {odd.casa && <span className="text-ink-3 text-xs">· {odd.casa}</span>}
      {selo && <span className={cn('ml-auto text-[11px] font-bold px-2 py-0.5 rounded border', selo.cls)}>{selo.txt}</span>}
    </div>
  )
}

/* ── Mercados ───────────────────────────────────────────────────────────── */

function AbaMercados({ dados, nomeJogo, odds }: { dados: RaioX; nomeJogo: string; odds: OddDaCasa[] }) {
  /* Mercado + DE QUEM (os dois somados, ou um time só) · ver MERCADOS_PRINCIPAIS. */
  const [principal, setPrincipal] = useState(MERCADOS_PRINCIPAIS[0].id)
  const [quem, setQuem] = useState<'jogo' | 'home' | 'away'>('jogo')
  const par = MERCADOS_PRINCIPAIS.find(p => p.id === principal)!
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
  const rotulosDe = (jogos: JogoDoTime[]) =>
    jogos.map(j => `${j.em_casa ? 'vs' : '@'} ${j.adversario || 'adversário'} · ${dataCurta(j.data)}`)

  /* "últimos 10 jogos", ou quantos têm o dado de verdade · no 1º e 2º tempo
     os jogos antigos não têm a folha do 1º tempo, e a barra vazia sem
     explicação parece jogo de zero. */
  const amostra = (valores: Array<number | null>) => {
    const com = valores.filter(v => v != null).length
    if (com === valores.length) return `últimos ${valores.length} jogos`
    return `${com} de ${valores.length} jogos com dado ${periodo === 'total' ? '' : `do ${ROTULO_PERIODO[periodo]}`}`.trim()
  }

  interface Grupo { teamId: number; nome: string; valores: Array<number | null>; rotulos: string[] }

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

  const Quadro = ({ titulo, sub, teamId, nomeTime, valores, rotulos, grupos, selecao, destaque }: {
    titulo: string; sub: string; teamId?: number; nomeTime?: string
    valores: Array<number | null>; rotulos?: string[]; grupos?: Grupo[]
    selecao?: Selecao; destaque?: boolean
  }) => {
    const t = taxa(valores, linha, lado)
    const maxComum = Math.max(linha + 1, ...valores.map(v => v ?? 0))
    return (
      <div className={cn('card p-4', destaque && 'border-accent/30')}>
        <div className="flex items-center gap-3 mb-3">
          {teamId != null && <TeamLogo id={teamId} name={nomeTime ?? ''} size={28} />}
          <div className="flex-1 min-w-0">
            <div className="text-sm font-bold text-ink-1 truncate">{titulo}</div>
            <div className="text-[11px] text-ink-3">{sub}</div>
          </div>
          <NumeroDaTaxa t={t} grande={destaque} />
          {selecao && !destaque && <BotaoBilhete selecao={{ ...selecao, bateu: t.bateu, n: t.n }} />}
        </div>
        {grupos ? (
          <div className="grid grid-cols-2 gap-3">
            {grupos.map(g => {
              const tg = taxa(g.valores, linha, lado)
              return (
                <div key={g.nome} className="min-w-0">
                  <div className="flex items-center gap-1.5 mb-1.5 min-w-0">
                    <TeamLogo id={g.teamId} name={g.nome} size={16} />
                    <span className="text-[11px] font-semibold text-ink-2 truncate flex-1">{g.nome}</span>
                    <span className={cn('font-mono text-[11px] font-black tabular-nums shrink-0', TOM[tomDaTaxa(tg.pct)])}>
                      {tg.n ? `${tg.bateu}/${tg.n}` : '—'}
                    </span>
                  </div>
                  <Barras valores={g.valores} rotulos={g.rotulos} linha={linha} lado={lado} max={maxComum} />
                </div>
              )
            })}
          </div>
        ) : (
          <Barras valores={valores} rotulos={rotulos} linha={linha} lado={lado} />
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

  const btts = useMemo(() => {
    const serie = [...home.jogos, ...away.jogos].map(ambasMarcam).map(b => (b == null ? null : b ? 1 : 0))
    return taxa(serie, 0.5, 'mais')
  }, [home.jogos, away.jogos])

  /* ── mercado do JOGO: os dois times somados ── */
  const quadrosDoJogo = () => {
    const vHome = home.jogos.map(j => numero(j, mercado.contador, 'jogo', periodo))
    const vAway = away.jogos.map(j => numero(j, mercado.contador, 'jogo', periodo))
    const descricao = `${comPeriodo(mercado.frase, periodo)} · ${linhaTxt}`
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
            { teamId: f.home_team_id, nome: f.home_team, valores: vHome, rotulos: rotulosDe(home.jogos) },
            { teamId: f.away_team_id, nome: f.away_team, valores: vAway, rotulos: rotulosDe(away.jogos) },
          ]} />
        <Quadro titulo={f.home_team} sub={amostra(vHome)} teamId={f.home_team_id}
          nomeTime={f.home_team} valores={vHome} rotulos={rotulosDe(home.jogos)} />
        <Quadro titulo={f.away_team} sub={amostra(vAway)} teamId={f.away_team_id}
          nomeTime={f.away_team} valores={vAway} rotulos={rotulosDe(away.jogos)} />
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
    const descricao = `${comPeriodo(`${mercado.frase} do ${nomeTime}`, periodo)} · ${linhaTxt}`
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
            { teamId: ehCasa ? f.home_team_id : f.away_team_id, nome: `${nomeTime} faz`, valores: faz, rotulos: rotulosDe(time.jogos) },
            { teamId: ehCasa ? f.away_team_id : f.home_team_id, nome: `${nomeAdv} cede`, valores: cede, rotulos: rotulosDe(adv.jogos) },
          ]} />
        <Quadro titulo={`${nomeTime} faz`} sub={`${mercado.frase.toLowerCase()} a favor, ${amostra(faz)}`}
          teamId={ehCasa ? f.home_team_id : f.away_team_id} nomeTime={nomeTime} valores={faz} rotulos={rotulosDe(time.jogos)} />
        <Quadro titulo={`${nomeAdv} cede`} sub={`${mercado.frase.toLowerCase()} contra, ${amostra(cede)}`}
          teamId={ehCasa ? f.away_team_id : f.home_team_id} nomeTime={nomeAdv} valores={cede} rotulos={rotulosDe(adv.jogos)} />
      </>
    )
  }

  return (
    <div className="space-y-3">
      <Chips opcoes={MERCADOS_PRINCIPAIS.map(m => ({ id: m.id, rotulo: m.rotulo }))} valor={principal} onChange={setPrincipal} />

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
          <p className="text-[11px] text-ink-3">Faltas só existem no jogo todo: o provedor não separa por tempo.</p>
        )}
      </div>

      {mercado.escopo === 'jogo' ? quadrosDoJogo() : quadrosDoTime()}

      {mercado.contador === 'amarelos' && periodo === 'total' && dados.arbitro && (
        <CartaoDoArbitro arbitro={dados.arbitro} linha={linha} lado={lado} />
      )}

      {id === 'gols' && periodo === 'total' && (
        <div className="card p-4">
          <div className="flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Também no jogo</div>
              <div className="text-base font-bold text-ink-1 mt-0.5">Ambas marcam · Sim</div>
            </div>
            <NumeroDaTaxa t={btts} />
            <BotaoBilhete selecao={comOdd({
              id: `${f.fixture_id}:btts`, fixture_id: f.fixture_id, jogo: nomeJogo,
              descricao: 'Ambas marcam · Sim', bateu: btts.bateu, n: btts.n,
              perna: { ...base, descricao: 'Ambas marcam · Sim', tipo: 'time', mercado: 'btts' },
            }, btts.bateu, btts.n, oddDaSelecao(odds, { mercado: 'btts', quem: 'jogo', periodo: 'total' }))} />
          </div>
          <LinhaDaOdd odd={oddDaSelecao(odds, { mercado: 'btts', quem: 'jogo', periodo: 'total' })} bateu={btts.bateu} n={btts.n} />
        </div>
      )}
    </div>
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
        ? <Barras valores={arbitro.jogos.map(j => j.amarelos)} linha={linha} lado={lado} />
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

function AbaJogadores({ dados, nomeJogo }: { dados: RaioX; nomeJogo: string }) {
  const [time, setTime] = useState<'home' | 'away'>('home')
  const [estatId, setEstatId] = useState<EstatDeJogador['id']>('chutes_alvo')
  const estat = ESTATS_DE_JOGADOR.find(e => e.id === estatId)!
  const [minimos, setMinimos] = useState<Record<string, number>>({})
  const minimo = minimos[estatId] ?? estat.minimoPadrao
  const { fonte_titulares, lista } = dados.jogadores[time]
  const f = dados.fixture

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

      <Chips opcoes={ESTATS_DE_JOGADOR.map(e => ({ id: e.id, rotulo: e.rotulo }))} valor={estatId} onChange={setEstatId} />

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
          <p className="text-xs text-ink-3 mt-1">A coleta por jogador cobre as ligas principais; as outras chegam aos poucos.</p>
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
                <div className="mt-1.5 max-w-[200px]"><MiniSerie jogos={j} estat={estatId} minimo={minimo} /></div>
              </div>
              <NumeroDaTaxa t={t} />
              <BotaoBilhete selecao={{
                id: `${f.fixture_id}:p${j.player_id}:${estatId}:${minimo}`, fixture_id: f.fixture_id, jogo: nomeJogo,
                descricao: `${j.nome} · ${fraseDoJogador(estat, minimo)}`, bateu: t.bateu, n: t.n, player_id: j.player_id,
                perna: {
                  fixture_id: f.fixture_id, home_team_id: f.home_team_id, away_team_id: f.away_team_id,
                  home: f.home_team, away: f.away_team, descricao: `${j.nome} · ${fraseDoJogador(estat, minimo)}`,
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

/** Quadradinhos por jogo do jogador: verde bateu, cinza não, vazado sem dado. */
function MiniSerie({ jogos, estat, minimo }: { jogos: Jogador; estat: EstatDeJogador['id']; minimo: number }) {
  return (
    <div className="flex gap-[3px]" aria-hidden>
      {[...jogos.jogos].reverse().map((g, i) => {
        const v = g[estat]
        return (
          <span key={i} title={v == null ? 'sem dado' : String(v)}
            className={cn('flex-1 h-2 rounded-[2px] max-w-[14px]',
              v == null ? 'border border-line' : v >= minimo ? 'bg-green-500' : 'bg-surface-3')} />
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

function AbaConfronto({ dados }: { dados: RaioX }) {
  const f = dados.fixture
  const jogos = dados.h2h
  if (!jogos.length) {
    return <div className="card p-8 text-center text-sm text-ink-2">Os dois ainda não se enfrentaram no nosso histórico.</div>
  }
  let vHome = 0, empates = 0, vAway = 0
  for (const j of jogos) {
    if (j.home_goals == null || j.away_goals == null) continue
    const golsHome = j.home_team_id === f.home_team_id ? j.home_goals : j.away_goals
    const golsAway = j.home_team_id === f.home_team_id ? j.away_goals : j.home_goals
    if (golsHome > golsAway) vHome++
    else if (golsHome < golsAway) vAway++
    else empates++
  }
  const gols = jogos.filter(j => j.home_goals != null).map(j => (j.home_goals ?? 0) + (j.away_goals ?? 0))
  const esc = jogos.map(j => j.escanteios).filter((v): v is number => v != null)
  const media = (xs: number[]) => (xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(1) : '—')

  return (
    <div className="space-y-3">
      <div className="card p-4">
        <div className="grid grid-cols-3 text-center">
          {[[vHome, f.home_team], [empates, 'Empates'], [vAway, f.away_team]].map(([n, r], i) => (
            <div key={i} className="min-w-0">
              <div className={cn('font-mono text-3xl font-black tabular-nums', i === 1 ? 'text-ink-2' : 'text-ink-1')}>{n}</div>
              <div className="text-[11px] text-ink-3 truncate px-1">{r}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 pt-3 border-t border-line grid grid-cols-2 text-center text-sm">
          <div><span className="font-mono font-bold text-ink-1">{media(gols)}</span> <span className="text-ink-3 text-xs">gols/jogo</span></div>
          <div><span className="font-mono font-bold text-ink-1">{media(esc)}</span> <span className="text-ink-3 text-xs">escanteios/jogo</span></div>
        </div>
      </div>
      <div className="card divide-y divide-line/60">
        {jogos.map((j, i) => (
          <div key={i} className="px-4 py-3 flex items-center gap-3 text-sm">
            <span className="text-[11px] text-ink-3 w-16 shrink-0 tabular-nums">{dataCurta(j.data)}</span>
            <TeamLogo id={j.home_team_id} name="" size={18} />
            <span className="font-mono font-black text-ink-1 tabular-nums">{j.home_goals ?? '-'} - {j.away_goals ?? '-'}</span>
            <TeamLogo id={j.away_team_id} name="" size={18} />
            <span className="ml-auto text-[11px] text-ink-3 tabular-nums">{j.escanteios ?? '—'} esc · {j.amarelos} cart</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Forma ──────────────────────────────────────────────────────────────── */

function AbaForma({ dados }: { dados: RaioX }) {
  const f = dados.fixture
  const bloco = (id: number, nome: string, jogos: JogoDoTime[]) => (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 flex items-center gap-2 border-b border-line bg-surface-2/40">
        <TeamLogo id={id} name={nome} size={22} />
        <span className="text-sm font-bold text-ink-1 truncate">{nome}</span>
      </div>
      {jogos.length === 0 ? (
        <p className="p-4 text-sm text-ink-3">Sem jogos encerrados no histórico.</p>
      ) : (
        <div className="divide-y divide-line/60">
          {jogos.map(j => {
            const r = resultadoDoJogo(j)
            return (
              <div key={j.fixture_id} className="px-4 py-2.5 flex items-center gap-3">
                <span className={cn('w-6 h-6 grid place-items-center rounded font-black text-[11px] shrink-0',
                  r === 'V' ? 'bg-green-500 text-on-fill' : r === 'D' ? 'bg-red-500 text-on-fill' : 'bg-surface-3 text-ink-2')}>
                  {r ?? '?'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-ink-1 truncate">
                    <span className="text-ink-3 text-xs mr-1">{j.em_casa ? 'vs' : '@'}</span>{j.adversario || '—'}
                  </div>
                  <div className="text-[11px] text-ink-3 tabular-nums">
                    {j.escanteios_pro ?? '—'}-{j.escanteios_contra ?? '—'} esc · {j.amarelos_pro ?? '—'}-{j.amarelos_contra ?? '—'} cart
                  </div>
                </div>
                <span className="font-mono font-black text-ink-1 tabular-nums">{j.gols_pro ?? '-'}-{j.gols_contra ?? '-'}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
  return (
    <div className="space-y-3">
      {bloco(f.home_team_id, f.home_team, dados.times.home.jogos)}
      {bloco(f.away_team_id, f.away_team, dados.times.away.jogos)}
    </div>
  )
}
