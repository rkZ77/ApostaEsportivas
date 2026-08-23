import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Database, RefreshCw } from 'lucide-react'
import api from '../services/api'
import { Button, EmptyState, Pagination, SpinnerBlock, StatTile } from './ui'

/*
 * O que o motor tem pra ler, e onde estão os buracos.
 *
 * A aba Pipeline responde "o sistema está de pé". Esta responde outra coisa:
 * "o motor está enxergando?". São perguntas diferentes, e a segunda não tinha
 * tela · jogo encerrado sem estatística não quebra nada, só deixa a média
 * velha, e média velha não parece defeito de coisa nenhuma.
 *
 * O número que manda aqui é o de partidas encerradas sem estatística. Ele é a
 * distância entre o que aconteceu no mundo e o que o motor sabe.
 */

interface Dados {
  contagem: Record<string, number | null>
  frescor: {
    ultima_partida?: string | null
    ultimos_7_dias?: number | null
    medias_atualizadas_em?: string | null
  }
  buracos: { total?: number | null; mais_antigo?: string | null }
  varredura: {
    habilitada?: boolean; intervalo_s?: number; janela_dias?: number
    rodando?: boolean; ultima_passada_ha_s?: number | null
    ultimo_resultado?: unknown; erro?: string
  }
}

/** Par [casa, fora] de cada família. `null` é o provedor não ter devolvido. */
type Par = [number | null, number | null]

interface Partida {
  fixture_id: number
  data: string | null
  status: string | null
  referee: string | null
  coletada_em: string | null
  liga: string | null
  mandante: string | null
  visitante: string | null
  zerada: boolean
  completas: number
  stats: Record<string, Par>
}

interface Familia {
  chave: string
  rotulo: string
  modo: 'soma' | 'lado'
  com_dado: number
  media: number | null
}

interface Historico {
  total: number
  teto: number
  familias: number
  resumo: Familia[]
  zeradas: number
  partidas: Partida[]
  erro?: string
}

const POR_PAGINA = 10

const numero = (v: number | null | undefined) =>
  v == null ? '·' : v.toLocaleString('pt-BR')

const decimal = (v: number | null | undefined) =>
  v == null ? '·' : v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** "2026-08-22T21:30:00" -> "22/08". Fatiado, nunca por `new Date`: as datas
 *  deste banco já estão em Brasília e qualquer parse reintroduz fuso. */
const diaMes = (iso?: string | null) => {
  if (!iso) return '·'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : a
}

export default function AdminDados() {
  const [dados, setDados] = useState<Dados | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  const [historico, setHistorico] = useState<Historico | null>(null)
  const [pagina, setPagina] = useState(0)
  const [trocandoPagina, setTrocandoPagina] = useState(false)
  const [aberta, setAberta] = useState<number | null>(null)

  const buscarHistorico = useCallback((p: number) => {
    setTrocandoPagina(true)
    setAberta(null)
    api.get('/admin/dados/partidas', { params: { pagina: p, por_pagina: POR_PAGINA } })
      .then(r => setHistorico(r.data))
      .catch(() => setHistorico({
        total: 0, teto: 40, familias: 0, resumo: [], zeradas: 0,
        partidas: [], erro: 'Não deu pra ler as partidas.',
      }))
      .finally(() => setTrocandoPagina(false))
  }, [])

  const buscar = () => {
    setCarregando(true)
    setErro('')
    api.get('/admin/dados')
      .then(r => setDados(r.data))
      .catch(e => setErro(e?.response?.data?.detail ?? 'Não deu pra ler o estado do banco.'))
      .finally(() => setCarregando(false))
    // Volta pra primeira página: "Atualizar" com a página 3 na tela mostraria
    // a terceira dezena de uma lista que acabou de mudar embaixo.
    setPagina(0)
    buscarHistorico(0)
  }

  useEffect(buscar, [])

  const irPara = (p: number) => {
    setPagina(p)
    buscarHistorico(p)
  }

  if (carregando && !dados) return <SpinnerBlock className="py-20" />
  if (erro) return <p className="text-red-400 text-sm py-8">{erro}</p>
  if (!dados) return null

  const buracos = dados.buracos?.total ?? 0
  const v = dados.varredura ?? {}

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-bold text-ink-1">
          <Database className="w-4 h-4" />
          Dados no banco
        </h2>
        <Button size="sm" variant="ghost" onClick={buscar} disabled={carregando}>
          <RefreshCw className={`w-3.5 h-3.5 ${carregando ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </div>

      {/* O buraco vem primeiro porque é o único número acionável da tela. */}
      <div className={`card p-4 border ${buracos > 0 ? 'border-yellow-500/40 bg-yellow-500/5' : 'border-line'}`}>
        <div className="flex items-start gap-3">
          {buracos > 0
            ? <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
            : <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0 mt-0.5" />}
          <div>
            <p className="text-sm font-bold text-ink-1">
              {buracos > 0
                ? `${numero(buracos)} partida(s) encerrada(s) sem estatística`
                : 'Toda partida encerrada tem estatística'}
            </p>
            <p className="text-[11px] text-ink-3 mt-1 leading-relaxed">
              {buracos > 0 ? (
                <>
                  É a distância entre o que aconteceu e o que o motor sabe · sem a linha
                  em <span className="font-mono">match_statistics</span>, o jogo não entra
                  em baseline de liga, média de time, média de árbitro nem confronto direto.
                  {dados.buracos?.mais_antigo && ` Mais antigo: ${diaMes(dados.buracos.mais_antigo)}.`}
                </>
              ) : (
                'O motor está lendo tudo que já foi apitado dentro da janela coletada.'
              )}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <StatTile label="Jogos coletados"  value={numero(dados.contagem?.fixtures)} />
        <StatTile label="Com estatística"  value={numero(dados.contagem?.match_statistics)} tone="green" />
        <StatTile label="Médias por time"  value={numero(dados.contagem?.team_statistics)} />
        <StatTile label="Times"            value={numero(dados.contagem?.teams)} />
        <StatTile label="Últimos 7 dias"   value={numero(dados.frescor?.ultimos_7_dias)}
          hint="partidas com estatística" />
        <StatTile label="Última partida lida" value={diaMes(dados.frescor?.ultima_partida)}
          hint={`médias recalculadas em ${diaMes(dados.frescor?.medias_atualizadas_em)}`} />
        <StatTile label="Picks VIP"        value={numero(dados.contagem?.picks_vip)} />
        <StatTile label="Picks free"       value={numero(dados.contagem?.picks_free)} />
      </div>

      {/* Coleta automática · o que substituiu o clique manual. */}
      <div className="card p-4">
        <h3 className="text-sm font-bold text-ink-1 mb-2">Coleta automática</h3>
        {v.erro ? (
          <p className="text-[11px] text-red-400">{v.erro}</p>
        ) : (
          <>
            <p className="text-[11px] text-ink-3 leading-relaxed">
              {v.habilitada
                ? <>Ligada · roda no máximo a cada {Math.round((v.intervalo_s ?? 600) / 60)} min,
                    e só quando há jogo encerrado sem estatística nos últimos {v.janela_dias} dias.</>
                : <>Desligada neste ambiente. Ela só roda em produção · a chave da API é uma
                    conta só para os três ambientes, então dev consumiria a cota do site real.</>}
            </p>
            <div className="flex items-center gap-4 mt-2 text-[11px] font-mono text-ink-4">
              <span>{v.rodando ? 'rodando agora' : 'ociosa'}</span>
              {v.ultima_passada_ha_s != null && (
                <span>última passada há {Math.round(v.ultima_passada_ha_s / 60)} min</span>
              )}
            </div>
            {v.ultimo_resultado != null && (
              <pre className="mt-2 text-[10px] text-ink-4 bg-surface-2 rounded p-2 overflow-x-auto">
                {JSON.stringify(v.ultimo_resultado)}
              </pre>
            )}
          </>
        )}
      </div>

      {/* Cobertura e média andam juntas de propósito.
        *
        * Cobertura sozinha não vê o jogo coletado zerado (zero não é nulo).
        * Média sozinha não diz se saiu de 40 partidas ou de 2. Lado a lado,
        * número torto e amostra curta ficam visíveis na mesma olhada. */}
      {historico && !historico.erro && historico.resumo.length > 0 && (
        <div className="card p-4">
          <h3 className="text-sm font-bold text-ink-1">
            Médias das últimas {historico.total} partidas
          </h3>
          <p className="text-[11px] text-ink-4 mt-0.5 mb-3">
            Média por partida de cada estatística que o banco guarda, e em quantos desses
            jogos ela veio preenchida. Amarelo é estatística que faltou em algum jogo.
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {historico.resumo.map(f => {
              const falta = f.com_dado < historico.total
              return (
                <div
                  key={f.chave}
                  className={`rounded-lg border p-2.5 ${
                    falta ? 'border-yellow-500/40 bg-yellow-500/5' : 'border-line'}`}
                >
                  <p className="text-[10px] text-ink-4 leading-tight truncate" title={f.rotulo}>
                    {f.rotulo}
                  </p>
                  <p className="font-mono text-base font-black text-ink-1 tabular-nums leading-tight mt-0.5">
                    {decimal(f.media)}
                  </p>
                  <p className={`text-[10px] font-mono tabular-nums ${
                    falta ? 'text-yellow-400' : 'text-ink-4'}`}>
                    {f.com_dado}/{historico.total} jogos
                  </p>
                </div>
              )
            })}
          </div>

          <p className="text-[10px] text-ink-4 mt-3 leading-relaxed">
            Posse e precisão de passe são média por lado, não soma · somadas dariam 100% em
            todo jogo. São as duas que servem de aferição: posse média longe de 50 é coleta
            torta, não jogo estranho.
          </p>
        </div>
      )}

      {/* Partida a partida · o que o motor leu, e o que veio vazio na linha. */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <h3 className="text-sm font-bold text-ink-1">Últimas partidas coletadas</h3>
          <p className="text-[11px] text-ink-4 mt-0.5">
            As {historico?.teto ?? 40} mais recentes que entraram em{' '}
            <span className="font-mono">match_statistics</span>. Toque na partida para ver as{' '}
            {historico?.familias ?? 16} estatísticas que o banco tem dela.
          </p>
        </div>

        {/* O jogo coletado vazio é o erro que nenhuma contagem pega: zero não é
          * nulo, então ele passa por "preenchido" em toda métrica de cobertura. */}
        {!!historico?.zeradas && (
          <div className="flex items-start gap-2.5 px-4 py-3 border-b border-line bg-red-500/5">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-ink-3 leading-relaxed">
              <span className="font-bold text-ink-1">
                {historico.zeradas} partida(s) com escanteios, chutes e faltas em zero.
              </span>{' '}
              Zero não é ausência: essas linhas entram nas médias como jogo real e puxam
              o baseline para baixo sem aparecer em nenhuma contagem de cobertura.
            </p>
          </div>
        )}

        {historico?.erro ? (
          <p className="px-4 py-6 text-[11px] text-red-400">{historico.erro}</p>
        ) : !historico ? (
          <SpinnerBlock className="py-10" />
        ) : historico.partidas.length === 0 ? (
          <EmptyState
            compact
            Icon={Database}
            title="Nenhuma partida coletada"
            description="Sem linha em match_statistics não há baseline de liga, média de time nem confronto direto."
          />
        ) : (
          <>
            <div className={`divide-y divide-line/60 ${trocandoPagina ? 'opacity-50' : ''} transition-opacity duration-1`}>
              {historico.partidas.map(p => {
                const gols = p.stats?.gols ?? [null, null]
                const incompleta = p.completas < historico.familias
                const escancarada = aberta === p.fixture_id
                return (
                  <div key={p.fixture_id} className={p.zerada ? 'bg-red-500/5' : ''}>
                    <button
                      type="button"
                      onClick={() => setAberta(escancarada ? null : p.fixture_id)}
                      aria-expanded={escancarada}
                      className="w-full text-left px-4 py-2.5 hover:bg-surface-2/60 transition-colors duration-1"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-[11px] text-ink-4 shrink-0 w-9 tabular-nums">
                          {diaMes(p.data)}
                        </span>
                        <span className="flex-1 min-w-0 text-sm text-ink-2 truncate">
                          {p.mandante ?? 'Time ?'}
                          <span className="font-mono font-bold text-ink-1 mx-1.5 tabular-nums">
                            {numero(gols[0])}x{numero(gols[1])}
                          </span>
                          {p.visitante ?? 'Time ?'}
                        </span>
                        {p.status && p.status !== 'FT' && (
                          <span className="font-mono text-[10px] text-yellow-400 shrink-0">{p.status}</span>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 pl-11 mt-0.5 text-[10px] text-ink-4">
                        <span className="truncate max-w-[40%]">{p.liga ?? 'liga ?'}</span>
                        <span className={`font-mono tabular-nums ${
                          incompleta ? 'text-yellow-400' : 'text-green-400'}`}>
                          {p.completas}/{historico.familias} estatísticas
                        </span>
                        {p.zerada && <span className="text-red-400 font-semibold">zerada</span>}
                      </div>
                    </button>

                    {escancarada && (
                      <div className="px-4 pb-3 pl-11">
                        <div className="rounded-lg border border-line/60 overflow-hidden">
                          <div className="grid grid-cols-[1fr_3rem_3rem] gap-x-2 px-3 py-1.5 border-b border-line/60 text-[10px] text-ink-4">
                            <span>Estatística</span>
                            <span className="text-right truncate">Casa</span>
                            <span className="text-right truncate">Fora</span>
                          </div>
                          {historico.resumo.map(f => {
                            const [casa, fora] = p.stats?.[f.chave] ?? [null, null]
                            const vazio = casa == null || fora == null
                            return (
                              <div
                                key={f.chave}
                                className="grid grid-cols-[1fr_3rem_3rem] gap-x-2 px-3 py-1 text-[11px] odd:bg-surface-2/40"
                              >
                                <span className={`truncate ${vazio ? 'text-yellow-400' : 'text-ink-3'}`}>
                                  {f.rotulo}
                                </span>
                                <span className={`font-mono text-right tabular-nums ${
                                  casa == null ? 'text-yellow-400' : 'text-ink-2'}`}>
                                  {numero(casa)}
                                </span>
                                <span className={`font-mono text-right tabular-nums ${
                                  fora == null ? 'text-yellow-400' : 'text-ink-2'}`}>
                                  {numero(fora)}
                                </span>
                              </div>
                            )
                          })}
                        </div>
                        <p className="text-[10px] text-ink-4 mt-1.5 leading-relaxed">
                          Árbitro: {p.referee || 'não informado'} · coletada em{' '}
                          {diaMes(p.coletada_em)} · fixture{' '}
                          <span className="font-mono">{p.fixture_id}</span>
                        </p>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            <Pagination
              page={pagina}
              pageSize={POR_PAGINA}
              total={historico.total}
              onChange={irPara}
              unit="partidas"
            />
          </>
        )}
      </div>
    </div>
  )
}
