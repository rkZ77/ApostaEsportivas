import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, Gavel } from 'lucide-react'
import api from '../services/api'
import { Skeleton } from './ui'
import { TeamLogo } from './TeamLogo'
import { translateLine, translateMarket } from '../utils/marketTranslate'

/*
 * Como esse mercado vem se comportando.
 *
 * Uma barra por jogo recente, medida pelo contador que a aposta observa
 * (escanteios, cartões, faltas, chutes no alvo, gols), com a linha do pick
 * atravessando o gráfico. GREEN onde teria pago, RED onde não.
 *
 * É a diferença entre "a IA acha que dá Over 9.5" e "nos últimos 5 jogos deu
 * 11, 8, 12, 10...". O número de probabilidade pede confiança; isto mostra o
 * que aconteceu.
 *
 * UM TIME POR VEZ, NO MANDO DO JOGO (2026-08-10). Até aqui os jogos dos dois
 * times vinham embaralhados numa fileira só, ordenados por data: não dava pra
 * saber de quem era cada barra, e a média juntava mandos diferentes. Agora cada
 * time tem o próprio gráfico, e ele só traz os jogos no mando que aquele time
 * vai jogar · se o Goiás joga em casa, a série do Goiás é de jogos em casa.
 *
 * Não é preferência de layout. Na Série A o mandante faz 5.62 escanteios contra
 * 4.41 do visitante: juntar os dois mandos numa média só produz um número que
 * não descreve nem uma coisa nem outra.
 *
 * MERCADO DE CARTÃO GANHA A SÉRIE DO ÁRBITRO. Cartão é o único contador em que
 * quem apita responde por parte do número · o motor já veta o mercado quando o
 * árbitro não tem amostra, mas o card mostrava a conta sem essa variável.
 *
 * Bilhete de várias pernas (múltipla, alavancagem) repete a estrutura perna a
 * perna · não existe UMA série que descreva o bilhete inteiro.
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
  is_home: boolean | null
  opponent: string | null
}

interface Serie {
  label: string
  line: number | null
  matches: FormMatch[]
  games: number
  resolved: number
  greens: number
  hit_rate: number | null
  average: number | null
  /* Frase de fato sobre a série, montada no backend a partir DESTES mesmos
     números (market_form.frase_da_serie). Vem pronta e traduzida: montar aqui
     abriria a porta pra o texto e as barras divergirem, que é exatamente o que
     já aconteceu entre o card e o motor. */
  frase?: string | null
  /** Vieram menos jogos do que a série pediu · ver o aviso no rodapé dela. */
  amostra_curta: boolean
  amostra_pedida: number
}

interface TeamSerie extends Serie {
  /** null em prop de JOGADOR (defesas de goleiro): a série é da pessoa, não
   *  de um time, e não há escudo nem mando pra mostrar. */
  team_id: number | null
  team: string | null
  /** Mando deste time na partida do pick, e de todos os jogos da série.
   *  null em prop de jogador: as defesas dele são as dele, jogue onde jogar. */
  side: 'home' | 'away' | null
}

interface RefereeSerie extends Serie {
  name: string
}

interface Leg {
  fixture_id: number | null
  market: string | null
  line: string | null
  label: string
  line_value: number | null
  home_team: string | null
  away_team: string | null
  teams: TeamSerie[]
  referee: RefereeSerie | null
}

interface MarketFormData {
  available: boolean
  legs?: Leg[]
}

const COR: Record<string, string> = {
  GREEN: 'bg-accent',
  RED:   'bg-red-400',
  PUSH:  'bg-ink-4',
}

function corDaTaxa(taxa: number) {
  return taxa >= 60 ? 'text-accent-ink' : taxa >= 40 ? 'text-ink-2' : 'text-red-400'
}

function Grafico({
  titulo, contexto, prefixo, serie, teto, logoId, Icone,
}: {
  titulo: string
  /** Completa "últimos N jogos ___" · "em casa", "fora", "apitados". */
  contexto: string
  /** Liga a barra ao adversário no tooltip · "x Vasco", "em Vasco", "" no árbitro. */
  prefixo: string
  serie: Serie
  teto: number
  logoId?: number
  Icone?: React.ComponentType<{ className?: string }>
}) {
  // A API devolve do mais recente pro mais antigo; o gráfico é lido da
  // esquerda pra direita, então inverte.
  const jogos = serie.matches.slice().reverse()
  const alturaLinha = serie.line != null ? (serie.line / teto) * 100 : null
  const taxa = serie.hit_rate != null ? Math.round(serie.hit_rate * 100) : null

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 min-w-0">
          {logoId != null && <TeamLogo id={logoId} name={titulo} size={18} />}
          {Icone && <Icone className="w-3.5 h-3.5 text-ink-4 shrink-0" />}
          <span className="text-xs font-bold text-ink-1 truncate">{titulo}</span>
        </div>
        {taxa != null && (
          <span className={`font-mono text-sm font-bold tabular-nums shrink-0 ${corDaTaxa(taxa)}`}>
            {taxa}%
          </span>
        )}
      </div>

      <p className="text-[11px] text-ink-4 mb-2">
        {serie.label}, últimos {jogos.length} jogos {contexto}
        {serie.average != null && <>, média {serie.average}</>}
        {taxa != null && <>, {serie.greens} GREEN em {serie.resolved}</>}
      </p>

      {/* O fato em uma frase, do jeito que o apostador lê nas casas. Fica ACIMA
          das barras porque é o resumo delas · quem só bate o olho leva o número
          principal, quem quiser o detalhe desce pro gráfico. */}
      {serie.frase && (
        <p className="text-[12px] text-ink-2 leading-snug mb-3 bg-surface-2/60 border border-line/60 rounded-lg px-2.5 py-2">
          {serie.frase}
        </p>
      )}

      <div className="relative h-20 flex items-end gap-1">
        {/* Linha do pick, atravessando. É a régua contra a qual as barras são
            lidas, então fica por cima delas e não atrás. */}
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

        {jogos.map(m => {
          const altura = m.value != null ? Math.max((m.value / teto) * 100, 4) : 100
          const quando = m.match_date ?? ''
          const contra = m.opponent ? `, ${prefixo ? `${prefixo} ` : ''}${m.opponent}` : ''
          const titulo = m.value == null
            ? `${quando}${contra}, sem estatística publicada`
            : `${quando}${contra}, ${m.value}`
          return (
            <div key={m.fixture_id} className="flex-1 h-full flex items-end" title={titulo}>
              <div
                className={`w-full rounded-sm transition-[height] ${
                  m.value == null
                    ? 'border border-dashed border-line-strong bg-transparent'
                    : COR[m.result ?? ''] ?? 'bg-ink-4'
                }`}
                style={{ height: `${altura}%` }}
              />
            </div>
          )
        })}
      </div>

      {/*
        Amostra curta, dita com todas as letras.

        O recorte por mando deixa isso comum: um time tem ~7 jogos em casa numa
        fase inteira, e no começo de temporada tem 2. Três barras verdes lidas
        como "100%" são muito menos do que parecem, e quem lê o card não tem
        como saber disso sozinho · a régua e as cores são idênticas.
      */}
      {serie.amostra_curta && (
        <p className="flex items-start gap-1.5 mt-2 text-[10px] text-yellow-500/90 leading-snug">
          <AlertTriangle className="w-3 h-3 shrink-0 mt-px" />
          <span>
            Histórico curto: {jogos.length} {jogos.length === 1 ? 'jogo' : 'jogos'} nesta
            temporada, não {serie.amostra_pedida}. Com poucos jogos, essa porcentagem
            varia muito.
          </span>
        </p>
      )}
    </div>
  )
}

function BlocoDaPerna({ leg, numero }: { leg: Leg; numero: number | null }) {
  // Teto compartilhado por todas as séries da perna, árbitro incluído: barras
  // de gráficos diferentes só são comparáveis na mesma escala, e comparar as
  // séries entre si é justamente o que a seção passou a permitir.
  /* `Array.isArray` antes de espalhar: uma perna sem `teams` (resposta parcial,
     erro serializado, versão antiga do endpoint) não pode derrubar a PÁGINA.
     Sem a guarda, o spread levanta "leg.teams is not iterable", o erro sobe pro
     ErrorBoundary e o "Algo deu errado" toma o lugar dos picks -- um modal
     estragado apagando a tela inteira. Mesma trava de PicksPendingCard e
     LivePicks. */
  const times: TeamSerie[] = Array.isArray(leg?.teams) ? leg.teams : []
  const series: Serie[] = [...times, ...(leg?.referee ? [leg.referee] : [])]
  const valores = series.flatMap(s => s.matches.map(m => m.value)).filter((v): v is number => v != null)
  if (!valores.length) return null
  const teto = Math.max(...valores, leg.line_value ?? 0) * 1.15 || 1

  return (
    <div className="space-y-4">
      {numero != null && (
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[10px] font-bold text-ink-4 shrink-0">{numero}</span>
          <p className="text-[11px] font-semibold text-ink-1 min-w-0">
            {leg.home_team} x {leg.away_team}
            <span className="text-ink-3 font-normal">
              {', '}{translateMarket(leg.market ?? '')}
              {leg.line && <> {translateLine(leg.line)}</>}
            </span>
          </p>
        </div>
      )}

      {times.map(t => (
        <Grafico
          key={`${t.team_id ?? t.team}-${t.side ?? 'jogador'}`}
          titulo={t.team ?? 'Time'}
          /* Sem mando não existe "em casa"/"fora" pra dizer, e inventar um dos
             dois descreveria a série errado · prop de jogador cai aqui. */
          contexto={t.side === 'home' ? 'em casa' : t.side === 'away' ? 'fora' : ''}
          prefixo={t.side === 'home' ? 'x' : t.side === 'away' ? 'em' : ''}
          logoId={t.team_id ?? undefined}
          serie={t}
          teto={teto}
        />
      ))}

      {leg.referee && (
        <div className="pt-1">
          <Grafico
            titulo={leg.referee.name}
            contexto="apitados"
            prefixo=""
            Icone={Gavel}
            serie={leg.referee}
            teto={teto}
          />
        </div>
      )}
    </div>
  )
}

export default function MarketForm({
  pickId,
  pickType,
  dados,
}: {
  pickId: number
  pickType: string
  /* JÁ VEM PRONTO quando o modal buscou tudo de uma vez (o caso normal desde
     02/09 · ver services/analisePick). A busca própria fica como caminho de
     quem monta este bloco fora do modal. */
  dados?: MarketFormData | null
}) {
  const [data, setData] = useState<MarketFormData | null>(dados ?? null)
  const [loading, setLoading] = useState(dados === undefined)

  useEffect(() => {
    if (dados !== undefined) {
      setData(dados)
      setLoading(false)
      return
    }
    let vivo = true
    api.get(`/suggestions/${pickId}/market-form`, { params: { pick_type: pickType } })
      .then(r => { if (vivo) setData(r.data) })
      .catch(() => { if (vivo) setData({ available: false }) })
      .finally(() => { if (vivo) setLoading(false) })
    return () => { vivo = false }
  }, [pickId, pickType, dados])

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

      <div className={multi ? 'space-y-5' : ''}>
        {legs.map((leg, i) => (
          <div key={`${leg.fixture_id}-${i}`} className={multi && i > 0 ? 'pt-5 border-t border-line/60' : ''}>
            <BlocoDaPerna leg={leg} numero={multi ? i + 1 : null} />
          </div>
        ))}
      </div>

      {/* Vocabulário do produto: é GREEN, RED e PUSH em todo o resto do site
          (ver utils/resultStyle.ts), não "bateu"/"não bateu". */}
      <div className="flex items-center gap-3 mt-4 pt-2.5 border-t border-line/60 flex-wrap">
        {[
          ['bg-accent', 'GREEN'],
          ['bg-red-400', 'RED'],
          ['bg-ink-4', 'PUSH'],
        ].map(([cls, txt]) => (
          <span key={txt} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-sm ${cls}`} />
            <span className="text-[10px] font-bold text-ink-4">{txt}</span>
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-sm border border-dashed border-line-strong" />
          <span className="text-[10px] text-ink-4">sem dado</span>
        </span>
      </div>
    </div>
  )
}
