import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { Spinner } from '../components/ui'
import { fmtSigned } from '../utils/format'

/*
 * Desempenho por pipeline, em página própria.
 *
 * Meus Picks responde "quanto eu ganhei". Não respondia "ganhei COM O QUÊ" ·
 * e é a segunda pergunta que muda decisão: estar no lucro somando tudo e estar
 * no lucro apesar de um pipeline são diagnósticos diferentes, e só o segundo
 * diz o que parar de seguir. O dado já vinha no payload (cada aposta carrega o
 * pick_type); faltava agregar e mostrar.
 *
 * Por que página separada e não mais um bloco em Meus Picks: aquela tela já
 * carrega cinco tiles, o gráfico, o resumo do dia e a lista paginada de
 * apostas. A quebra é consulta, não operação · aguenta ficar a um clique.
 *
 * ALAVANCAGEM NÃO ENTRA AQUI. Ela não está em `entries` no backend (a consulta
 * filtra `pick_type != 'alavancagem'`), porque caminho em andamento não é
 * dinheiro: só vira P&L quando encerra. Misturar degrau a degrau com o resto
 * contaria a mesma aposta por duas réguas. A tela dela é /banca/alavancagem, e
 * o rodapé desta página aponta pra lá.
 */

interface Pipeline {
  key: string
  label: string
  total: number
  greens: number
  reds: number
  pnl: number
  units: number
  staked_units: number
  win_rate: number
  yield: number
}

/** Barra de participação · quanto deste pipeline no volume total de apostas. */
function BarraVolume({ pct }: { pct: number }) {
  return (
    <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden w-full">
      <div
        className="h-full rounded-full bg-ink-4"
        style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
      />
    </div>
  )
}

function LinhaPipeline({ p, volumeTotal }: { p: Pipeline; volumeTotal: number }) {
  const positivo = p.pnl >= 0
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p className="text-sm font-black text-ink-1">{p.label}</p>
          <p className="text-[11px] text-ink-4 mt-0.5">
            {p.total} {p.total === 1 ? 'aposta' : 'apostas'} · {p.greens}G/{p.reds}R
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className={`font-mono text-lg font-black tabular-nums ${positivo ? 'text-green-500' : 'text-red-400'}`}>
            {fmtSigned(p.pnl)}
          </p>
          <p className="font-mono text-[10px] text-ink-4 tabular-nums">
            {p.units >= 0 ? '+' : ''}{p.units.toFixed(1)}u
          </p>
        </div>
      </div>

      <BarraVolume pct={volumeTotal > 0 ? (p.total / volumeTotal) * 100 : 0} />

      <div className="grid grid-cols-3 gap-2 mt-3">
        {[
          { l: 'Win rate', v: `${p.win_rate}%` },
          /* Yield é lucro em unidades sobre unidades APOSTADAS · é o que
             compara pipelines de volume diferente entre si. ROI sobre a banca
             faria o pipeline mais frequente parecer sempre o melhor. */
          { l: 'Yield', v: `${p.yield >= 0 ? '+' : ''}${p.yield.toFixed(1)}%` },
          { l: 'Arriscado', v: `${p.staked_units.toFixed(1)}u` },
        ].map(({ l, v }) => (
          <div key={l} className="text-center">
            <p className="font-mono text-sm font-bold text-ink-1 tabular-nums">{v}</p>
            <p className="text-[10px] text-ink-4 mt-0.5">{l}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function MeusPicksPipelines() {
  const navigate = useNavigate()
  const [data, setData] = useState<any>(null)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    api.get('/banca')
      .then(r => setData(r.data))
      .catch(() => setErro(true))
  }, [])

  const pipelines: Pipeline[] = data?.by_pipeline ?? []
  const volumeTotal = pipelines.reduce((a, p) => a + p.total, 0)
  const pnlTotal    = pipelines.reduce((a, p) => a + p.pnl, 0)
  const unidades    = pipelines.reduce((a, p) => a + p.units, 0)
  const noAzul      = pipelines.filter(p => p.pnl > 0).length
  const melhor      = pipelines.length > 0 ? pipelines[0] : null   // já vem ordenado por pnl

  return (
    <PageShell
      title="Meus Picks por pipeline"
      description="Quanto cada pipeline rendeu dentro da sua banca."
      noindex
      width="full"
      bar={{
        back: '/meus-picks',
        title: 'Por pipeline',
        sub: 'Quanto cada produto rendeu dentro da sua banca',
      }}
      mainClassName="space-y-5"
    >
      {erro ? (
        <div className="card p-12 text-center border-dashed">
          <p className="text-ink-3 text-sm font-semibold">Não deu para carregar</p>
        </div>
      ) : data === null ? (
        <div className="flex justify-center py-20"><Spinner size="lg" /></div>
      ) : pipelines.length === 0 ? (
        <div className="card p-12 text-center border-dashed">
          <p className="text-ink-3 text-sm font-semibold mb-2">Nenhuma aposta resolvida ainda</p>
          <p className="text-ink-4 text-xs leading-relaxed max-w-sm mx-auto">
            A quebra por pipeline aparece assim que a primeira aposta que você
            registrou for liquidada.
          </p>
        </div>
      ) : (
        <>
          {/* Total · o mesmo número da Meus Picks, e pelo mesmo motivo: sai do
              mesmo `entries` do backend, então as duas telas não têm como
              discordar. Sem alavancagem, igual lá. */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              {
                l: 'Total no período',
                v: pnlTotal === 0 ? 'R$ 0' : fmtSigned(pnlTotal),
                sub: 'sem alavancagem',
                c: pnlTotal > 0 ? 'text-green-500' : pnlTotal < 0 ? 'text-red-400' : 'text-ink-2',
              },
              {
                l: 'Em unidades',
                v: `${unidades >= 0 ? '+' : ''}${unidades.toFixed(1)}u`,
                sub: 'independe do valor da sua unidade',
                c: unidades >= 0 ? 'text-green-500' : 'text-red-400',
              },
              {
                l: 'Pipelines no azul',
                v: `${noAzul} de ${pipelines.length}`,
                sub: 'onde o lucro está concentrado',
                c: noAzul * 2 >= pipelines.length ? 'text-green-500' : 'text-ink-1',
              },
              {
                l: 'Mais lucro',
                v: melhor ? melhor.label : '-',
                sub: melhor ? fmtSigned(melhor.pnl) : '',
                c: 'text-ink-1',
              },
            ].map(({ l, v, sub, c }) => (
              <div key={l} className="card p-4">
                <div className="text-[10px] text-ink-3 mb-1">{l}</div>
                <div className={`text-xl font-black ${c}`}>{v}</div>
                <div className="text-[10px] text-ink-4 mt-0.5">{sub}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {pipelines.map(p => (
              <LinhaPipeline key={p.key} p={p} volumeTotal={volumeTotal} />
            ))}
          </div>

          {/* Alavancagem tem régua própria · o link evita que a ausência dela
              nesta lista pareça dado faltando. */}
          <button
            onClick={() => navigate('/banca/alavancagem')}
            className="card p-4 w-full text-left hover:border-ink-4/40 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Info className="w-3.5 h-3.5 text-ink-4 shrink-0" />
              <p className="text-xs text-ink-3">
                <strong className="text-ink-2">Alavancagem não entra nesta conta.</strong>{' '}
                Ela é um caminho: o composto em andamento não é dinheiro e só vira
                saldo quando você encerra. Ver a alavancagem separada
              </p>
            </div>
          </button>
        </>
      )}
    </PageShell>
  )
}
