import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, Flag, Target, TrendingDown } from 'lucide-react'
import api from '../services/api'
import { Spinner } from './ui'
import LucroBarChart from './LucroBarChart'
import { fmtBRL, fmtSigned, fmtUnits } from '../utils/format'

/*
 * Alavancagem · contabilidade e leitura do caminho, num painel só.
 *
 * POR QUE COMPONENTE E NÃO PÁGINA
 * -------------------------------
 * Ele é sub-página de dois lugares (Minha Banca e Meus Picks) e ainda é a
 * tela pra onde o card da aba Alavancagem de /picks manda. Três entradas, um
 * conteúdo · escrito uma vez.
 *
 * POR QUE ELE EXISTE
 * ------------------
 * A Minha Banca não conta alavancagem, de propósito: o composto em andamento
 * não é dinheiro, o caminho só vira saldo quando encerra e o RED custa só a
 * entrada. Regra certa, buraco de leitura · quem segue caminho não tinha ONDE
 * ver como ele está indo, e o único sinal na Banca era uma linha de aviso
 * dizendo que aquilo ficava de fora.
 *
 * É CONSULTA, não operação. Seguir degrau e encerrar o caminho continuam na
 * aba Alavancagem de /picks, que é onde o pick do dia aparece · duplicar o
 * botão de encerrar em duas telas é duplicar uma ação irreversível.
 */

interface AlavStep {
  pick_id: number
  result: 'GREEN' | 'RED'
  odd: number
  date: string | null
  match: string
  before: number
  after: number
}

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
  steps?: AlavStep[]
  open_profit?: number
  open_units?: number
  meta?: number
  greens_no_caminho?: number
  realized_total?: number
  realized_units?: number
  history?: CaminhoEncerrado[]
}

interface CaminhoDaIA {
  encerrou_em: string
  passos: number
  motivo: 'meta' | 'red'
  unidades: number
}

interface HistoricoDaIA {
  meta: number
  fechados: number
  na_meta: number
  no_red: number
  unidades: number
  melhor_sequencia: number
  passos_em_aberto: number
  caminhos: CaminhoDaIA[]
}

const MOTIVO: Record<string, { label: string; cor: string; Icone: typeof Flag }> = {
  manual: { label: 'Encerrado por você', cor: 'text-accent-ink', Icone: Flag },
  meta:   { label: 'Bateu a meta',       cor: 'text-accent-ink', Icone: Target },
  red:    { label: 'Caiu num RED',       cor: 'text-red-400',   Icone: TrendingDown },
}

const dataBR = (iso: string | null) =>
  iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '-'

/*
 * A ESCADA · o gráfico que só a alavancagem tem.
 *
 * Curva de linha no tempo é o gráfico errado aqui. O caminho não anda por dia,
 * anda por DEGRAU: cada green reaposta o bolo inteiro, então o eixo natural é
 * a ordem dos greens, não a data. E o formato importa mais que o número · o
 * salto entre o quarto e o quinto degrau é o argumento inteiro do produto, e
 * ele só fica visível quando as barras crescem lado a lado.
 *
 * Escala pelo maior valor da série (nunca pela entrada): com o bolo composto,
 * escalar pela entrada achataria tudo depois do terceiro green.
 */
function Escada({ entrada, steps }: { entrada: number; steps: AlavStep[] }) {
  const degraus = [
    { rotulo: 'Entrada', valor: entrada, result: null as null | 'GREEN' | 'RED', match: '' },
    ...steps.map((s, i) => ({
      rotulo: s.result === 'GREEN' ? `${i + 1}º green` : 'RED',
      valor: s.result === 'GREEN' ? s.after : s.before,
      result: s.result,
      match: s.match,
    })),
  ]
  const maior = Math.max(...degraus.map(d => d.valor), entrada)

  return (
    <div className="flex items-end gap-1.5 h-40">
      {degraus.map((d, i) => {
        const alturaPct = maior > 0 ? (d.valor / maior) * 100 : 0
        const cor = d.result === 'RED' ? 'bg-red-500/70'
                  : d.result === 'GREEN' ? 'bg-orange-400'
                  : 'bg-ink-4/50'
        return (
          <div key={i} className="flex-1 flex flex-col items-center justify-end min-w-0 h-full">
            <span className="font-mono text-[10px] text-ink-3 mb-1 tabular-nums whitespace-nowrap">
              {d.result === 'RED' ? '0' : Math.round(d.valor)}
            </span>
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: `${Math.max(3, alturaPct)}%` }}
              transition={{ delay: i * 0.06, type: 'spring', stiffness: 220, damping: 26 }}
              className={`w-full rounded-t ${cor}`}
              title={d.match || d.rotulo}
            />
            <span className="text-[9px] text-ink-4 mt-1 truncate w-full text-center">
              {d.rotulo}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/*
 * Progresso até o fechamento automático.
 *
 * Segmentos discretos e não barra contínua: a meta é contada em GREENS, um
 * número inteiro e pequeno, e uma barra lisa sugeriria progresso fracionado
 * ("estou em 62% do caminho") que não existe · ou o green veio, ou não veio.
 */
function ProgressoMeta({ feitos, meta }: { feitos: number; meta: number }) {
  return (
    <div className="flex gap-1.5">
      {Array.from({ length: meta }, (_, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, scaleY: 0.4 }}
          animate={{ opacity: 1, scaleY: 1 }}
          transition={{ delay: i * 0.05 }}
          className={`h-2 flex-1 rounded-full ${i < feitos ? 'bg-orange-400' : 'bg-surface-2'}`}
        />
      ))}
    </div>
  )
}

function LinhaCaminho({ c }: { c: CaminhoEncerrado }) {
  const m = MOTIVO[c.end_reason] ?? MOTIVO.manual
  const { Icone } = m
  return (
    <div className="flex items-center gap-3 py-3 border-b border-line last:border-0">
      <Icone className={`w-4 h-4 shrink-0 ${m.cor}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-1 font-semibold truncate">{m.label}</p>
        <p className="text-[11px] text-ink-4">
          {dataBR(c.ended_at)}, entrou com {fmtBRL(c.initial)}, {c.greens}{' '}
          {c.greens === 1 ? 'green' : 'greens'} no caminho
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className={`font-mono text-sm font-black tabular-nums ${c.realized >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
          {fmtSigned(c.realized)}
        </p>
        <p className="font-mono text-[10px] text-ink-4 tabular-nums">
          {fmtUnits(c.units, 2)}
        </p>
      </div>
    </div>
  )
}

/*
 * COMO A IA FOI NOS CAMINHOS · o histórico que a aba não tinha.
 *
 * A aba só sabia falar do caminho de QUEM JÁ CONFIGUROU. Quem nunca pegou um
 * via uma tela vazia com um convite e nada mais; quem já tinha um não tinha
 * com o que comparar. E a amostra pessoal nunca vai responder "isso costuma
 * dar certo?": um caminho de seis passos leva ~28 dias, então em três meses
 * cabem uns poucos.
 *
 * O QUE ESTE BLOCO PRECISA MOSTRAR é a forma do produto, e ela é
 * contraintuitiva: a maioria dos caminhos MORRE. O que sustenta a conta é que
 * morrer custa 1u e chegar ao fim paga dez. Um número só ("+42,9u") esconde
 * isso e vende bem demais; a lista inteira, com os vermelhos todos visíveis,
 * conta a verdade e ainda assim é um bom argumento.
 *
 * Por isso o gráfico é de barras por caminho e não uma curva acumulada: a
 * curva acumulada é a fotografia mais bonita e a menos honesta que existe
 * aqui.
 */
function CaminhosDaIA({ compacto = false }: { compacto?: boolean }) {
  const [ia, setIa] = useState<HistoricoDaIA | null>(null)

  useEffect(() => {
    api.get('/public/alavancagem/caminhos')
      .then(r => setIa(r.data))
      .catch(() => setIa(null))
  }, [])

  if (!ia || ia.fechados === 0) return null

  const naMeta = ia.caminhos.filter(c => c.motivo === 'meta')
  const pagamentos = naMeta.map(c => c.unidades).sort((a, b) => a - b)
  const barras = ia.caminhos
    .slice()
    .reverse()
    .map(c => ({
      label: `${c.encerrou_em.slice(8, 10)}/${c.encerrou_em.slice(5, 7)}`,
      value: c.unidades,
      meta: c.motivo === 'meta' ? `${c.passos} greens` : `RED no ${c.passos}º`,
    }))

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-xs text-ink-3 font-semibold">Como a IA foi nos caminhos</p>
          <p className="text-[11px] text-ink-4 mt-0.5">
            todos os caminhos encerrados desde o primeiro pick de alavancagem
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className={`font-mono text-lg font-black tabular-nums ${ia.unidades >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
            {fmtUnits(ia.unidades, 1)}
          </p>
          <p className="text-[10px] text-ink-4">em {ia.fechados} caminhos</p>
        </div>
      </div>

      {/* A frase que o gráfico sozinho não diz. Sem ela, quem bate o olho no
          total lê "produto que só ganha" · que é o oposto do que aconteceu. */}
      <p className="text-[11px] text-ink-3 leading-relaxed mb-4">
        {ia.no_red} {ia.no_red === 1 ? 'caminho morreu' : 'caminhos morreram'} no
        meio e {ia.no_red === 1 ? 'custou' : 'custaram'} a entrada, 1u cada.
        {naMeta.length > 0 && (
          <> {ia.na_meta} {ia.na_meta === 1 ? 'chegou' : 'chegaram'} aos {ia.meta} greens
          e {ia.na_meta === 1 ? 'pagou' : 'pagaram'} de {fmtUnits(pagamentos[0], 1)} a{' '}
          {fmtUnits(pagamentos[pagamentos.length - 1], 1)}. É assim que o produto
          funciona: perder é o caso comum, e o que fecha paga por vários que não
          fecharam.</>
        )}
      </p>

      {!compacto && <LucroBarChart data={barras} height={170} />}

      {ia.passos_em_aberto > 0 && (
        <p className="text-[11px] text-ink-4 mt-4">
          Há um caminho em andamento, no {ia.passos_em_aberto}º passo. Ele não
          entra em nenhuma soma acima enquanto não encerrar.
        </p>
      )}
    </div>
  )
}

export default function AlavancagemPanel() {
  const navigate = useNavigate()
  const [serie, setSerie] = useState<Serie | null>(null)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    api.get('/banca/alavancagem-serie')
      .then(r => setSerie(r.data))
      .catch(() => setErro(true))
  }, [])

  if (erro) {
    return (
      <div className="card p-12 text-center border-dashed">
        <p className="text-ink-3 text-sm font-semibold">Não deu para carregar</p>
      </div>
    )
  }

  if (serie === null) {
    return <div className="flex justify-center py-20"><Spinner size="lg" /></div>
  }

  /* Sem caminho configurado a tela era um convite e mais nada: quem chegava
     aqui tinha que decidir sobre um produto que nunca viu funcionar. O
     histórico da IA embaixo é a mesma resposta que a página de Resultados dá
     pro resto do site · mostra o que já aconteceu em vez de prometer. */
  if (!serie.configured) {
    return (
      <div className="space-y-5">
        <div className="card p-10 text-center border-dashed">
          <p className="text-ink-3 text-sm font-semibold mb-2">Você ainda não pegou um caminho</p>
          <p className="text-ink-4 text-xs leading-relaxed max-w-sm mx-auto mb-5">
            A alavancagem reaposta o bolo inteiro a cada green e fecha sozinha ao
            bater a meta. Um RED custa só o valor da entrada, nunca a banca.
          </p>
          <button onClick={() => navigate('/picks')} className="btn-primary text-xs">
            Ver o pick de alavancagem
          </button>
        </div>
        <CaminhosDaIA />
      </div>
    )
  }

  const historico = serie.history ?? []
  const steps     = serie.steps ?? []
  const realizado = serie.realized_total ?? 0
  const unidades  = serie.realized_units ?? 0
  const emAberto  = serie.open_profit ?? 0
  const meta      = serie.meta ?? 6
  const feitos    = serie.greens_no_caminho ?? 0
  const fechados  = historico.length
  const noVerde   = historico.filter(c => c.realized > 0).length

  /* Melhor sequência já alcançada · o número que o usuário pediu pra destacar.
     Sai do histórico (greens de cada caminho encerrado) junto com o caminho
     ABERTO, senão a melhor marca sumiria justamente enquanto ela acontece. */
  const melhorSequencia = Math.max(feitos, ...historico.map(c => c.greens), 0)

  const barrasHistorico = historico
    .slice()
    .reverse()   // o gráfico lê da esquerda (mais antigo) pra direita
    .map(c => ({
      label: dataBR(c.ended_at).slice(0, 5),
      value: c.units,
      meta: `${c.greens}G, ${fmtSigned(c.realized)}`,
    }))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          {
            l: 'Já realizado',
            v: realizado === 0 ? 'R$ 0' : fmtSigned(realizado),
            sub: 'isto sim entrou na sua banca',
            c: realizado > 0 ? 'text-accent-ink' : realizado < 0 ? 'text-red-400' : 'text-ink-2',
          },
          {
            l: 'Em unidades',
            v: fmtUnits(unidades, 2),
            sub: 'o caminho arrisca 1u, sempre',
            c: unidades >= 0 ? 'text-accent-ink' : 'text-red-400',
          },
          {
            l: 'Melhor sequência',
            v: `${melhorSequencia}`,
            sub: melhorSequencia === 1 ? 'green seguido' : 'greens seguidos',
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

      {/* Caminho em andamento · read-only. */}
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

        <div className="flex items-end justify-between gap-4 mb-5">
          <div>
            <div className="text-3xl font-black text-orange-400">
              {fmtBRL(serie.current_bankroll)}
            </div>
            <div className="text-xs text-ink-4 mt-1">
              entrada: {fmtBRL(serie.initial_bankroll)}
              {emAberto > 0 && (
                <span className="text-accent-ink font-semibold">, {fmtSigned(emAberto)} em jogo</span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm font-black text-ink-1">{feitos}/{meta}</div>
            <div className="text-[11px] text-ink-4">greens até fechar sozinho</div>
          </div>
        </div>

        <ProgressoMeta feitos={feitos} meta={meta} />

        {steps.length > 0 && (
          <div className="mt-6">
            <p className="text-[11px] text-ink-4 mb-3">Como o bolo cresceu, degrau a degrau</p>
            <Escada entrada={serie.initial_bankroll} steps={steps} />
          </div>
        )}

        <p className="text-[11px] text-ink-4 mt-5 leading-relaxed">
          Este valor não está na Minha Banca e não deve estar: composto em
          andamento é aposta de pé, não saldo. Ele entra lá inteiro no dia em
          que o caminho encerra. Se der RED, o custo é só a entrada de{' '}
          {fmtBRL(serie.initial_bankroll)}.
        </p>
      </div>

      {/* O histórico da IA vem ANTES do histórico pessoal de propósito: com
          poucos caminhos fechados, o pessoal não responde "isso costuma dar
          certo?" e o da IA responde. Quando o usuário acumular caminhos, o
          dele é que passa a ser a leitura principal · e ele está logo abaixo. */}
      <CaminhosDaIA />

      {/* Histórico · barra por caminho encerrado. Em unidades e não em reais
          porque o valor da unidade muda ao longo do tempo, e o gráfico existe
          justamente pra comparar caminhos entre si. */}
      {barrasHistorico.length > 1 && (
        <div className="card p-5">
          <p className="text-xs text-ink-3 font-semibold mb-4">Os seus caminhos, em unidades</p>
          <LucroBarChart data={barrasHistorico} />
        </div>
      )}

      <div className="card p-5">
        <p className="text-xs text-ink-3 font-semibold mb-1">Caminhos encerrados</p>
        {fechados === 0 ? (
          <p className="text-ink-4 text-xs leading-relaxed py-6 text-center">
            Nenhum caminho encerrado ainda. O primeiro aparece aqui quando você
            fechar na mão, bater a meta ou cair num RED.
          </p>
        ) : (
          <div className="mt-2">
            {historico.map(c => <LinhaCaminho key={c.id} c={c} />)}
          </div>
        )}
      </div>
    </div>
  )
}
