import { useEffect, useState } from 'react'
import { TrendingDown, TrendingUp } from 'lucide-react'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { Spinner } from '../components/ui'
import { fmtBRL, fmtSigned } from '../utils/format'

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
    [h.greens,     'G',  'text-green-500'],
    [h.reds,       'R',  'text-red-400'],
    [h.half_wins,  '½G', 'text-green-500/70'],
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

  useEffect(() => {
    api.get('/banca/monthly-closes', { params: { limit: 60 } })
      .then(r => setRows(r.data ?? []))
      .catch(() => setRows([]))
  }, [])

  // Acumulado de tudo que já foi fechado. É a leitura que a lista sozinha não
  // dá: mês a mês o número é pequeno, e a soma é a que responde se a banca
  // cresceu no ano.
  const total = (rows ?? []).reduce((acc, r) => acc + Number(r.total_pnl || 0), 0)
  // "Somei X" nao diz se o resultado veio de consistencia ou de um mes fora da
  // curva. Meses positivos e o melhor/pior mes respondem isso de graca, com o
  // dado que a lista ja carrega.
  const positivos = (rows ?? []).filter(r => Number(r.total_pnl) > 0).length
  const melhor = (rows ?? []).reduce<CloseRow | null>(
    (a, r) => (!a || Number(r.total_pnl) > Number(a.total_pnl) ? r : a), null)
  const unidades = (rows ?? []).reduce((acc, r) => acc + Number(r.profit_units ?? 0), 0)

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
                c: total > 0 ? 'text-green-500' : total < 0 ? 'text-red-400' : 'text-ink-2',
              },
              {
                l: 'Em unidades',
                v: `${unidades >= 0 ? '+' : ''}${unidades.toFixed(1)}u`,
                sub: 'independe do valor da sua unidade',
                c: unidades >= 0 ? 'text-green-500' : 'text-red-400',
              },
              {
                l: 'Meses no azul',
                v: `${positivos} de ${rows.length}`,
                sub: 'consistência, não sorte de um mês',
                c: positivos * 2 >= rows.length ? 'text-green-500' : 'text-ink-1',
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

          <div className="card overflow-hidden divide-y divide-line/60">
            {rows.map(h => {
              const positivo = Number(h.total_pnl) >= 0
              return (
                <div key={h.month_key} className="px-4 py-4 flex items-start gap-3">
                  {positivo
                    ? <TrendingUp className="w-4 h-4 shrink-0 text-green-500 mt-0.5" />
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
                    <p className={`font-mono text-base font-black tabular-nums ${positivo ? 'text-green-500' : 'text-red-400'}`}>
                      {fmtSigned(h.total_pnl)}
                    </p>
                    {h.profit_units != null && (
                      <p className="font-mono text-[10px] text-ink-4 tabular-nums">
                        {h.profit_units >= 0 ? '+' : ''}{h.profit_units.toFixed(1)}u
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          <p className="text-[11px] text-ink-4 leading-relaxed">
            Cada linha é um mês já confirmado. O resultado do mês corrente ainda está
            na Minha Banca e entra aqui quando você fechar.
          </p>
        </>
      )}
    </PageShell>
  )
}
