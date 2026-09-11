import { useEffect, useState } from 'react'
import { ArrowDown, Cpu, Database, Filter, Info } from 'lucide-react'
import api from '../services/api'
import { Badge, EmptyState, SpinnerBlock } from './ui'

/*
 * Como cada motor chega num pick.
 *
 * As outras telas da aba Motor respondem o que ACONTECEU: quais execuções
 * rodaram (Auditoria dos Motores) e o que o motor olhou num dia (O que o motor
 * olhou). Esta responde a pergunta anterior, que não tinha tela nenhuma: qual
 * é o caminho, e com que dado.
 *
 * Nada aqui é escrito no frontend. O desenho vem de /admin/motor/fluxo, os
 * limiares saem do config real do motor e os métodos do registro de motores ·
 * um limiar que mude em pick_engine/config.py muda esta tela sozinho. Ver a
 * docstring de backend/motor_fluxo.py.
 */

interface Camada {
  nome: string
  faz: string
  reprova: string
  limiares: Record<string, unknown>
}
interface Entrada { fonte: string; o_que: string; origem: string }
interface Metodo { slug: string; label: string; versao: string; tabela: string }
interface Motor {
  slug: string
  label: string
  resumo: string
  entradas: Entrada[]
  camadas: Camada[]
  metodos: Metodo[]
}

/** Número do config como texto. Lista vira "14/1, 30/0.85"; nulo some. */
function valorLegivel(v: unknown): string | null {
  if (v === null || v === undefined) return null
  if (Array.isArray(v)) {
    return v.map(item => Array.isArray(item) ? item.join('/') : String(item)).join(', ')
  }
  return String(v)
}

function Limiares({ limiares }: { limiares: Record<string, unknown> }) {
  const pares = Object.entries(limiares)
    .map(([k, v]) => [k, valorLegivel(v)] as const)
    // Limiar nulo é motor fora do path, não limiar zero · mostrar o degrau sem
    // número é honesto, inventar um padrão não.
    .filter(([, v]) => v !== null)
  if (pares.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {pares.map(([k, v]) => (
        <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-2 border border-line text-ink-3">
          {k}: <span className="text-ink-1 font-mono tabular-nums">{v}</span>
        </span>
      ))}
    </div>
  )
}

function BlocoDoMotor({ motor }: { motor: Motor }) {
  return (
    <div className="rounded-lg border border-line bg-surface-1 p-4">
      <div className="flex items-start gap-2 flex-wrap">
        <Cpu className="w-4 h-4 text-accent-ink mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-ink-1">{motor.label}</h3>
          <p className="text-xs text-ink-3 mt-0.5">{motor.resumo}</p>
        </div>
      </div>

      {motor.metodos.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {motor.metodos.map(m => (
            <Badge key={m.slug} tone="neutral">
              {m.label} <span className="opacity-60 font-mono">v{m.versao}</span>
            </Badge>
          ))}
        </div>
      )}

      {/* O QUE ENTRA. Vem antes do fluxo de propósito: a pergunta do usuário
          era "o que ele leva de dados pra chegar naquele pick", e a resposta
          começa pela origem, não pela primeira peneira. */}
      <div className="mt-4">
        <p className="text-[11px] font-semibold text-ink-2 flex items-center gap-1.5 mb-2">
          <Database className="w-3 h-3" /> O que entra
        </p>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {motor.entradas.map(e => (
            <div key={e.fonte} className="rounded-md border border-line/70 p-2">
              <p className="text-[11px] font-mono text-accent-ink break-all">{e.fonte}</p>
              <p className="text-[11px] text-ink-3 mt-0.5 leading-snug">{e.o_que}</p>
              <p className="text-[10px] text-ink-4 mt-1">{e.origem}</p>
            </div>
          ))}
        </div>
      </div>

      {/* O FLUXO. Vertical e numerado, com a seta entre um degrau e o outro ·
          a ordem é o conteúdo aqui, então ela precisa ser impossível de ler
          errado. */}
      <div className="mt-4">
        <p className="text-[11px] font-semibold text-ink-2 flex items-center gap-1.5 mb-2">
          <Filter className="w-3 h-3" /> Por onde passa
        </p>
        <ol className="space-y-0">
          {motor.camadas.map((c, i) => (
            <li key={c.nome}>
              <div className="rounded-md border border-line/70 bg-surface-0 p-2.5">
                <div className="flex items-baseline gap-2">
                  <span className="text-[10px] font-mono font-bold text-ink-4 shrink-0">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <p className="text-xs font-semibold text-ink-1">{c.nome}</p>
                </div>
                <p className="text-[11px] text-ink-3 mt-1 leading-snug">{c.faz}</p>
                {c.reprova && c.reprova !== '—' && (
                  <p className="text-[11px] text-red-400/80 mt-1 leading-snug">
                    Reprova: {c.reprova}
                  </p>
                )}
                <Limiares limiares={c.limiares} />
              </div>
              {i < motor.camadas.length - 1 && (
                <div className="flex justify-center py-1">
                  <ArrowDown className="w-3 h-3 text-ink-4" />
                </div>
              )}
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}

export default function AdminFluxoDosMotores() {
  const [dados, setDados] = useState<{ motores: Motor[]; derivado: boolean } | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    api.get('/admin/motor/fluxo')
      .then(r => setDados(r.data))
      .catch(() => setDados(null))
      .finally(() => setCarregando(false))
  }, [])

  if (carregando) return <SpinnerBlock />
  if (!dados || dados.motores.length === 0) {
    return <EmptyState title="Sem o desenho dos motores"
                       description="O motor não está acessível a partir deste serviço." />
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-bold text-ink-1">Como o pick nasce</h2>
        <p className="text-xs text-ink-3 mt-1">
          O caminho de cada motor, do dado cru até o pick publicado. Os limiares
          são lidos do motor agora, não escritos nesta tela.
        </p>
        {!dados.derivado && (
          <p className="text-[11px] text-yellow-400/90 mt-2 flex items-center gap-1.5">
            <Info className="w-3 h-3 shrink-0" />
            O motor não está no caminho deste serviço: os métodos e os limiares
            não aparecem.
          </p>
        )}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {dados.motores.map(m => <BlocoDoMotor key={m.slug} motor={m} />)}
      </div>
    </div>
  )
}
