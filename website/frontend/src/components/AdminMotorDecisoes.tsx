import { useCallback, useEffect, useState } from 'react'
import { Brain, ChevronRight, CircleSlash, RefreshCw, Target, Users } from 'lucide-react'
import api from '../services/api'
import AdminAmostra, { type AlvoAmostra } from './AdminAmostra'
import { Button, EmptyState, Pagination, SpinnerBlock } from './ui'

/*
 * Por que ESTE pick, e não os outros jogos do dia.
 *
 * O pick publicado é a ponta. A pergunta de baixo dela nunca teve tela: que
 * partidas o motor considerou, que mercados ele pontuou em cada uma, e por que
 * os outros não venceram.
 *
 * O dado existe desde 07/08 e o site nunca leu · `engine_decisions`, gravada
 * por engine_pipelines/decision_log.py. Uma linha por fixture, em três formas:
 *
 *   avaliado    o motor rodou · traz TODOS os mercados pontuados, com odd,
 *               taxa real, amostra, EV e o score final
 *   descartado  o jogo caiu ANTES do motor, e o motivo diz qual porta fechou
 *   sem_pick    o pipeline terminou o dia sem candidato nenhum
 *
 * A leitura da tela é uma conta de três colunas: avaliados, quantos tinham
 * candidato aprovado, quantos viraram pick. Dia vazio com 30 avaliados e zero
 * aprovados é limiar apertado; dia vazio com zero avaliados é coleta furada, e
 * o lugar de resolver isso é a aba Dados.
 *
 * Nada aqui escreve. Log de decisão que a tela altera deixa de ser log.
 */

interface Resumo {
  pipeline: string
  rotulo: string
  avaliados: number
  descartados: number
  sem_pick: number
  com_aprovado: number
  picks: number | null
}

interface Motivo { pipeline: string; reason: string; n: number }

interface Candidato {
  market_type?: string | null
  line?: string | null
  direcao?: string | null
  odd?: number | null
  taxa_real?: number | null
  probability?: number | null
  amostra?: number | string | null
  confidence?: number | null
  ev?: number | null
  edge?: number | null
  final_score?: number | null
  context_score?: number | null
  profile_score?: number | null
  line_score?: number | null
  eligible?: boolean
  is_best_pick?: boolean
  motivos_reprovacao?: string[]
  /* Rastro (2026-08-27) · linhas e famílias que o motor viu e não levou.
   * `origem` ausente = linha gravada antes do rastro existir, e ela sempre
   * foi o mercado. Ler como 'candidato' mantém o histórico legível. */
  origem?: 'candidato' | 'rastro'
  nivel?: 'mercado' | 'linha' | 'familia'
  rastro_status?: 'avaliada' | 'descartada_sem_calcular' | 'eliminada'
  market_name?: string | null
  scope?: string | null
}

/** Um mercado com todas as linhas que o motor olhou dentro dele. */
interface Mercado {
  chave: string
  rotulo: string
  vencedor: Candidato | null
  linhas: Candidato[]
  eliminada: Candidato | null
}

/* O motor devolve UM candidato por mercado (a linha que venceu lá dentro), e
 * era só isso que a tela tinha. Daí a pergunta que abriu esta mudança: "cadê o
 * mercado de gols, por que só tem Under?" · o Over existia, foi calculado e
 * perdeu, e nada disso chegava aqui.
 *
 * Agora o log traz as três camadas na mesma lista, e a tela remonta a árvore:
 * mercado -> linhas, com a vencedora em destaque e as outras embaixo, cada
 * uma com o motivo. Família eliminada antes das linhas (handicap, resultado,
 * cartões sem árbitro) vira uma linha só, apagada, com o porquê. */
const agruparPorMercado = (cands: Candidato[]): Mercado[] => {
  const mapa = new Map<string, Mercado>()
  const pegar = (c: Candidato) => {
    const chave = `${c.market_type ?? '?'}${c.scope ? `·${c.scope}` : ''}`
    let m = mapa.get(chave)
    if (!m) {
      m = { chave, rotulo: c.market_type ?? '?', vencedor: null, linhas: [], eliminada: null }
      mapa.set(chave, m)
    }
    return m
  }
  for (const c of cands) {
    const m = pegar(c)
    if (c.origem === 'rastro' && c.nivel === 'familia') m.eliminada = c
    else if (c.origem === 'rastro') m.linhas.push(c)
    else m.vencedor = c
  }
  // Mercado com pick escolhido primeiro, depois os que tiveram candidato,
  // depois os eliminados · é a ordem em que se procura resposta.
  const peso = (m: Mercado) =>
    m.vencedor?.is_best_pick ? 0 : m.vencedor?.eligible ? 1 : m.vencedor ? 2 : 3
  return [...mapa.values()].sort((a, b) => peso(a) - peso(b) || a.rotulo.localeCompare(b.rotulo))
}

interface Linha {
  id: number
  dia: string | null
  pipeline: string
  fixture_id: number | null
  home_team: string | null
  away_team: string | null
  status: string
  reason: string | null
  candidates: Candidato[] | null
  matchup: Record<string, unknown> | null
  context: Record<string, unknown> | null
  gravada_em: string | null
}

const POR_PAGINA = 10

const diaMes = (iso?: string | null) => {
  if (!iso) return '·'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : a
}

const num = (v: number | null | undefined, casas = 2) =>
  v == null ? '·' : v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas })

/** Taxa/probabilidade chega em 0..1 do motor e em 0..100 de alguns modelos. */
const pct = (v: number | null | undefined) => {
  if (v == null) return '·'
  const n = v <= 1 ? v * 100 : v
  return `${n.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}%`
}

export default function AdminMotorDecisoes() {
  const [dados, setDados] = useState<{
    disponivel: boolean; data: string | null
    dias: { dia: string; n: number }[]
    pipelines: Resumo[]; motivos: Motivo[]; erro?: string
  } | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [dia, setDia] = useState<string | null>(null)

  const [pipeline, setPipeline] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('avaliado')
  const [linhas, setLinhas] = useState<{
    total: number; linhas: Linha[]; virou_pick: number[]; erro?: string
  } | null>(null)
  const [pagina, setPagina] = useState(0)
  const [carregandoLinhas, setCarregandoLinhas] = useState(false)
  const [aberta, setAberta] = useState<number | null>(null)
  /* O log guarda o NOME do time, não o id · é o que o motor tem à mão quando
   * grava. O id é resolvido pelo fixture na hora de abrir a amostra. */
  const [amostra, setAmostra] = useState<AlvoAmostra | null>(null)

  const buscarResumo = useCallback((quando?: string | null) => {
    setCarregando(true)
    api.get('/admin/motor/decisoes', { params: quando ? { data: quando } : {} })
      .then(r => {
        setDados(r.data)
        setDia(r.data?.data ?? null)
      })
      .catch(() => setDados(null))
      .finally(() => setCarregando(false))
  }, [])

  useEffect(() => { buscarResumo() }, [buscarResumo])

  const buscarLinhas = useCallback((p: number, pipe: string, st: string, quando: string | null) => {
    setCarregandoLinhas(true)
    setAberta(null)
    api.get('/admin/motor/decisoes/linhas', {
      params: { pipeline: pipe, status: st || undefined, data: quando || undefined,
                pagina: p, por_pagina: POR_PAGINA },
    })
      .then(r => setLinhas(r.data))
      .catch(() => setLinhas({ total: 0, linhas: [], virou_pick: [], erro: 'Não deu pra ler as decisões.' }))
      .finally(() => setCarregandoLinhas(false))
  }, [])

  const abrirAmostra = async (fixtureId: number, lado: 'casa' | 'fora') => {
    try {
      const r = await api.get(`/admin/dados/partidas/${fixtureId}/times`)
      const d = r.data
      setAmostra({
        tipo: 'time',
        teamId: lado === 'casa' ? d.home_team_id : d.away_team_id,
        leagueId: d.league_id,
        season: d.season,
        nome: lado === 'casa' ? d.mandante : d.visitante,
      })
    } catch {
      // Partida sem linha em match_statistics nem em fixtures: nada a abrir.
      // Silencioso de propósito · é um atalho, não a função da tela.
    }
  }

  const abrirPipeline = (pipe: string, st = status) => {
    setPipeline(pipe)
    setStatus(st)
    setPagina(0)
    buscarLinhas(0, pipe, st, dia)
  }

  const trocarDia = (novo: string) => {
    setDia(novo)
    setPipeline(null)
    setLinhas(null)
    buscarResumo(novo)
  }

  if (carregando && !dados) return <SpinnerBlock className="py-20" />

  if (!dados?.disponivel) {
    return (
      <EmptyState
        Icon={Brain}
        title="Sem decisão registrada"
        description={dados?.erro ?? 'Nenhum pipeline gravou em engine_decisions neste banco ainda. A tabela é criada pelo motor, não pelas migrações do site.'}
      />
    )
  }

  const motivosDoPipeline = pipeline
    ? dados.motivos.filter(m => m.pipeline === pipeline)
    : dados.motivos

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-bold text-ink-1">
          <Brain className="w-4 h-4" />
          O que o motor olhou
        </h2>
        <div className="flex items-center gap-2">
          {dados.dias.length > 0 && (
            <select
              value={dia ?? ''}
              onChange={e => trocarDia(e.target.value)}
              className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
              aria-label="Dia"
            >
              {dados.dias.map(d => (
                <option key={d.dia} value={d.dia}>
                  {diaMes(d.dia)} · {d.n} linha(s)
                </option>
              ))}
            </select>
          )}
          <Button size="sm" variant="ghost" onClick={() => buscarResumo(dia)} disabled={carregando}>
            <RefreshCw className={`w-3.5 h-3.5 ${carregando ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
        </div>
      </div>

      {/* A conta de três colunas. Sem as três lado a lado, "não saiu pick hoje"
        * não distingue limiar apertado de coleta furada. */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <h3 className="text-sm font-bold text-ink-1">Dia {diaMes(dia)} · por pipeline</h3>
          <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
            Avaliados é quanto o motor rodou. Com aprovado é em quantos desses sobrou candidato.
            Picks é o que foi publicado · entre um e outro ainda passam o gate de IA, a
            exclusividade de partida e o teto do dia.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[30rem]">
            <thead>
              <tr className="text-ink-4 text-[10px] border-b border-line">
                <th className="text-left font-medium px-4 py-2">Pipeline</th>
                <th className="text-right font-medium px-2 py-2">Avaliados</th>
                <th className="text-right font-medium px-2 py-2">Com aprovado</th>
                <th className="text-right font-medium px-2 py-2">Descartados</th>
                <th className="text-right font-medium px-4 py-2">Picks</th>
              </tr>
            </thead>
            <tbody>
              {dados.pipelines.map(p => {
                const vazio = p.avaliados === 0 && p.descartados === 0 && p.sem_pick === 0
                const ativo = pipeline === p.pipeline
                return (
                  <tr
                    key={p.pipeline}
                    onClick={() => !vazio && abrirPipeline(p.pipeline)}
                    className={`border-b border-line/60 ${
                      vazio ? 'opacity-40' : 'cursor-pointer hover:bg-surface-2/60'} ${
                      ativo ? 'bg-surface-2/60' : ''} transition-colors duration-1`}
                  >
                    <td className="px-4 py-2.5 text-ink-2 font-medium">
                      <span className="flex items-center gap-1.5">
                        {p.rotulo}
                        {!vazio && <ChevronRight className="w-3 h-3 text-ink-4" />}
                      </span>
                    </td>
                    <td className="px-2 py-2.5 text-right font-mono tabular-nums text-ink-2">{p.avaliados}</td>
                    <td className={`px-2 py-2.5 text-right font-mono tabular-nums ${
                      p.com_aprovado > 0 ? 'text-green-400' : 'text-ink-4'}`}>{p.com_aprovado}</td>
                    <td className="px-2 py-2.5 text-right font-mono tabular-nums text-ink-4">{p.descartados}</td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums text-ink-1 font-bold">
                      {p.picks == null ? '·' : p.picks}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Onde os jogos morreram. Motivo é texto curto e estável de propósito ·
        * é o que permite agrupar em vez de ler linha por linha. */}
      {motivosDoPipeline.length > 0 && (
        <div className="card p-4">
          <h3 className="flex items-center gap-2 text-sm font-bold text-ink-1 mb-2">
            <CircleSlash className="w-4 h-4 text-ink-3" />
            Onde os jogos morreram {pipeline && <span className="text-ink-4 font-normal">· só {pipeline}</span>}
          </h3>
          <div className="space-y-1.5">
            {motivosDoPipeline.slice(0, 12).map((m, i) => (
              <div key={i} className="flex items-baseline justify-between gap-3 text-[11px]">
                <span className="text-ink-3 min-w-0">
                  {!pipeline && <span className="font-mono text-ink-4 mr-1.5">{m.pipeline.replace('_ENGINE', '')}</span>}
                  {m.reason}
                </span>
                <span className="font-mono tabular-nums text-ink-2 shrink-0">{m.n}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Partida a partida. */}
      {pipeline && (
        <div className="card p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-line flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-ink-1">{pipeline.replace('_ENGINE', '')} · partida a partida</h3>
              <p className="text-[11px] text-ink-4 mt-0.5">
                Toque na partida para ver todos os mercados que o motor pontuou nela.
              </p>
            </div>
            <div className="flex gap-1.5 shrink-0">
              {[['avaliado', 'Avaliadas'], ['descartado', 'Descartadas'], ['', 'Todas']].map(([valor, texto]) => (
                <button
                  key={texto}
                  type="button"
                  onClick={() => abrirPipeline(pipeline, valor)}
                  className={`text-[10px] px-2 py-1.5 rounded-md border transition-colors duration-1 ${
                    status === valor
                      ? 'border-ink-4 text-ink-1'
                      : 'border-line text-ink-4 hover:text-ink-2'}`}
                >
                  {texto}
                </button>
              ))}
            </div>
          </div>

          {carregandoLinhas ? (
            <SpinnerBlock className="py-10" />
          ) : linhas?.erro ? (
            <p className="px-4 py-6 text-[11px] text-red-400">{linhas.erro}</p>
          ) : !linhas?.linhas.length ? (
            <EmptyState
              compact
              Icon={Target}
              title="Nada neste recorte"
              description="Nenhuma linha para este pipeline, dia e situação."
            />
          ) : (
            <>
              <div className="divide-y divide-line/60">
                {linhas.linhas.map(l => {
                  const escancarada = aberta === l.id
                  const cands = l.candidates ?? []
                  const mercados = agruparPorMercado(cands)
                  const aprovados = cands.filter(c => c.eligible).length
                  const virou = l.fixture_id != null && linhas.virou_pick.includes(l.fixture_id)
                  return (
                    <div key={l.id}>
                      <button
                        type="button"
                        onClick={() => setAberta(escancarada ? null : l.id)}
                        aria-expanded={escancarada}
                        className="w-full text-left px-4 py-2.5 hover:bg-surface-2/60 transition-colors duration-1"
                      >
                        <div className="flex items-baseline gap-2">
                          <span className="flex-1 min-w-0 text-sm text-ink-2 truncate">
                            {l.home_team ?? 'Time ?'} <span className="text-ink-4">x</span>{' '}
                            {l.away_team ?? (l.status === 'sem_pick' ? '' : 'Time ?')}
                            {l.status === 'sem_pick' && <span className="text-ink-4">o pipeline inteiro</span>}
                          </span>
                          {virou && (
                            <span className="text-[10px] font-bold text-green-400 shrink-0">virou pick</span>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5 text-[10px] text-ink-4">
                          {l.status === 'avaliado' ? (
                            <>
                              {/* Mercados, nao linhas · o log passou a trazer as
                                * duas coisas e contar tudo junto diria "38
                                * mercados" num jogo que teve 9. */}
                              <span className="font-mono tabular-nums">{mercados.length} mercado(s)</span>
                              <span className={`font-mono tabular-nums ${
                                aprovados > 0 ? 'text-green-400' : 'text-yellow-400'}`}>
                                {aprovados} aprovado(s)
                              </span>
                            </>
                          ) : (
                            <span className="text-yellow-400 truncate max-w-full">{l.reason}</span>
                          )}
                          {l.fixture_id && <span className="font-mono">fixture {l.fixture_id}</span>}
                        </div>
                      </button>

                      {escancarada && cands.length > 0 && (
                        <div className="px-4 pb-3 space-y-2">
                          {mercados.map(m => {
                            const v = m.vencedor
                            const outras = m.linhas
                            const morto = !v && !!m.eliminada
                            return (
                              <div key={m.chave}
                                   className={`rounded-lg border overflow-hidden ${
                                     v?.is_best_pick ? 'border-green-500/40' : 'border-line/60'}`}>
                                <div className={`flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 px-3 py-1.5 ${
                                  v?.is_best_pick ? 'bg-green-500/10' : 'bg-surface-2/40'}`}>
                                  <span className={`text-[11px] font-bold ${
                                    morto ? 'text-ink-4' : 'text-ink-1'}`}>
                                    {m.rotulo}
                                    {v?.is_best_pick && (
                                      <span className="text-[9px] font-bold text-green-400 ml-1.5">escolhido</span>
                                    )}
                                  </span>
                                  <span className="text-[10px] font-mono tabular-nums text-ink-4">
                                    {morto
                                      ? 'nem chegou as linhas'
                                      : `${outras.length + (v ? 1 : 0)} linha(s) olhada(s)`}
                                  </span>
                                </div>

                                {/* Familia que morreu antes de qualquer linha ·
                                  * o motivo e a unica coisa que ela tem pra dizer. */}
                                {morto && (
                                  <p className="px-3 py-1.5 text-[10px] text-yellow-400/80 leading-relaxed">
                                    {m.eliminada?.motivos_reprovacao?.join(' · ')}
                                  </p>
                                )}

                                {!morto && (
                                  <div className="overflow-x-auto">
                                    <table className="w-full text-[11px] min-w-[34rem]">
                                      <thead>
                                        <tr className="text-[10px] text-ink-4 border-b border-line/60">
                                          <th className="text-left font-medium px-3 py-1.5">Linha</th>
                                          <th className="text-right font-medium px-2 py-1.5">Odd</th>
                                          <th className="text-right font-medium px-2 py-1.5">Taxa</th>
                                          <th className="text-right font-medium px-2 py-1.5">Amostra</th>
                                          <th className="text-right font-medium px-2 py-1.5">EV</th>
                                          <th className="text-right font-medium px-3 py-1.5">Score</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {(v ? [v, ...outras] : outras).map((c, i) => {
                                          const venceu = c === v
                                          const semConta = c.rastro_status === 'descartada_sem_calcular'
                                          return (
                                            <tr key={i}
                                                className={`odd:bg-surface-2/30 ${
                                                  venceu ? 'bg-surface-2/60' : ''}`}>
                                              <td className="px-3 py-1.5">
                                                <span className={venceu && c.eligible ? 'text-ink-1' : 'text-ink-4'}>
                                                  {c.line ?? c.market_name ?? '?'}
                                                  {c.direcao && <span className="text-ink-4 ml-1">{c.direcao}</span>}
                                                </span>
                                                {venceu && (
                                                  <span className="text-[9px] text-ink-3 ml-1.5">
                                                    linha do mercado
                                                  </span>
                                                )}
                                                {/* "nem calculou" e o ponto: a odd
                                                  * fora da faixa mata a linha antes
                                                  * da conta, entao taxa/EV ficam
                                                  * vazios por construcao, nao por
                                                  * falha. */}
                                                {semConta && (
                                                  <span className="text-[9px] font-mono text-ink-4 ml-1.5">
                                                    nem calculou
                                                  </span>
                                                )}
                                                {!!c.motivos_reprovacao?.length && (
                                                  <p className="text-[10px] text-yellow-400/80 mt-0.5 leading-snug">
                                                    {c.motivos_reprovacao.join(' · ')}
                                                  </p>
                                                )}
                                              </td>
                                              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink-2">
                                                {num(c.odd)}
                                              </td>
                                              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink-2">
                                                {pct(c.taxa_real ?? c.probability)}
                                              </td>
                                              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink-4">
                                                {c.amostra ?? '·'}
                                              </td>
                                              <td className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                                                (c.ev ?? 0) > 0 ? 'text-green-400' : 'text-ink-4'}`}>
                                                {num(c.ev)}
                                              </td>
                                              <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ink-1">
                                                {num(c.final_score ?? c.line_score ?? c.confidence)}
                                              </td>
                                            </tr>
                                          )
                                        })}
                                      </tbody>
                                    </table>
                                  </div>
                                )}
                              </div>
                            )
                          })}

                          <p className="text-[10px] text-ink-4 leading-relaxed">
                            Cada bloco e um mercado, e dentro dele estao TODAS as linhas que o motor
                            olhou · a que representou o mercado vem primeiro, as outras embaixo com o
                            motivo de terem perdido. Linha marcada "nem calculou" tem a odd fora da
                            faixa do pipeline: ela e descartada antes da conta, porque calcular nao
                            mudaria o desfecho. Taxa e a frequencia historica do evento, nao a odd
                            implicita · edge alto e alerta, nao qualidade.
                            {l.gravada_em && ` Gravada em ${l.gravada_em.slice(0, 16).replace('T', ' ')}.`}
                          </p>
                          {/* De onde vieram esses numeros: a media do time na
                            * temporada, e os jogos que a formaram. E a pergunta
                            * seguinte natural de quem olha uma taxa estranha. */}
                          {l.fixture_id && (
                            <div className="flex flex-wrap gap-2">
                              <Button size="sm" variant="ghost"
                                      onClick={() => abrirAmostra(l.fixture_id!, 'casa')}>
                                <Users className="w-3.5 h-3.5" />
                                Amostra do {l.home_team ?? 'mandante'}
                              </Button>
                              <Button size="sm" variant="ghost"
                                      onClick={() => abrirAmostra(l.fixture_id!, 'fora')}>
                                <Users className="w-3.5 h-3.5" />
                                Amostra do {l.away_team ?? 'visitante'}
                              </Button>
                            </div>
                          )}
                        </div>
                      )}

                      {escancarada && cands.length === 0 && (
                        <p className="px-4 pb-3 text-[11px] text-ink-3 leading-relaxed">
                          {l.reason ?? 'Sem candidato registrado nesta linha.'}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
              <Pagination
                page={pagina}
                pageSize={POR_PAGINA}
                total={linhas.total}
                onChange={p => { setPagina(p); buscarLinhas(p, pipeline, status, dia) }}
                unit="partidas"
              />
            </>
          )}
        </div>
      )}

      {amostra && <AdminAmostra alvo={amostra} onClose={() => setAmostra(null)} />}
    </div>
  )
}
