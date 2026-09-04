import { Link } from 'react-router-dom'
import { CalendarDays, ListChecks } from 'lucide-react'
import {
  Button, EmptyState, Panel, PanelHead, PickTypeBadge, ResultBadge, StatTile,
  Table, type Column,
} from './ui'
import { rotuloDoMercado } from '../utils/marketTranslate'
import { fmtUnits, STAKE_LABEL_PADRAO } from '../utils/format'

/*
 * Peças das páginas públicas de palpites (/palpites-de-futebol-hoje e
 * /palpites/<liga>).
 *
 * As duas telas mostram as MESMAS três coisas na mesma ordem (placar público,
 * jogos na fila, últimos picks resolvidos) e só mudam o recorte, então elas
 * moram aqui em vez de nascerem duas vezes. O que muda de uma pra outra é um
 * booleano: o hub precisa dizer de que liga é cada jogo, a página da liga não.
 *
 * Nada aqui mostra pick PENDENTE. O corte é do backend (routers/palpites.py só
 * lê o union de resultados), e a tela não tem como afrouxá-lo por engano.
 */

export interface JogoPublico {
  fixture_id: number
  home_team: string
  away_team: string
  league_id: number
  league_name: string
  /** Horário de Brasília sem fuso: ler por slice, nunca com new Date. */
  match_datetime: string | null
}

export interface PickPublico {
  match_date: string
  home_team_name: string | null
  away_team_name: string | null
  market: string | null
  line: string | null
  odd: number | null
  result: string | null
  source: string
  league_name: string | null
}

export interface DesempenhoPublico {
  total: number
  greens: number
  reds: number
  profit: number
  win_rate: number
  roi: number
}

/** dd/mm a partir de 'YYYY-MM-DD'. Sem Date: a string já é a data brasileira. */
function diaBR(iso: string): string {
  return iso.slice(8, 10) + '/' + iso.slice(5, 7)
}

export function PlacarPublico({ dados, rotulo }: { dados: DesempenhoPublico; rotulo: string }) {
  return (
    <section>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatTile
          label="Assertividade"
          value={`${dados.win_rate}%`}
          tone={dados.win_rate >= 55 ? 'green' : 'default'}
        />
        <StatTile label="Palpites resolvidos" value={String(dados.total)} />
        <StatTile
          label="ROI acumulado"
          value={`${dados.roi >= 0 ? '+' : ''}${dados.roi.toFixed(1)}%`}
          tone={dados.roi >= 0 ? 'green' : 'red'}
        />
        <StatTile
          label="Lucro"
          value={fmtUnits(dados.profit, 1)}
          tone={dados.profit >= 0 ? 'green' : 'red'}
          hint={STAKE_LABEL_PADRAO}
        />
      </div>
      <p className="text-[11px] text-ink-4 mt-2">{rotulo}</p>
    </section>
  )
}

export function ListaDeJogos({
  jogos,
  comLiga = false,
  titulo,
}: {
  jogos: JogoPublico[]
  comLiga?: boolean
  titulo: string
}) {
  return (
    <section>
      <h2 className="font-display text-base font-semibold text-ink-1 mb-4">{titulo}</h2>
      {jogos.length === 0 ? (
        <EmptyState
          Icon={CalendarDays}
          title="Nenhum jogo na fila agora"
          description="A lista volta assim que a próxima rodada entrar no calendário."
          compact
        />
      ) : (
        <Panel>
          <PanelHead label="Jogos que a IA vai analisar" meta={`${jogos.length} partidas`} />
          <ul className="divide-y divide-line/60">
            {jogos.map(j => (
              <li key={j.fixture_id} className="px-5 py-3 flex items-center gap-3">
                <span className="font-mono text-xs text-ink-3 tabular-nums w-11 shrink-0">
                  {j.match_datetime ? String(j.match_datetime).slice(11, 16) : '--:--'}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink-1 truncate">
                    {j.home_team} x {j.away_team}
                  </p>
                  {comLiga && (
                    <p className="text-[11px] text-ink-4 truncate">{j.league_name}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </section>
  )
}

export function UltimosPicks({
  picks,
  comLiga = false,
  titulo,
}: {
  picks: PickPublico[]
  comLiga?: boolean
  titulo: string
}) {
  const cols: Column<PickPublico>[] = [
    {
      key: 'jogo',
      header: 'Jogo',
      cell: p => (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <PickTypeBadge type={p.source} short />
            <span className="text-xs text-ink-1 truncate">
              {p.home_team_name} x {p.away_team_name}
            </span>
          </div>
          <p className="text-[10px] text-ink-4 truncate mt-0.5">
            {rotuloDoMercado(p.market ?? undefined, p.line ?? undefined)}
            {comLiga && p.league_name ? `, ${p.league_name}` : ''}
          </p>
        </div>
      ),
    },
    {
      key: 'data', header: 'Data', align: 'right', hideOnMobile: true,
      cell: p => <span className="font-mono text-xs text-ink-3 tabular-nums">{diaBR(p.match_date)}</span>,
    },
    {
      key: 'odd', header: 'Odd', align: 'right', hideOnMobile: true,
      cell: p => (
        <span className="font-mono text-xs tabular-nums">
          {p.odd == null ? '-' : p.odd.toFixed(2)}
        </span>
      ),
    },
    { key: 'result', header: 'Resultado', align: 'right', cell: p => <ResultBadge result={p.result} /> },
  ]

  return (
    <section>
      <h2 className="font-display text-base font-semibold text-ink-1 mb-4">{titulo}</h2>
      {picks.length === 0 ? (
        <EmptyState
          Icon={ListChecks}
          title="Ainda sem palpites resolvidos aqui"
          description="Assim que o primeiro jogo desta lista for liquidado, ele aparece nesta tabela."
          compact
        />
      ) : (
        <Panel>
          <Table columns={cols} rows={picks} rowKey={(p, i) => `${p.match_date}-${p.source}-${i}`} />
        </Panel>
      )}
    </section>
  )
}

/**
 * Fim de página. Quem chegou por busca não conhece o produto, então a saída
 * precisa dizer o que ele ganha em vez de só oferecer um botão.
 */
export function ChamadaFinal() {
  return (
    <section className="card p-6 sm:p-8 text-center">
      <h2 className="font-display text-lg sm:text-xl font-semibold text-ink-1 mb-2">
        Os palpites de hoje saem para quem tem conta
      </h2>
      <p className="text-sm text-ink-2 max-w-xl mx-auto mb-5">
        O histórico acima é público e fica registrado, acerto e erro. O mercado e a
        linha de cada jogo do dia ficam na área de picks, e o teste do VIP dura 2 dias
        sem cobrança.
      </p>
      <div className="flex flex-col sm:flex-row gap-3 justify-center">
        <Button to="/login?mode=register" size="lg">Testar o VIP grátis por 2 dias</Button>
        <Button to="/resultados" variant="ghost" size="lg">Ver o histórico completo</Button>
      </div>
    </section>
  )
}

/** Navegação entre as páginas de liga. Também é o link interno que faz o Google
 *  encontrar cada uma delas a partir de qualquer outra. */
export function LinksDeLigas({
  ligas,
  atual,
  /* A tela de slug inválido já usa "Palpites por campeonato" na barra, e o
     mesmo texto duas vezes na mesma tela lê como erro de montagem. */
  titulo = 'Palpites por campeonato',
}: {
  ligas: Array<{ slug: string; name: string }>
  atual?: string
  titulo?: string
}) {
  if (!ligas.length) return null
  return (
    <section>
      <h2 className="font-display text-base font-semibold text-ink-1 mb-4">
        {titulo}
      </h2>
      <div className="flex flex-wrap gap-2">
        {ligas.map(l => (
          <Link
            key={l.slug}
            to={`/palpites/${l.slug}`}
            aria-current={l.slug === atual ? 'page' : undefined}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              l.slug === atual
                ? 'border-accent text-accent-ink'
                : 'border-line text-ink-2 hover:border-line-strong'
            }`}
          >
            {l.name}
          </Link>
        ))}
      </div>
    </section>
  )
}
