import { useEffect, useState } from 'react'
import { ArrowUpRight, Flag, TrendingDown, Target } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { Spinner } from '../components/ui'
import { fmtBRL, fmtSigned } from '../utils/format'

/*
 * Alavancagem em página própria, saindo da Minha Banca.
 *
 * A Minha Banca não conta alavancagem, de propósito: o composto em andamento
 * não é dinheiro, e o caminho só vira saldo quando encerra (o RED custa só a
 * entrada). Isso é a regra certa, mas criava um buraco de leitura · quem
 * seguia caminho não tinha ONDE ver como ele está indo, e o único sinal na
 * Banca era uma linha de aviso dizendo que aquilo ficava de fora.
 *
 * Esta tela é o outro lado desse aviso: mostra o caminho aberto, quanto já foi
 * realizado (isso sim entrou na banca) e o histórico de caminhos encerrados.
 *
 * É CONSULTA, não operação. Seguir degrau e encerrar o caminho continuam na
 * aba Alavancagem de /picks, que é onde o pick do dia aparece · duplicar o
 * botão de encerrar em duas telas é duplicar uma ação irreversível.
 */

interface CaminhoEncerrado {
  id: number
  initial: number
  final: number
  realized: number
  units: number
  greens: number
  end_reason: 'manual' | 'red' | 'meta'
  started_at: string | null
  ended_at: string | null
}

interface Serie {
  configured: boolean
  current_bankroll: number
  initial_bankroll: number
  open_profit?: number
  open_units?: number
  meta?: number
  greens_no_caminho?: number
  realized_total?: number
  realized_units?: number
  history?: CaminhoEncerrado[]
}

const MOTIVO: Record<string, { label: string; cor: string; Icone: typeof Flag }> = {
  manual: { label: 'Encerrado por você', cor: 'text-green-500', Icone: Flag },
  meta:   { label: 'Bateu a meta',       cor: 'text-green-500', Icone: Target },
  red:    { label: 'Caiu num RED',       cor: 'text-red-400',   Icone: TrendingDown },
}

const dataBR = (iso: string | null) =>
  iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '-'

function LinhaCaminho({ c }: { c: CaminhoEncerrado }) {
  const m = MOTIVO[c.end_reason] ?? MOTIVO.manual
  const { Icone } = m
  return (
    <div className="flex items-center gap-3 py-3 border-b border-line last:border-0">
      <Icone className={`w-4 h-4 shrink-0 ${m.cor}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-1 font-semibold truncate">{m.label}</p>
        <p className="text-[11px] text-ink-4">
          {dataBR(c.ended_at)} · entrou com {fmtBRL(c.initial)} · {c.greens}{' '}
          {c.greens === 1 ? 'green' : 'greens'} no caminho
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className={`font-mono text-sm font-black tabular-nums ${c.realized >= 0 ? 'text-green-500' : 'text-red-400'}`}>
          {fmtSigned(c.realized)}
        </p>
        <p className="font-mono text-[10px] text-ink-4 tabular-nums">
          {c.units >= 0 ? '+' : ''}{c.units.toFixed(2)}u
        </p>
      </div>
    </div>
  )
}

export default function BancaAlavancagem() {
  const navigate = useNavigate()
  const [serie, setSerie] = useState<Serie | null>(null)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    api.get('/banca/alavancagem-serie')
      .then(r => setSerie(r.data))
      .catch(() => setErro(true))
  }, [])

  const historico = serie?.history ?? []
  const realizado = serie?.realized_total ?? 0
  const unidades  = serie?.realized_units ?? 0
  const emAberto  = serie?.open_profit ?? 0
  const fechados  = historico.length
  const noVerde   = historico.filter(c => c.realized > 0).length

  return (
    <PageShell
      title="Alavancagem"
      description="Seus caminhos de alavancagem, separados da banca."
      noindex
      width="full"
      bar={{
        back: '/banca',
        title: 'Alavancagem',
        sub: 'Contabilizada à parte da banca · só o caminho encerrado vira saldo',
      }}
      mainClassName="space-y-5"
    >
      {erro ? (
        <div className="card p-12 text-center border-dashed">
          <p className="text-ink-3 text-sm font-semibold">Não deu para carregar</p>
        </div>
      ) : serie === null ? (
        <div className="flex justify-center py-20"><Spinner size="lg" /></div>
      ) : !serie.configured ? (
        <div className="card p-12 text-center border-dashed">
          <p className="text-ink-3 text-sm font-semibold mb-2">Você ainda não pegou um caminho</p>
          <p className="text-ink-4 text-xs leading-relaxed max-w-sm mx-auto mb-5">
            A alavancagem reaposta o bolo inteiro a cada green e fecha sozinha ao
            bater a meta. Um RED custa só o valor da entrada · nunca a banca.
          </p>
          <button onClick={() => navigate('/picks')} className="btn-primary text-xs">
            Ver o pick de alavancagem
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              {
                l: 'Já realizado',
                v: realizado === 0 ? 'R$ 0' : fmtSigned(realizado),
                sub: 'isto sim entrou na sua banca',
                c: realizado > 0 ? 'text-green-500' : realizado < 0 ? 'text-red-400' : 'text-ink-2',
              },
              {
                l: 'Em unidades',
                v: `${unidades >= 0 ? '+' : ''}${unidades.toFixed(2)}u`,
                sub: 'o caminho arrisca 1u, sempre',
                c: unidades >= 0 ? 'text-green-500' : 'text-red-400',
              },
              {
                l: 'Caminho aberto',
                v: emAberto === 0 ? 'R$ 0' : fmtSigned(emAberto),
                sub: 'ainda não é dinheiro',
                c: 'text-orange-400',
              },
              {
                l: 'Caminhos fechados',
                v: fechados === 0 ? '0' : `${noVerde} de ${fechados}`,
                sub: fechados === 0 ? 'nenhum encerrado ainda' : 'terminaram no verde',
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

          {/* Caminho em andamento · read-only. Operar (seguir degrau, encerrar)
              continua na aba Alavancagem de /picks. */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <p className="text-xs text-ink-3 font-semibold">Caminho em andamento</p>
              <button
                onClick={() => navigate('/picks')}
                className="text-[11px] text-ink-3 hover:text-ink-1 flex items-center gap-1 transition-colors"
              >
                Operar em Picks <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            <div className="flex items-end justify-between gap-4">
              <div>
                <div className="text-3xl font-black text-orange-400">
                  {fmtBRL(serie.current_bankroll)}
                </div>
                <div className="text-xs text-ink-4 mt-1">
                  entrada: {fmtBRL(serie.initial_bankroll)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-black text-ink-1">
                  {serie.greens_no_caminho ?? 0}/{serie.meta ?? 6}
                </div>
                <div className="text-[11px] text-ink-4">greens até fechar sozinho</div>
              </div>
            </div>
            <p className="text-[11px] text-ink-4 mt-4 leading-relaxed">
              Este valor não está na Minha Banca e não deve estar: composto em
              andamento é aposta de pé, não saldo. Ele entra lá inteiro no dia em
              que o caminho encerra. Se der RED, o custo é só a entrada de{' '}
              {fmtBRL(serie.initial_bankroll)}.
            </p>
          </div>

          <div className="card p-5">
            <p className="text-xs text-ink-3 font-semibold mb-1">Caminhos encerrados</p>
            {fechados === 0 ? (
              <p className="text-ink-4 text-xs leading-relaxed py-6 text-center">
                Nenhum caminho encerrado ainda. O primeiro aparece aqui quando
                você fechar na mão, bater a meta ou cair num RED.
              </p>
            ) : (
              <div className="mt-2">
                {historico.map(c => <LinhaCaminho key={c.id} c={c} />)}
              </div>
            )}
          </div>
        </>
      )}
    </PageShell>
  )
}
