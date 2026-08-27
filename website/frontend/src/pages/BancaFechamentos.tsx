import { useEffect, useState } from 'react'
import { TrendingDown, TrendingUp } from 'lucide-react'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { PillGroup, Spinner } from '../components/ui'
import LucroBarChart from '../components/LucroBarChart'
import { fmtBRL, fmtSigned, fmtUnits } from '../utils/format'

/*
 * Histórico de fechamentos mensais, em página própria.
 *
 * Ele morava no rodapé da Minha Banca, embaixo de tudo. Dois problemas nisso:
 * a lista cresce um item por mês e nunca para, empurrando a página pra baixo
 * sem limite; e ela ficava misturada com o que é do MÊS CORRENTE (saldo,
 * gráfico, sequência), que é outra pergunta.
 *
 * O que fica na Banca é o fechamento PENDENTE, porque aquilo é ação e tem
 * prazo. Aqui é consulta, e consulta suporta ficar a um clique de distância.
 *
 * Com a largura toda a linha cabe mais do que cabia no rodapé: além do saldo,
 * a composição do mês (G/R/meio/devolvido) e o caminho da banca de ponta a
 * ponta, que é o que responde "esse mês foi bom por acerto ou por stake?".
 */

interface Recorte {
  tipo?: string; liga?: string
  picks: number; greens: number; reds: number
  pnl: number; units: number; win_rate: number
}

const TIPO_LABEL: Record<string, string> = {
  vip: 'VIP', free: 'Dica do Dia', multipla: 'Múltiplas',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
  player_stats: 'Jogadores',
}

/** Uma linha de recorte · mesma forma pra tipo e pra liga. */
function LinhaRecorte({ nome, r }: { nome: string; r: Recorte }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-1 font-semibold truncate">{nome}</p>
        <p className="text-[11px] text-ink-4">
          {r.picks} {r.picks === 1 ? 'pick' : 'picks'} · {r.greens}G/{r.reds}R
          {r.picks > 0 && <> · {r.win_rate}%</>}
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className={`font-mono text-sm font-black tabular-nums ${r.pnl >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
          {fmtSigned(r.pnl)}
        </p>
        <p className="font-mono text-[10px] text-ink-4 tabular-nums">
          {fmtUnits(r.units)}
        </p>
      </div>
    </div>
  )
}

interface CloseRow {
  month_key: string
  month_label: string
  bankroll_start: number
  bankroll_end: number
  total_pnl: number
  profit_units: number | null
  greens: number
  reds: number
  half_wins: number
  half_loss: number
  push: number
  total_resolved: number
}

function Composicao({ h }: { h: CloseRow }) {
  const partes: Array<[number, string, string]> = [
    [h.greens,     'G',  'text-accent-ink'],
    [h.reds,       'R',  'text-red-400'],
    [h.half_wins,  '½G', 'text-accent-ink/70'],
    [h.half_loss,  '½R', 'text-red-400/70'],
    [h.push,       'D',  'text-ink-4'],
  ]
  const visiveis = partes.filter(([n]) => n > 0)
  if (!visiveis.length) return <span className="text-[11px] text-ink-4">sem picks resolvidos</span>

  return (
    <span className="flex items-center gap-2 flex-wrap">
      {visiveis.map(([n, rot, cor]) => (
        <span key={rot} className={`font-mono text-[11px] tabular-nums ${cor}`}>
          {n}<span className="text-ink-4">{rot}</span>
        </span>
      ))}
    </span>
  )
}

export default function BancaFechamentos() {
  const [rows, setRows] = useState<CloseRow[] | null>(null)
  const [porTipo, setPorTipo] = useState<Recorte[]>([])
  const [porLiga, setPorLiga] = useState<Recorte[]>([])
  // Filtro por ano · o recorte natural do historico. Mes a mes ja e a lista;
  // o que falta e conseguir isolar um periodo sem rolar 40 linhas.
  const [ano, setAno] = useState<string>('tudo')

  useEffect(() => {
    api.get('/banca/monthly-closes', { params: { limit: 60 } })
      .then(r => setRows(r.data ?? []))
      .catch(() => setRows([]))
    // Recortes falham separado da lista: sao complemento, e a pagina continua
    // util sem eles.
    api.get('/banca/fechamentos/resumo')
      .then(r => { setPorTipo(r.data?.por_tipo ?? []); setPorLiga(r.data?.por_liga ?? []) })
      .catch(() => {})
  }, [])

  // Acumulado de tudo que já foi fechado. É a leitura que a lista sozinha não
  // dá: mês a mês o número é pequeno, e a soma é a que responde se a banca
  // cresceu no ano.
  const anos = Array.from(new Set((rows ?? []).map(r => r.month_key.slice(0, 4)))).sort().reverse()
  const filtradas = ano === 'tudo' ? (rows ?? []) : (rows ?? []).filter(r => r.month_key.startsWith(ano))

  const total = filtradas.reduce((acc, r) => acc + Number(r.total_pnl || 0), 0)
  // "Somei X" nao diz se o resultado veio de consistencia ou de um mes fora da
  // curva. Meses positivos e o melhor/pior mes respondem isso de graca, com o
  // dado que a lista ja carrega.
  const positivos = filtradas.filter(r => Number(r.total_pnl) > 0).length
  const melhor = filtradas.reduce<CloseRow | null>(
    (a, r) => (!a || Number(r.total_pnl) > Number(a.total_pnl) ? r : a), null)
  const unidades = filtradas.reduce((acc, r) => acc + Number(r.profit_units ?? 0), 0)

  // Barras do mais antigo pro mais novo · a lista vem invertida porque ler
  // historico e comecar pelo recente, mas grafico se le da esquerda pra direita
  // no sentido do tempo.
  const barras = [...filtradas].reverse().map(r => ({
    label: r.month_label.replace(/ \d{4}$/, '').slice(0, 3),
    value: Number(r.total_pnl || 0),
    meta: r.total_resolved ? `${r.greens}G/${r.reds}R em ${r.total_resolved}` : undefined,
  }))

  // Media por mes fechado · e a regua contra a qual cada mes se le. Sem ela
  // "+R$ 300" nao diz se foi mes bom ou mes normal.
  const media = filtradas.length ? total / filtradas.length : 0

  return (
    <PageShell
      title="Fechamentos mensais"
      description="Histórico mês a mês da sua banca, com o resultado de cada fechamento confirmado."
      noindex
      width="full"
      bar={{
        back: '/banca',
        title: 'Fechamentos mensais',
        sub: 'Mês a mês, desde o primeiro fechamento confirmado',
      }}
      mainClassName="space-y-5"
    >
      {rows !== null && rows.length > 0 && anos.length > 1 && (
        <PillGroup
          options={[{ value: 'tudo', label: 'Todos os anos' },
                    ...anos.map(a => ({ value: a, label: a }))]}
          value={ano}
          onChange={setAno}
        />
      )}

      {rows === null ? (
        <div className="flex justify-center py-20"><Spinner size="lg" /></div>
      ) : rows.length === 0 ? (
        <div className="card p-12 text-center border-dashed">
          <p className="text-ink-3 text-sm font-semibold mb-2">Nenhum fechamento ainda</p>
          <p className="text-ink-4 text-xs leading-relaxed max-w-sm mx-auto">
            Todo início de mês a sua banca do mês anterior é fechada e registrada aqui.
            O primeiro aparece depois que você confirmar o fechamento na Minha Banca.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              {
                l: 'Somando os meses fechados',
                v: total === 0 ? 'R$ 0' : fmtSigned(total),
                sub: rows.length === 1 ? '1 mês registrado' : `${rows.length} meses registrados`,
                c: total > 0 ? 'text-accent-ink' : total < 0 ? 'text-red-400' : 'text-ink-2',
              },
              {
                l: 'Em unidades',
                v: fmtUnits(unidades),
                sub: 'independe do valor da sua unidade',
                c: unidades >= 0 ? 'text-accent-ink' : 'text-red-400',
              },
              {
                l: 'Meses no azul',
                v: `${positivos} de ${rows.length}`,
                sub: 'consistência, não sorte de um mês',
                c: positivos * 2 >= rows.length ? 'text-accent-ink' : 'text-ink-1',
              },
              {
                l: 'Melhor mês',
                v: melhor ? fmtSigned(melhor.total_pnl) : 'R$ 0',
                sub: melhor?.month_label ?? '',
                c: 'text-ink-1',
              },
            ].map(x => (
              <div key={x.l} className="card p-4">
                <p className={`font-mono text-xl font-black tabular-nums ${x.c}`}>{x.v}</p>
                <p className="text-[11px] text-ink-3 mt-0.5 leading-snug">{x.l}</p>
                <p className="text-[10px] text-ink-4 mt-0.5 leading-snug capitalize">{x.sub}</p>
              </div>
            ))}
          </div>

          {barras.length > 1 && (
            <div className="card p-5">
              <div className="flex items-baseline justify-between gap-3 mb-4">
                <p className="text-xs text-ink-3 font-semibold">Resultado mês a mês</p>
                <p className="text-[11px] text-ink-4">
                  média de <span className={`font-mono font-bold ${media >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
                    {fmtSigned(media)}
                  </span> por mês fechado
                </p>
              </div>
              <LucroBarChart data={barras} height={200} />
            </div>
          )}

          {filtradas.length === 0 ? (
            <div className="card p-10 text-center border-dashed">
              <p className="text-ink-3 text-sm">Nenhum fechamento em {ano}.</p>
            </div>
          ) : (
          <div className="card overflow-hidden divide-y divide-line/60">
            {filtradas.map(h => {
              const positivo = Number(h.total_pnl) >= 0
              return (
                <div key={h.month_key} className="px-4 py-4 flex items-start gap-3">
                  {positivo
                    ? <TrendingUp className="w-4 h-4 shrink-0 text-accent-ink mt-0.5" />
                    : <TrendingDown className="w-4 h-4 shrink-0 text-red-400 mt-0.5" />}

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-ink-1 capitalize">{h.month_label}</p>
                    <p className="font-mono text-[11px] text-ink-3 mt-0.5 tabular-nums">
                      {fmtBRL(h.bankroll_start)}
                      <span className="text-ink-4"> para </span>
                      {fmtBRL(h.bankroll_end)}
                    </p>
                    <div className="mt-1.5">
                      <Composicao h={h} />
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    <p className={`font-mono text-base font-black tabular-nums ${positivo ? 'text-accent-ink' : 'text-red-400'}`}>
                      {fmtSigned(h.total_pnl)}
                    </p>
                    {h.profit_units != null && (
                      <p className="font-mono text-[10px] text-ink-4 tabular-nums">
                        {fmtUnits(h.profit_units)}
                      </p>
                    )}
                    {/* Contra a media · e o que transforma um numero solto em
                        leitura ("esse mes foi acima ou abaixo do meu normal"). */}
                    {filtradas.length > 1 && (
                      <p className={`text-[10px] tabular-nums ${
                        Number(h.total_pnl) >= media ? 'text-accent-ink/70' : 'text-red-400/70'
                      }`}>
                        {Number(h.total_pnl) >= media ? 'acima' : 'abaixo'} da média
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          )}

          {/* As duas perguntas que vem depois de "quanto deu": em QUE PRODUTO
              eu vou bem e em QUE LIGA eu vou bem. Sem elas o usuario sabe o
              placar mas nao sabe o que repetir. */}
          {(porTipo.length > 0 || porLiga.length > 0) && (
            <div className="grid gap-5 lg:grid-cols-2">
              {porTipo.length > 0 && (
                <div className="card p-5">
                  <p className="text-xs text-ink-3 font-semibold mb-1">Por tipo de pick</p>
                  <p className="text-[11px] text-ink-4 mb-2">Todo o seu histórico, do que mais rendeu ao que menos</p>
                  <div className="divide-y divide-line/60">
                    {porTipo.map(r => (
                      <LinhaRecorte key={r.tipo} nome={TIPO_LABEL[r.tipo ?? ''] ?? r.tipo ?? ''} r={r} />
                    ))}
                  </div>
                </div>
              )}

              {porLiga.length > 0 && (
                <div className="card p-5">
                  <p className="text-xs text-ink-3 font-semibold mb-1">Por liga</p>
                  <p className="text-[11px] text-ink-4 mb-2">
                    Só picks de um jogo, porque múltipla e alavancagem não pertencem a uma liga
                  </p>
                  <div className="divide-y divide-line/60">
                    {porLiga.slice(0, 10).map(r => (
                      <LinhaRecorte key={r.liga} nome={r.liga ?? ''} r={r} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="card p-5">
            <p className="text-xs text-ink-3 font-semibold mb-2">Como ler esta página</p>
            <div className="text-[11px] text-ink-3 space-y-1.5 leading-relaxed">
              <p>
                Todo início de mês a sua banca do mês anterior é fechada e vira uma linha
                aqui. O valor registrado é o que você tinha no fim daquele mês, e ele passa
                a ser a base do mês seguinte.
              </p>
              <p>
                <b className="text-ink-2">Em unidades</b> é o número que compara meses entre si:
                reais dependem de quanto vale a sua unidade, e ela muda quando você
                reconfigura a banca. Unidade é a mesma régua sempre.
              </p>
              <p>
                <b className="text-ink-2">Meses no azul</b> separa consistência de sorte. Um
                total alto vindo de um mês fora da curva conta uma história diferente de um
                total alto vindo de seis meses positivos seguidos.
              </p>
              <p>
                <b className="text-ink-2">Por tipo e por liga</b> somam todo o seu histórico,
                não só os meses fechados. Servem pra responder o que repetir: um produto ou uma
                liga com muitos picks e saldo negativo diz mais que um mês ruim isolado.
              </p>
              <p className="text-ink-4">
                O mês corrente ainda não está aqui: ele vive na Minha Banca e entra quando
                você confirmar o fechamento.
              </p>
            </div>
          </div>
        </>
      )}
    </PageShell>
  )
}
