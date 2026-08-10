import { useEffect, useState } from 'react'
import { Activity, Home, Plane } from 'lucide-react'
import api from '../services/api'
import { Skeleton } from './ui'
import { translateLine, translateMarket } from '../utils/marketTranslate'

/*
 * Como esse mercado vem se comportando.
 *
 * Uma barra por jogo recente, medida pelo contador que a aposta observa
 * (escanteios, cartões, faltas, chutes no alvo, gols), com a linha do pick
 * atravessando o gráfico. Verde onde teria pago, vermelho onde não.
 *
 * É a diferença entre "a IA acha que dá Over 9.5" e "nos últimos 10 jogos deu
 * 11, 8, 12, 10...". O número de probabilidade pede confiança; isto mostra o
 * que aconteceu.
 *
 * UM TIME POR VEZ, CASA SEPARADA DE FORA (2026-08-10). Até aqui os jogos dos
 * dois times vinham embaralhados numa fileira só, ordenados por data: não dava
 * pra saber de quem era cada barra. Agora cada time tem o próprio gráfico, e
 * dentro dele os jogos em casa ficam de um lado e os fora do outro, com média e
 * aproveitamento de cada mando. A diferença entre os dois blocos não é
 * detalhe · na Série A o mandante faz 5.62 escanteios contra 4.41 do visitante,
 * e era essa mistura que produzia número que não fechava com o pick.
 *
 * O bloco do mando que o time vai jogar HOJE fica em destaque; o outro entra
 * mais apagado, como contraste. Bilhete de várias pernas (múltipla,
 * alavancagem) repete a estrutura perna a perna.
 *
 * Quem decide a cor NÃO é este arquivo. O servidor devolve cada jogo já
 * liquidado pelo mesmo módulo que grada o pick de verdade (settlement), então
 * meia-linha asiática e PUSH em linha cheia chegam aqui resolvidos. Um
 * `valor > linha` daqui pareceria inofensivo e pintaria de verde jogo que não
 * pagou.
 *
 * Jogo sem estatística publicada aparece como barra vazia e fica fora da taxa.
 * Some é o que não pode: "não sei" virando zero foi o que gravou RED num pick
 * que era GREEN em 05/08.
 */

interface FormMatch {
  fixture_id: number
  match_date: string | null
  /** null = a fonte não publicou o contador desse jogo. */
  value: number | null
  result: 'GREEN' | 'RED' | 'PUSH' | null
  /** null = série sem time identificado; aí não há como separar mando. */
  is_home: boolean | null
  opponent: string | null
}

interface Resumo {
  games: number
  resolved: number
  greens: number
  hit_rate: number | null
  average: number | null
}

interface TeamSeries extends Resumo {
  team_id: number
  team: string | null
  /** Mando deste time NA PARTIDA do pick · define qual bloco fica em destaque. */
  side: 'home' | 'away'
  label: string
  line: number | null
  op: string | null
  matches: FormMatch[]
  splits: { home: Resumo | null; away: Resumo | null }
}

interface Leg {
  fixture_id: number | null
  market: string | null
  line: string | null
  label: string
  line_value: number | null
  home_team: string | null
  away_team: string | null
  teams: TeamSeries[]
}

interface MarketFormData {
  available: boolean
  legs?: Leg[]
}

/*
 * Duas perguntas, dois canais. A COR diz se o mercado teria pago (é o
 * vocabulário do produto: green e red); o TOM diz o mando, junto com a
 * separação física dos dois blocos e o rótulo de cada um. Usar cor pro mando
 * custaria o green/red, que é a informação que a barra existe pra dar.
 */
const COR: Record<string, { casa: string; fora: string }> = {
  GREEN: { casa: 'bg-accent',  fora: 'bg-accent/40' },
  RED:   { casa: 'bg-red-400', fora: 'bg-red-400/40' },
  PUSH:  { casa: 'bg-ink-4',   fora: 'bg-ink-4/40' },
}

const pct = (v: number | null | undefined) => (v != null ? Math.round(v * 100) : null)

function corDaTaxa(taxa: number | null) {
  if (taxa == null) return 'text-ink-3'
  return taxa >= 60 ? 'text-accent' : taxa >= 40 ? 'text-ink-2' : 'text-red-400'
}

/** Uma barra por jogo, agrupada por mando. */
function GraficoDoTime({ serie, teto }: { serie: TeamSeries; teto: number }) {
  // A API devolve do mais recente pro mais antigo; o gráfico é lido da
  // esquerda pra direita, então inverte.
  const jogos = serie.matches.slice().reverse()
  const casa = jogos.filter(m => m.is_home === true)
  const fora = jogos.filter(m => m.is_home === false)
  // Série sem mando por jogo (pick antigo, sem id de time): cai numa fileira
  // única em vez de sumir.
  const semMando = !casa.length && !fora.length

  const grupos = semMando
    ? [{ chave: 'todos', titulo: 'últimos jogos', Icone: Activity, jogos, resumo: serie as Resumo, destaque: true, mando: 'casa' as const }]
    : [
        { chave: 'casa', titulo: 'em casa', Icone: Home,  jogos: casa, resumo: serie.splits?.home ?? null, destaque: serie.side === 'home', mando: 'casa' as const },
        { chave: 'fora', titulo: 'fora',    Icone: Plane, jogos: fora, resumo: serie.splits?.away ?? null, destaque: serie.side === 'away', mando: 'fora' as const },
      ].filter(g => g.jogos.length > 0)

  const alturaLinha = serie.line != null ? (serie.line / teto) * 100 : null
  const taxa = pct(serie.hit_rate)

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-2">
        <div className="flex items-baseline gap-1.5 min-w-0">
          <span className="text-xs font-bold text-ink-1 truncate">{serie.team ?? 'Time'}</span>
          {/* Mando na partida DO PICK · é o que justifica o bloco em destaque
              logo abaixo, que fala do mesmo mando no histórico. */}
          <span className="text-[10px] text-ink-4 shrink-0">
            {serie.side === 'home' ? 'mandante neste jogo' : 'visitante neste jogo'}
          </span>
        </div>
        {taxa != null && (
          <span className="text-[10px] text-ink-4 shrink-0">
            bateu em <span className={`font-mono font-bold ${corDaTaxa(taxa)}`}>{serie.greens}</span> de {serie.resolved}
          </span>
        )}
      </div>

      <div className="relative flex items-end gap-2 h-20">
        {/* Linha do pick, atravessando os dois blocos. É a régua contra a qual
            as barras são lidas, então fica por cima delas e não atrás. */}
        {alturaLinha != null && alturaLinha < 100 && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 border-t border-dashed border-ink-3/70 z-10"
            style={{ bottom: `${alturaLinha}%` }}
          >
            <span className="absolute right-0 -top-4 font-mono text-[9px] text-ink-3 bg-surface-0 px-1">
              {serie.line}
            </span>
          </div>
        )}

        {grupos.map((g, i) => (
          <div
            key={g.chave}
            className={`flex items-end gap-1 h-full ${i > 0 ? 'pl-2 border-l border-line' : ''} ${g.destaque ? '' : 'opacity-70'}`}
            style={{ flexGrow: g.jogos.length, flexBasis: 0 }}
          >
            {g.jogos.map(m => {
              const altura = m.value != null ? Math.max((m.value / teto) * 100, 4) : 100
              const quando = m.match_date ?? ''
              const contra = m.opponent ? ` · ${g.mando === 'casa' ? 'x' : 'em'} ${m.opponent}` : ''
              const titulo = m.value == null
                ? `${quando}${contra} · sem estatística publicada`
                : `${quando}${contra} · ${m.value}`
              return (
                <div key={m.fixture_id} className="flex-1 h-full flex items-end" title={titulo}>
                  <div
                    className={`w-full rounded-sm transition-[height] ${
                      m.value == null
                        ? 'border border-dashed border-line-strong bg-transparent'
                        : COR[m.result ?? '']?.[g.mando] ?? 'bg-ink-4'
                    }`}
                    style={{ height: `${altura}%` }}
                  />
                </div>
              )
            })}
          </div>
        ))}
      </div>

      <div className="flex items-start gap-2 mt-1.5">
        {grupos.map((g, i) => (
          <div
            key={g.chave}
            className={`min-w-0 ${i > 0 ? 'pl-2 border-l border-line' : ''}`}
            style={{ flexGrow: g.jogos.length, flexBasis: 0 }}
          >
            <div className={`flex items-center gap-1 ${g.destaque ? 'text-ink-2' : 'text-ink-4'}`}>
              <g.Icone className="w-3 h-3 shrink-0" />
              <span className="text-[10px] font-semibold truncate">{g.titulo}</span>
            </div>
            <div className="text-[10px] text-ink-4 font-mono tabular-nums">
              {g.resumo?.average != null && <>méd {g.resumo.average}</>}
              {g.resumo?.hit_rate != null && <> · {g.resumo.greens}/{g.resumo.resolved}</>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function BlocoDaPerna({ leg, numero }: { leg: Leg; numero: number | null }) {
  // Teto compartilhado pelos dois times: barras de gráficos diferentes só são
  // comparáveis na mesma escala, e a comparação entre os dois times é
  // justamente o que a seção passou a permitir.
  const valores = leg.teams.flatMap(t => t.matches.map(m => m.value)).filter((v): v is number => v != null)
  if (!valores.length) return null
  const teto = Math.max(...valores, leg.line_value ?? 0) * 1.15 || 1
  const jogosPorTime = Math.max(...leg.teams.map(t => t.matches.length))

  return (
    <div className="space-y-4">
      {numero != null && (
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[10px] font-bold text-ink-4 shrink-0">{numero}</span>
          <p className="text-[11px] font-semibold text-ink-1 min-w-0">
            {leg.home_team} x {leg.away_team}
            <span className="text-ink-3 font-normal">
              {' · '}{translateMarket(leg.market ?? '')}
              {leg.line && <> {translateLine(leg.line)}</>}
            </span>
          </p>
        </div>
      )}

      <p className="text-[11px] text-ink-4 -mt-1">
        {leg.label} · últimos {jogosPorTime} jogos de cada time
      </p>

      {leg.teams.map(t => (
        <GraficoDoTime key={`${t.team_id}-${t.side}`} serie={t} teto={teto} />
      ))}
    </div>
  )
}

export default function MarketForm({
  pickId,
  pickType,
}: {
  pickId: number
  pickType: string
}) {
  const [data, setData] = useState<MarketFormData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let vivo = true
    api.get(`/suggestions/${pickId}/market-form`, { params: { pick_type: pickType } })
      .then(r => { if (vivo) setData(r.data) })
      .catch(() => { if (vivo) setData({ available: false }) })
      .finally(() => { if (vivo) setLoading(false) })
    return () => { vivo = false }
  }, [pickId, pickType])

  if (loading) return <Skeleton className="h-[200px]" />
  if (!data?.available || !data.legs?.length) return null

  const legs = data.legs
  const multi = legs.length > 1

  return (
    <div className="bg-surface-0 border border-line rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-3.5 h-3.5 text-ink-4 shrink-0" />
        <span className="panel-label truncate">Como esse mercado vem se comportando</span>
      </div>

      <div className={multi ? 'space-y-5 divide-y divide-line/60' : ''}>
        {legs.map((leg, i) => (
          <div key={`${leg.fixture_id}-${i}`} className={multi && i > 0 ? 'pt-5' : ''}>
            <BlocoDaPerna leg={leg} numero={multi ? i + 1 : null} />
          </div>
        ))}
      </div>

      <div className="flex items-center gap-x-3 gap-y-1.5 mt-4 pt-2.5 border-t border-line/60 flex-wrap">
        {[
          ['bg-accent', 'bateu'],
          ['bg-red-400', 'não bateu'],
          ['bg-ink-4', 'devolveu'],
        ].map(([cls, txt]) => (
          <span key={txt} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-sm ${cls}`} />
            <span className="text-[10px] text-ink-4">{txt}</span>
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-sm border border-dashed border-line-strong" />
          <span className="text-[10px] text-ink-4">sem dado</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-sm bg-accent/40" />
          <span className="text-[10px] text-ink-4">tom mais claro · jogo fora de casa</span>
        </span>
      </div>
    </div>
  )
}
