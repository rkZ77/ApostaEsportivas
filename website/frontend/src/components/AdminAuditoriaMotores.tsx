import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, Check, ChevronRight, CircleSlash, Cpu, Loader2, RefreshCw, X,
} from 'lucide-react'
import api from '../services/api'
import { Badge, Button, EmptyState, Pagination, Select, SpinnerBlock } from './ui'
import type { BadgeTone } from './ui'
import BlocoAmostra, { type Amostra } from './BlocoAmostra'

/*
 * Auditoria dos Motores · a camada de EXECUÇÃO.
 *
 * A aba abaixo desta ("O que o motor olhou") responde o que aconteceu com os
 * jogos de um dia. Esta responde uma pergunta anterior, que não tinha tela:
 * QUAIS EXECUÇÕES rodaram, de qual motor, em que versão e com que desfecho.
 *
 * A diferença não é cosmética. "Por que não saiu pick de faltas hoje?" tem três
 * respostas possíveis, e só a execução as separa:
 *
 *   o motor não rodou · rodou e falhou · rodou, olhou 14 jogos, nenhum passou
 *
 * As três produzem exatamente a mesma coisa do lado de fora: nenhuma linha em
 * picks_faltas. Sem `engine_runs`, eram indistinguíveis.
 *
 * A fonte é o Engine Audit, gravado DURANTE a execução do motor · nada aqui
 * recalcula nada. Um número desta tela que discordasse do motor estaria errado
 * por construção, e é essa garantia que faz a tela valer alguma coisa.
 *
 * Nada aqui escreve. Auditoria que a tela altera deixa de ser auditoria.
 */

interface Metodo { slug: string; label: string; versao: string; tabela_picks: string }
interface Motor { slug: string; label: string; prefixo: string; metodos: Metodo[] }

interface Execucao {
  run_id: string
  engine: string
  method: string
  metodo_label?: string
  engine_version: string
  dia: string | null
  iniciada_em: string | null
  terminada_em: string | null
  duracao_s: number | null
  status: string
  analisados: number
  selecionados: number
  descartados: number
  erros: number
  resumo: Record<string, unknown> | null
}

interface Resumo24h {
  engine: string; method: string; metodo_label?: string
  execucoes: number; falhas: number; parciais: number; rodando: number
  analisados: number; selecionados: number; erros: number; ultima: string | null
}

interface Jogo {
  id: number
  fixture_id: number | null
  home_team: string | null
  away_team: string | null
  status: string
  reason: string | null
  score: number | null
  probability: number | null
  odd: number | null
  pick_table: string | null
  pick_id: number | null
  context: {
    resumo?: { rotulo: string; valor: string; detalhe?: string }[]
    conclusao?: string
    parcelas?: Record<string, number>
    pontos_fracos?: { rotulo: string; aproveitamento: number }[]
    amostra?: Amostra
  } | null
}

interface Erro {
  id: number
  fixture_id: number | null
  contexto: string | null
  erro: string
  traceback: string | null
  quando: string | null
}

const POR_PAGINA = 15

/** RUNNING não tem tom próprio: é azul-neutro, porque não é bom nem ruim ainda. */
const TOM_DO_STATUS: Record<string, BadgeTone> = {
  COMPLETED: 'green',
  FAILED: 'red',
  PARTIAL: 'amber',
  // RUNNING é azul e não verde de propósito: ainda não é bom nem ruim, e
  // pintar de verde uma execução que pode falhar em dez segundos mente.
  RUNNING: 'blue',
}

const ROTULO_DO_STATUS: Record<string, string> = {
  COMPLETED: 'Concluída',
  FAILED: 'Falhou',
  PARTIAL: 'Parcial',
  RUNNING: 'Rodando',
}

const hora = (iso?: string | null) => {
  if (!iso) return '·'
  // Vem do Postgres como "2026-08-27 19:04:12". Fatiado, e não passado por
  // `new Date`, pelo mesmo motivo do resto do projeto: o timestamp não carrega
  // fuso, e o construtor de Date assume um.
  const t = iso.slice(11, 16)
  return t || iso.slice(0, 10)
}

const diaMes = (iso?: string | null) => {
  if (!iso) return '·'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : a
}

const duracao = (s?: number | null) => {
  if (s == null) return '·'
  if (s < 60) return `${s}s`
  const min = Math.floor(s / 60)
  return `${min}min ${s % 60}s`
}

const pct = (v?: number | null) => {
  if (v == null) return '·'
  const n = Number(v)
  return `${((n <= 1 ? n * 100 : n)).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}%`
}

/* ── Por que essa pick ───────────────────────────────────────────────────── */

function PorQueEssaPick({ jogo }: { jogo: Jogo }) {
  const ctx = jogo.context
  if (!ctx) {
    return (
      <p className="text-[11px] text-ink-4">
        Esta execução não gravou indicadores para este jogo.
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {ctx.resumo && ctx.resumo.length > 0 && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
          {ctx.resumo.map((item, i) => (
            <div key={i} className="flex items-baseline justify-between gap-2 border-b border-line/50 pb-1">
              <dt className="text-[11px] text-ink-3">{item.rotulo}</dt>
              <dd className="text-right">
                <span className="font-mono text-xs text-ink-1 tabular-nums">{item.valor}</span>
                {item.detalhe && (
                  <span className="block text-[10px] text-ink-4 leading-tight">{item.detalhe}</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {ctx.conclusao && (
        <p className="text-xs text-ink-2 leading-relaxed bg-surface-0 border border-line rounded-lg p-3">
          {ctx.conclusao}
        </p>
      )}

      {/* Onde o jogo perdeu ponto. Só faz sentido no descartado · num
        * selecionado, "pontos fracos" seria ruído sobre uma decisão positiva. */}
      {jogo.status !== 'selecionado' && ctx.pontos_fracos && ctx.pontos_fracos.length > 0 && (
        <div>
          <div className="text-[10px] text-ink-4 mb-1">Onde perdeu ponto</div>
          <ul className="space-y-0.5">
            {ctx.pontos_fracos.slice(0, 4).map((f, i) => (
              <li key={i} className="text-[11px] text-ink-3 flex items-baseline gap-2">
                <span className="font-mono text-ink-4 tabular-nums">{pct(f.aproveitamento)}</span>
                {f.rotulo}
              </li>
            ))}
          </ul>
        </div>
      )}

      {ctx.amostra && (
        <div>
          <div className="text-[10px] text-ink-4 mb-1.5">Jogos que o motor leu</div>
          <BlocoAmostra amostra={ctx.amostra} />
        </div>
      )}
    </div>
  )
}

/* ── Tela ────────────────────────────────────────────────────────────────── */

export default function AdminAuditoriaMotores() {
  const [dados, setDados] = useState<{
    disponivel: boolean; total: number
    execucoes: Execucao[]; resumo_24h: Resumo24h[]; motores: Motor[]; erro?: string
  } | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [motor, setMotor] = useState<string>('')
  const [statusFiltro, setStatusFiltro] = useState<string>('')
  const [pagina, setPagina] = useState(0)

  const [aberta, setAberta] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState<{
    execucao: Execucao; jogos: Jogo[]; total: number; erros: Erro[]; erro?: string
  } | null>(null)
  const [filtroJogos, setFiltroJogos] = useState<string>('todos')
  const [carregandoDetalhe, setCarregandoDetalhe] = useState(false)
  const [jogoAberto, setJogoAberto] = useState<number | null>(null)

  const buscar = useCallback((p: number, eng: string, st: string) => {
    setCarregando(true)
    api.get('/admin/motor/execucoes', {
      params: { motor: eng || undefined, status: st || undefined, pagina: p, por_pagina: POR_PAGINA },
    })
      .then(r => setDados(r.data))
      .catch(() => setDados(null))
      .finally(() => setCarregando(false))
  }, [])

  useEffect(() => { buscar(0, motor, statusFiltro) }, [buscar, motor, statusFiltro])

  const abrir = useCallback((runId: string, filtro: string) => {
    setCarregandoDetalhe(true)
    setJogoAberto(null)
    api.get(`/admin/motor/execucoes/${encodeURIComponent(runId)}`, {
      params: { filtro, por_pagina: 25 },
    })
      .then(r => setDetalhe(r.data))
      .catch(() => setDetalhe(null))
      .finally(() => setCarregandoDetalhe(false))
  }, [])

  const alternar = (runId: string) => {
    if (aberta === runId) { setAberta(null); setDetalhe(null); return }
    setAberta(runId)
    setFiltroJogos('todos')
    abrir(runId, 'todos')
  }

  const trocarFiltro = (f: string) => {
    setFiltroJogos(f)
    if (aberta) abrir(aberta, f)
  }

  if (carregando && !dados) return <SpinnerBlock className="py-20" />

  if (!dados?.disponivel) {
    return (
      <EmptyState
        Icon={Cpu}
        title="Sem execução registrada"
        description={dados?.erro ?? 'Nenhum motor registrou execução neste banco ainda. As tabelas de auditoria são criadas na primeira rodada.'}
      />
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-ink-1">
            <Cpu className="w-4 h-4" />
            Auditoria dos Motores
          </h2>
          <p className="text-[11px] text-ink-4 mt-0.5">
            Cada execução com o seu run ID, a versão que rodava e o que ela decidiu.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={motor}
            onChange={e => { setMotor(e.target.value); setPagina(0) }}
            aria-label="Motor"
            options={[
              { value: '', label: 'Todos os motores' },
              ...dados.motores.map(m => ({ value: m.slug, label: m.label })),
            ]}
          />
          <Select
            value={statusFiltro}
            onChange={e => { setStatusFiltro(e.target.value); setPagina(0) }}
            aria-label="Status"
            options={[
              { value: '', label: 'Qualquer status' },
              ...Object.entries(ROTULO_DO_STATUS).map(([k, v]) => ({ value: k, label: v })),
            ]}
          />
          <Button size="sm" variant="ghost" onClick={() => buscar(pagina, motor, statusFiltro)} disabled={carregando}>
            <RefreshCw className={`w-3.5 h-3.5 ${carregando ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
        </div>
      </div>

      {/* Últimas 24h por motor+método. Fica em cima porque é a leitura de
        * conjunto: qual motor está falhando, qual não roda há tempo demais. */}
      {dados.resumo_24h.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {dados.resumo_24h.map(r => (
            <div key={`${r.engine}-${r.method}`} className="card p-3">
              <div className="text-[10px] text-ink-4 truncate">{r.engine}</div>
              <div className="text-xs font-bold text-ink-1 truncate">{r.metodo_label ?? r.method}</div>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span className="font-mono text-lg font-bold tabular-nums text-ink-1">{r.selecionados}</span>
                <span className="text-[10px] text-ink-4">de {r.analisados} analisados</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="text-[10px] text-ink-4">{r.execucoes}x em 24h</span>
                {r.falhas > 0 && <Badge tone="red">{r.falhas} falha(s)</Badge>}
                {r.parciais > 0 && <Badge tone="amber">{r.parciais} parcial</Badge>}
                {r.rodando > 0 && <Badge tone="neutral">rodando</Badge>}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <h3 className="text-sm font-bold text-ink-1">Execuções recentes</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[42rem]">
            <thead>
              <tr className="text-ink-4 text-[10px] border-b border-line">
                <th className="text-left font-medium px-4 py-2">Run ID</th>
                <th className="text-left font-medium px-2 py-2">Motor · método</th>
                <th className="text-left font-medium px-2 py-2">Versão</th>
                <th className="text-left font-medium px-2 py-2">Horário</th>
                <th className="text-right font-medium px-2 py-2">Analisados</th>
                <th className="text-right font-medium px-2 py-2">Picks</th>
                <th className="text-right font-medium px-2 py-2">Erros</th>
                <th className="text-right font-medium px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {dados.execucoes.map(e => (
                <tr
                  key={e.run_id}
                  onClick={() => alternar(e.run_id)}
                  className={`border-b border-line/60 cursor-pointer hover:bg-surface-2/60 transition-colors duration-1 ${
                    aberta === e.run_id ? 'bg-surface-2/60' : ''}`}
                >
                  <td className="px-4 py-2.5 font-mono text-[11px] text-ink-2 whitespace-nowrap">
                    <span className="flex items-center gap-1">
                      <ChevronRight className={`w-3 h-3 text-ink-4 transition-transform duration-1 ${
                        aberta === e.run_id ? 'rotate-90' : ''}`} />
                      {e.run_id}
                    </span>
                  </td>
                  <td className="px-2 py-2.5 text-ink-2">
                    {e.engine} · {e.metodo_label ?? e.method}
                  </td>
                  <td className="px-2 py-2.5 font-mono text-[11px] text-ink-4">v{e.engine_version}</td>
                  <td className="px-2 py-2.5 text-ink-3 whitespace-nowrap">
                    {hora(e.iniciada_em)}
                    <span className="text-ink-4"> · {duracao(e.duracao_s)}</span>
                  </td>
                  <td className="px-2 py-2.5 text-right font-mono tabular-nums text-ink-2">{e.analisados}</td>
                  <td className={`px-2 py-2.5 text-right font-mono tabular-nums ${
                    e.selecionados > 0 ? 'text-green-400' : 'text-ink-4'}`}>{e.selecionados}</td>
                  <td className={`px-2 py-2.5 text-right font-mono tabular-nums ${
                    e.erros > 0 ? 'text-red-400' : 'text-ink-4'}`}>{e.erros}</td>
                  <td className="px-4 py-2.5 text-right">
                    <Badge tone={TOM_DO_STATUS[e.status] ?? 'neutral'}>
                      {ROTULO_DO_STATUS[e.status] ?? e.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {dados.total > POR_PAGINA && (
          <div className="px-4 py-3 border-t border-line">
            <Pagination
              page={pagina}
              pageSize={POR_PAGINA}
              total={dados.total}
              unit="execuções"
              onChange={p => { setPagina(p); buscar(p, motor, statusFiltro) }}
            />
          </div>
        )}
      </div>

      {/* Dentro de uma execução */}
      {aberta && (
        <div className="card p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-line flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-ink-1 font-mono">{aberta}</h3>
              {detalhe?.execucao && (
                <p className="text-[11px] text-ink-4">
                  {detalhe.execucao.engine} · {detalhe.execucao.metodo_label ?? detalhe.execucao.method}
                  {' '}· v{detalhe.execucao.engine_version} · {diaMes(detalhe.execucao.dia)}
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-1">
              {[
                { k: 'todos', r: 'Todos' },
                { k: 'selecionados', r: 'Selecionados' },
                { k: 'descartados', r: 'Descartados' },
                { k: 'erros', r: 'Erros' },
              ].map(f => (
                <button
                  key={f.k}
                  onClick={() => trocarFiltro(f.k)}
                  className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors duration-1 ${
                    filtroJogos === f.k
                      ? 'border-line-strong bg-surface-2 text-ink-1'
                      : 'border-line text-ink-3 hover:text-ink-2'}`}
                >
                  {f.r}
                </button>
              ))}
            </div>
          </div>

          {carregandoDetalhe ? (
            <SpinnerBlock className="py-10" />
          ) : !detalhe ? (
            <p className="px-4 py-6 text-xs text-ink-4">Não deu pra ler esta execução.</p>
          ) : (
            <div className="divide-y divide-line">
              {detalhe.erros.length > 0 && (
                <div className="px-4 py-3 space-y-2">
                  <div className="flex items-center gap-1.5 text-[11px] text-red-400">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {detalhe.erros.length} erro(s) nesta execução
                  </div>
                  {detalhe.erros.map(er => (
                    <div key={er.id} className="bg-surface-0 border border-line rounded-lg p-2.5">
                      <div className="text-[11px] text-ink-2">{er.contexto ?? 'sem contexto'}</div>
                      <div className="text-[11px] font-mono text-red-400 break-all mt-0.5">{er.erro}</div>
                    </div>
                  ))}
                </div>
              )}

              {detalhe.jogos.length === 0 && filtroJogos !== 'erros' && (
                <p className="px-4 py-6 text-xs text-ink-4 flex items-center gap-2">
                  <CircleSlash className="w-3.5 h-3.5" />
                  Nenhum jogo neste filtro.
                </p>
              )}

              {detalhe.jogos.map(j => {
                const escolhido = j.status === 'selecionado'
                const aberto = jogoAberto === j.id
                return (
                  <div key={j.id}>
                    <button
                      onClick={() => setJogoAberto(aberto ? null : j.id)}
                      className="w-full text-left px-4 py-2.5 hover:bg-surface-2/50 transition-colors duration-1"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="flex items-center gap-2 min-w-0">
                          {escolhido
                            ? <Check className="w-3.5 h-3.5 text-green-400 shrink-0" />
                            : <X className="w-3.5 h-3.5 text-ink-4 shrink-0" />}
                          <span className="text-xs text-ink-1 truncate">
                            {j.home_team ?? '·'} x {j.away_team ?? '·'}
                          </span>
                        </span>
                        <span className="flex items-center gap-3 text-[11px] shrink-0">
                          {j.score != null && (
                            <span className="font-mono tabular-nums text-ink-1">
                              Score {Number(j.score).toFixed(0)}
                            </span>
                          )}
                          {j.probability != null && (
                            <span className="font-mono tabular-nums text-ink-3">{pct(j.probability)}</span>
                          )}
                          {j.odd != null && (
                            <span className="font-mono tabular-nums text-ink-4">@{Number(j.odd).toFixed(2)}</span>
                          )}
                        </span>
                      </div>
                      {/* O motivo é a razão desta tela existir: "descartado" sem
                        * ele não diferencia limiar apertado de dado ausente. */}
                      {j.reason && (
                        <p className="text-[11px] text-ink-4 mt-0.5 ml-[1.375rem] leading-snug">{j.reason}</p>
                      )}
                    </button>
                    {aberto && (
                      <div className="px-4 pb-4 pt-1">
                        <div className="text-[10px] text-ink-4 mb-2 uppercase tracking-wide">
                          Por que essa pick?
                        </div>
                        <PorQueEssaPick jogo={j} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {carregando && (
        <div className="flex justify-center py-2">
          <Loader2 className="w-4 h-4 animate-spin text-ink-4" />
        </div>
      )}
    </div>
  )
}
