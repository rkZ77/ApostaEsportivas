import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, Database, Pencil, PlayCircle, RefreshCw, Save,
  ShieldAlert, X,
} from 'lucide-react'
import api from '../services/api'
import { Button, EmptyState, Pagination, SpinnerBlock, StatTile } from './ui'

/*
 * O que o motor tem pra ler, onde estão os buracos, e o que dá pra fazer.
 *
 * A aba Pipeline responde "o sistema está de pé". Esta responde outra coisa:
 * "o motor está enxergando?". São perguntas diferentes, e a segunda não tinha
 * tela · jogo encerrado sem estatística não quebra nada, só deixa a média
 * velha, e média velha não parece defeito de coisa nenhuma.
 *
 * O número que manda aqui é o de partidas encerradas sem estatística. Ele é a
 * distância entre o que aconteceu no mundo e o que o motor sabe.
 *
 * Até 26/08 a tela parava nesse número. Alarme sem botão: a única saída era
 * esperar a varredura automática (que só olha 3 dias e só roda em produção) ou
 * rodar o pipeline inteiro por causa de uma partida. Agora cada buraco tem as
 * três saídas do backend, na mesma ordem de preferência:
 *
 *   Rodar            repergunta a folha pra API. Resolve o caso normal.
 *   Criar a linha    a API não tem folha e não vai ter. Grava placar e árbitro,
 *                    contadores em branco, pra dar onde escrever.
 *   Preencher à mão  digitar olhando a súmula. Fica marcado como manual.
 *
 * Digitar é o ÚLTIMO recurso, e a tela precisa mostrar isso: o número da mão
 * entra na mesma coluna que o coletado e o motor lê os dois igual.
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

/** O que foi digitado à mão, por quem e quando · vem de `manual_stats`. */
type Manual = Record<string, { casa: number | null; fora: number | null; por?: string; em?: string }>

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
  manual_stats?: Manual | null
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

/** Partida encerrada que nunca entrou em `match_statistics`. */
interface Buraco {
  fixture_id: number
  data: string | null
  status: string | null
  liga: string | null
  mandante: string | null
  visitante: string | null
}

/** Cobertura da tabela inteira numa janela de meses · não das últimas 40. */
interface Diagnostico {
  meses: number
  ft: number
  incompletas: number
  incompleta_mais_antiga?: string | null
  zeradas: number
  sem_linha: number
  colunas_da_folha?: string[]
  familias: { chave: string; rotulo: string; com_dado: number; sem_dado: number; desde: string | null }[]
  erro?: string
}

/** Estado do lote de recoleta · vive na memória do processo do site. */
interface Recoleta {
  rodando: boolean
  total: number
  feitas: number
  gravadas: number
  falhas: number
  medias: number
  iniciada_em?: string | null
  terminada_em?: string | null
  erro?: string | null
}

interface Vermelho {
  disponivel: boolean
  alvo?: number
  sem_vermelho?: number
  folha_incompleta?: number
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

const msgErro = (e: unknown, padrao: string) => {
  const r = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof r === 'string') return r
  // 422 do Pydantic chega como lista de erros; a mensagem útil é a do validador.
  if (Array.isArray(r) && r[0]?.msg) return String(r[0].msg).replace(/^Value error, /, '')
  return padrao
}

export default function AdminDados() {
  const [dados, setDados] = useState<Dados | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  const [historico, setHistorico] = useState<Historico | null>(null)
  const [pagina, setPagina] = useState(0)
  const [trocandoPagina, setTrocandoPagina] = useState(false)
  const [aberta, setAberta] = useState<number | null>(null)

  const [buracos, setBuracos] = useState<Buraco[] | null>(null)
  const [verBuracos, setVerBuracos] = useState(false)
  const [vermelho, setVermelho] = useState<Vermelho | null>(null)
  const [corrigindoVermelho, setCorrigindoVermelho] = useState(false)

  const [diagnostico, setDiagnostico] = useState<Diagnostico | null>(null)
  const [recoleta, setRecoleta] = useState<Recoleta | null>(null)
  const [lote, setLote] = useState(20)
  const [pedindoLote, setPedindoLote] = useState(false)

  /** fixture_id em coleta. Um por vez: cada clique custa 2 requisições da cota. */
  const [rodando, setRodando] = useState<number | null>(null)
  const [aviso, setAviso] = useState<{ fixture: number; texto: string; ok: boolean } | null>(null)

  /** Edição manual: fixture aberto, rascunho em texto, erro do servidor. */
  const [editando, setEditando] = useState<number | null>(null)
  const [rascunho, setRascunho] = useState<Record<string, [string, string]>>({})
  const [salvando, setSalvando] = useState(false)
  const [erroEdicao, setErroEdicao] = useState('')

  const buscarHistorico = useCallback((p: number) => {
    setTrocandoPagina(true)
    setAberta(null)
    setEditando(null)
    api.get('/admin/dados/partidas', { params: { pagina: p, por_pagina: POR_PAGINA } })
      .then(r => setHistorico(r.data))
      .catch(() => setHistorico({
        total: 0, teto: 40, familias: 0, resumo: [], zeradas: 0,
        partidas: [], erro: 'Não deu pra ler as partidas.',
      }))
      .finally(() => setTrocandoPagina(false))
  }, [])

  const buscarBuracos = useCallback(() => {
    api.get('/admin/dados/buracos')
      .then(r => setBuracos(r.data?.partidas ?? []))
      .catch(() => setBuracos([]))
    api.get('/admin/dados/vermelho-legado')
      .then(r => setVermelho(r.data))
      .catch(() => setVermelho(null))
  }, [])

  const buscarDiagnostico = useCallback((meses = 12) => {
    api.get('/admin/dados/diagnostico', { params: { meses } })
      .then(r => setDiagnostico(r.data))
      .catch(() => setDiagnostico(null))
  }, [])

  const buscarRecoleta = useCallback(() => {
    api.get('/admin/dados/recoleta-status')
      .then(r => setRecoleta(r.data))
      .catch(() => {})
  }, [])

  const buscar = () => {
    setCarregando(true)
    setErro('')
    api.get('/admin/dados')
      .then(r => setDados(r.data))
      .catch(e => setErro(msgErro(e, 'Não deu pra ler o estado do banco.')))
      .finally(() => setCarregando(false))
    // Volta pra primeira página: "Atualizar" com a página 3 na tela mostraria
    // a terceira dezena de uma lista que acabou de mudar embaixo.
    setPagina(0)
    buscarHistorico(0)
    buscarBuracos()
    buscarDiagnostico(diagnostico?.meses ?? 12)
    buscarRecoleta()
  }

  useEffect(buscar, [])

  /* Enquanto o lote roda, a tela pergunta o estado. O intervalo é de 3s e não
   * de 1s de propósito: o trabalho é de segundos POR PARTIDA (duas requisições
   * à API cada), então pesquisar mais rápido só gera request sem novidade. */
  useEffect(() => {
    if (!recoleta?.rodando) return
    const t = setInterval(() => {
      api.get('/admin/dados/recoleta-status')
        .then(r => {
          setRecoleta(r.data)
          // Acabou: o banco mudou embaixo, então tudo que a aba mostra
          // envelheceu junto.
          if (!r.data?.rodando) {
            api.get('/admin/dados').then(x => setDados(x.data)).catch(() => {})
            buscarHistorico(pagina)
            buscarBuracos()
            buscarDiagnostico(diagnostico?.meses ?? 12)
          }
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(t)
  }, [recoleta?.rodando, pagina, diagnostico?.meses, buscarHistorico, buscarBuracos, buscarDiagnostico])

  const dispararRecoleta = async () => {
    setPedindoLote(true)
    setAviso(null)
    try {
      const r = await api.post('/admin/dados/recoletar', null,
        { params: { limite: lote, meses: 3 } })
      setAviso({ fixture: -2, texto: r.data?.mensagem ?? 'Lote iniciado.', ok: true })
      buscarRecoleta()
    } catch (e) {
      setAviso({ fixture: -2, texto: msgErro(e, 'Não deu pra iniciar o lote.'), ok: false })
    } finally {
      setPedindoLote(false)
    }
  }

  const irPara = (p: number) => {
    setPagina(p)
    buscarHistorico(p)
  }

  /* Coleta de UMA partida. `criarSemFolha` é o segundo clique, o que aceita
   * gravar a linha sem contadores · só aparece depois de a API dizer que não
   * tem folha, nunca antes. */
  const rodar = async (fixtureId: number, criarSemFolha = false) => {
    setRodando(fixtureId)
    setAviso(null)
    try {
      const r = await api.post(`/admin/dados/partidas/${fixtureId}/coletar`, null,
        { params: criarSemFolha ? { criar_sem_folha: true } : {} })
      setAviso({ fixture: fixtureId, texto: r.data?.mensagem ?? 'Coleta concluída.', ok: !!r.data?.ok })
      if (r.data?.ok) {
        // Recarrega tudo: a partida sai da lista de buracos e entra na de
        // coletadas, e as médias das últimas 40 mudam junto.
        api.get('/admin/dados').then(x => setDados(x.data)).catch(() => {})
        buscarHistorico(pagina)
        buscarBuracos()
      }
    } catch (e) {
      setAviso({ fixture: fixtureId, texto: msgErro(e, 'A coleta falhou.'), ok: false })
    } finally {
      setRodando(null)
    }
  }

  const abrirEdicao = (p: Partida, familias: Familia[]) => {
    const inicial: Record<string, [string, string]> = {}
    for (const f of familias) {
      const [casa, fora] = p.stats?.[f.chave] ?? [null, null]
      inicial[f.chave] = [casa == null ? '' : String(casa), fora == null ? '' : String(fora)]
    }
    setRascunho(inicial)
    setErroEdicao('')
    setEditando(p.fixture_id)
  }

  const salvarManual = async (p: Partida, familias: Familia[]) => {
    // Só o que MUDOU vai pro servidor. Reenviar a folha inteira marcaria como
    // manual até o número que veio da API, e aí a marca não diria mais nada.
    const valores: Record<string, [number | null, number | null]> = {}
    for (const f of familias) {
      const draft = rascunho[f.chave]
      if (!draft) continue
      const [casaTxt, foraTxt] = draft
      const [casaOrig, foraOrig] = p.stats?.[f.chave] ?? [null, null]
      const casa = casaTxt.trim() === '' ? null : Number(casaTxt.replace(',', '.'))
      const fora = foraTxt.trim() === '' ? null : Number(foraTxt.replace(',', '.'))
      if (Number.isNaN(casa) || Number.isNaN(fora)) {
        setErroEdicao(`${f.rotulo}: só número.`)
        return
      }
      if (casa !== casaOrig || fora !== foraOrig) valores[f.chave] = [casa, fora]
    }
    if (Object.keys(valores).length === 0) {
      setEditando(null)
      return
    }

    setSalvando(true)
    setErroEdicao('')
    try {
      await api.put(`/admin/dados/partidas/${p.fixture_id}/estatisticas`, { valores })
      setEditando(null)
      setAviso({ fixture: p.fixture_id, texto: 'Estatística gravada à mão e médias refeitas.', ok: true })
      api.get('/admin/dados').then(x => setDados(x.data)).catch(() => {})
      buscarHistorico(pagina)
      buscarBuracos()
    } catch (e) {
      setErroEdicao(msgErro(e, 'Não deu pra gravar.'))
    } finally {
      setSalvando(false)
    }
  }

  const corrigirVermelho = async () => {
    setCorrigindoVermelho(true)
    try {
      const r = await api.post('/admin/dados/vermelho-legado')
      setVermelho(v => (v ? { ...v, alvo: 0 } : v))
      setAviso({
        fixture: -1, ok: true,
        texto: `${r.data?.corrigidas ?? 0} linha(s) corrigidas · ${r.data?.arbitros ?? 0} média(s) de árbitro refeitas.`,
      })
      buscarHistorico(pagina)
      buscarBuracos()
    } catch (e) {
      setAviso({ fixture: -1, texto: msgErro(e, 'Não deu pra corrigir.'), ok: false })
    } finally {
      setCorrigindoVermelho(false)
    }
  }

  if (carregando && !dados) return <SpinnerBlock className="py-20" />
  if (erro) return <p className="text-red-400 text-sm py-8">{erro}</p>
  if (!dados) return null

  const totalBuracos = dados.buracos?.total ?? 0
  const v = dados.varredura ?? {}
  const familias = historico?.resumo ?? []

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
      <div className={`card p-4 border ${totalBuracos > 0 ? 'border-yellow-500/40 bg-yellow-500/5' : 'border-line'}`}>
        <div className="flex items-start gap-3">
          {totalBuracos > 0
            ? <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
            : <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0 mt-0.5" />}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-ink-1">
              {totalBuracos > 0
                ? `${numero(totalBuracos)} partida(s) encerrada(s) sem estatística`
                : 'Toda partida encerrada tem estatística'}
            </p>
            <p className="text-[11px] text-ink-3 mt-1 leading-relaxed">
              {totalBuracos > 0 ? (
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

            {totalBuracos > 0 && !!buracos?.length && (
              <button
                type="button"
                onClick={() => setVerBuracos(x => !x)}
                className="mt-2 text-[11px] font-semibold text-ink-2 underline underline-offset-4 hover:text-ink-1"
              >
                {verBuracos ? 'esconder as partidas' : `ver as ${buracos.length} mais recentes`}
              </button>
            )}
          </div>
        </div>

        {/* Cada buraco com nome e botão. O número sozinho não dá pra agir:
          * pra ir atrás de uma dessas partidas era preciso abrir o banco. */}
        {verBuracos && !!buracos?.length && (
          <div className="mt-3 border-t border-line/60 divide-y divide-line/60">
            {buracos.map(b => (
              <div key={b.fixture_id} className="py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[13px] text-ink-2 truncate">
                      <span className="font-mono text-[11px] text-ink-4 mr-1.5">{diaMes(b.data)}</span>
                      {b.mandante ?? 'Time ?'} x {b.visitante ?? 'Time ?'}
                    </p>
                    <p className="text-[10px] text-ink-4 mt-0.5 truncate">
                      {b.liga ?? 'liga ?'} · {b.status} · fixture{' '}
                      <span className="font-mono">{b.fixture_id}</span>
                    </p>
                  </div>
                  <Button
                    size="sm" variant="ghost" className="shrink-0"
                    loading={rodando === b.fixture_id}
                    disabled={rodando != null}
                    onClick={() => rodar(b.fixture_id)}
                  >
                    Rodar
                  </Button>
                </div>

                {aviso?.fixture === b.fixture_id && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <p className={`text-[11px] ${aviso.ok ? 'text-green-400' : 'text-yellow-400'}`}>
                      {aviso.texto}
                    </p>
                    {/* Segunda saída. Só aparece depois de a API dizer que não
                      * tem folha: linha oca criada sozinha esconderia a partida
                      * da varredura pra sempre. */}
                    {!aviso.ok && (
                      <button
                        type="button"
                        onClick={() => rodar(b.fixture_id, true)}
                        disabled={rodando != null}
                        className="text-[11px] font-semibold text-ink-2 underline underline-offset-4 hover:text-ink-1 disabled:opacity-50"
                      >
                        criar a linha assim mesmo, pra preencher à mão
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Cartão vermelho apagado pelo coletor antigo.
        *
        * A API-Football publica zero explícito em todo contador da folha, menos
        * em "Red Cards": esse ela manda vazio no caso normal, quando ninguém foi
        * expulso. Entre 25/07 e 26/08 o coletor leu esse vazio como ausência e
        * gravou NULL · e jogo sem os dois contadores de cartão cai fora do pool
        * do motor, o que custou 87% da amostra.
        *
        * O coletor já foi corrigido, mas coletor corrigido não mexe no passado:
        * a coleta só volta em folha incompleta, e a janela é de dias. */}
      {vermelho?.disponivel && (vermelho.alvo ?? 0) > 0 && (
        <div className="card p-4 border border-orange-500/40 bg-orange-500/5">
          <div className="flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-orange-400 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-ink-1">
                {numero(vermelho.alvo)} partida(s) com o cartão vermelho apagado
              </p>
              <p className="text-[11px] text-ink-3 mt-1 leading-relaxed">
                A folha está completa no resto e o buraco é só no vermelho · essa combinação
                só sai do coletor antigo lendo uma folha publicada, ou seja, a API respondeu
                e disse que não houve expulsão. Jogo sem os dois contadores de cartão cai
                fora do pool do motor, e a média de vermelho do árbitro sai tirada só dos
                jogos com expulsão.
                {!!vermelho.folha_incompleta && (
                  <> Outras {numero(vermelho.folha_incompleta)} partida(s) estão de fato sem
                  folha e continuam em branco · essas voltam pela coleta.</>
                )}
              </p>
              <Button
                size="sm" variant="ghost" className="mt-3"
                loading={corrigindoVermelho}
                onClick={corrigirVermelho}
              >
                Gravar zero nessas {numero(vermelho.alvo)} e refazer a média dos árbitros
              </Button>
              {aviso?.fixture === -1 && (
                <p className={`text-[11px] mt-2 ${aviso.ok ? 'text-green-400' : 'text-red-400'}`}>
                  {aviso.texto}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

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
            <p className="text-[11px] text-ink-4 leading-relaxed mt-1.5">
              O botão Rodar de cada partida não passa por esse freio: ele custa duas
              requisições e só dispara por clique.
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

      {/* Diagnóstico do histórico · a varredura que o resumo das 40 não faz.
        *
        * O bloco do vermelho conserta um defeito conhecido, e ele é a exceção
        * da casa: vermelho é o único contador em que vazio numa folha publicada
        * significa zero, então é o único que dá pra corrigir sem perguntar nada
        * pra API. Em qualquer outra família, inventar o número seria fabricar
        * estatística. Pras outras só existem dois caminhos honestos, e os dois
        * estão aqui: pedir de novo pra API, ou digitar olhando a súmula. */}
      {diagnostico && !diagnostico.erro && (
        <div className="card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-ink-1">Diagnóstico do histórico</h3>
              <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
                A tabela inteira dos últimos {diagnostico.meses} meses, não as últimas 40.
                Folha completa aqui é{' '}
                <span className="font-mono">{diagnostico.colunas_da_folha?.length ?? 5}</span>{' '}
                contadores presentes · não as 16 famílias: defesa de goleiro aparece em menos
                de 1% das folhas, e exigir as 16 mandaria recoletar tudo pra receber o mesmo vazio.
              </p>
            </div>
            <select
              value={diagnostico.meses}
              onChange={e => buscarDiagnostico(Number(e.target.value))}
              className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] shrink-0 focus:border-ink-4 focus:outline-none"
              aria-label="Janela do diagnóstico"
            >
              {[3, 6, 12, 24].map(m => <option key={m} value={m}>{m} meses</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <StatTile label="Encerradas na janela" value={numero(diagnostico.ft)} />
            <StatTile label="Folha incompleta" value={numero(diagnostico.incompletas)}
              tone={diagnostico.incompletas > 0 ? 'red' : 'default'}
              hint={diagnostico.incompleta_mais_antiga
                ? `mais antiga em ${diaMes(diagnostico.incompleta_mais_antiga)}`
                : undefined} />
            <StatTile label="Sem linha nenhuma" value={numero(diagnostico.sem_linha)}
              tone={diagnostico.sem_linha > 0 ? 'red' : 'default'} />
            <StatTile label="Coletadas zeradas" value={numero(diagnostico.zeradas)}
              tone={diagnostico.zeradas > 0 ? 'red' : 'default'} />
          </div>

          {/* Família por família, com a data do buraco mais antigo. É o que
            * separa "defeito que voltou agora" de "cicatriz de julho": os dois
            * aparecem como cobertura baixa, e só um pede ação. */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
            {diagnostico.familias.map(f => (
              <div key={f.chave}
                   className={`rounded-lg border p-2.5 ${
                     f.sem_dado > 0 ? 'border-yellow-500/40 bg-yellow-500/5' : 'border-line'}`}>
                <p className="text-[10px] text-ink-4 leading-tight truncate" title={f.rotulo}>
                  {f.rotulo}
                </p>
                <p className={`font-mono text-base font-black tabular-nums leading-tight mt-0.5 ${
                  f.sem_dado > 0 ? 'text-yellow-400' : 'text-ink-1'}`}>
                  {numero(f.sem_dado)}
                </p>
                <p className="text-[10px] font-mono tabular-nums text-ink-4">
                  {f.sem_dado > 0 ? `sem dado · desde ${diaMes(f.desde)}` : 'sem buraco'}
                </p>
              </div>
            ))}
          </div>

          {/* Recoleta em lote · o botão Rodar aplicado à lista inteira. */}
          <div className="border-t border-line/60 mt-4 pt-3">
            {recoleta?.rodando ? (
              <>
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[11px] font-semibold text-ink-2">
                    Recoletando {recoleta.feitas} de {recoleta.total}
                  </p>
                  <p className="text-[10px] font-mono text-ink-4">
                    {recoleta.gravadas} gravada(s) · {recoleta.falhas} falha(s)
                  </p>
                </div>
                <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden mt-2">
                  <div
                    className="h-full bg-green-500 transition-all duration-1"
                    style={{ width: `${Math.round((recoleta.feitas / Math.max(1, recoleta.total)) * 100)}%` }}
                  />
                </div>
                <p className="text-[10px] text-ink-4 mt-1.5">
                  Duas requisições por partida. Dá pra sair da aba · o lote continua no servidor.
                </p>
              </>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={lote}
                    onChange={e => setLote(Number(e.target.value))}
                    className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
                    aria-label="Quantas partidas recoletar"
                  >
                    {[10, 20, 50, 100].map(n => (
                      <option key={n} value={n}>{n} partidas · {n * 2} requisições</option>
                    ))}
                  </select>
                  <Button size="sm" variant="ghost" loading={pedindoLote}
                          onClick={dispararRecoleta}>
                    <PlayCircle className="w-3.5 h-3.5" />
                    Recoletar as mais recentes
                  </Button>
                </div>
                <p className="text-[10px] text-ink-4 mt-2 leading-relaxed">
                  Pega as partidas mais recentes com folha furada ou sem linha nenhuma, nos
                  últimos 3 meses. Mais recente primeiro de propósito: a API publica folha de
                  jogo velho cada vez menos, então gastar o lote em agosto rende mais que
                  gastá-lo em março. Só o cartão vermelho se conserta sem cota · o resto é
                  API ou digitação.
                </p>
                {recoleta?.terminada_em && (
                  <p className="text-[11px] text-green-400 mt-1.5">
                    Último lote: {recoleta.gravadas} de {recoleta.total} gravada(s)
                    {recoleta.falhas > 0 && ` · ${recoleta.falhas} falha(s)`}
                    {recoleta.medias > 0 && ` · ${recoleta.medias} média(s) de time refeitas`}
                  </p>
                )}
                {recoleta?.erro && (
                  <p className="text-[11px] text-red-400 mt-1.5">{recoleta.erro}</p>
                )}
                {aviso?.fixture === -2 && (
                  <p className={`text-[11px] mt-1.5 ${aviso.ok ? 'text-green-400' : 'text-red-400'}`}>
                    {aviso.texto}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Cobertura e média andam juntas de propósito.
        *
        * Cobertura sozinha não vê o jogo coletado zerado (zero não é nulo).
        * Média sozinha não diz se saiu de 40 partidas ou de 2. Lado a lado,
        * número torto e amostra curta ficam visíveis na mesma olhada. */}
      {historico && !historico.erro && familias.length > 0 && (
        <div className="card p-4">
          <h3 className="text-sm font-bold text-ink-1">
            Médias das últimas {historico.total} partidas
          </h3>
          <p className="text-[11px] text-ink-4 mt-0.5 mb-3">
            Média por partida de cada estatística que o banco guarda, e em quantos desses
            jogos ela veio preenchida. Amarelo é estatística que faltou em algum jogo.
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {familias.map(f => {
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
            {historico?.familias ?? 16} estatísticas que o banco tem dela, coletar de novo ou
            preencher o que faltou.
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
                const emEdicao = editando === p.fixture_id
                const manual = p.manual_stats ?? {}
                const temManual = Object.keys(manual).length > 0
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
                        {temManual && <span className="text-ink-3">tem número à mão</span>}
                      </div>
                    </button>

                    {escancarada && (
                      <div className="px-4 pb-3 sm:pl-11">
                        <div className="rounded-lg border border-line/60 overflow-hidden">
                          <div className={`grid ${emEdicao ? 'grid-cols-[1fr_4.5rem_4.5rem]' : 'grid-cols-[1fr_3rem_3rem]'} gap-x-2 px-3 py-1.5 border-b border-line/60 text-[10px] text-ink-4`}>
                            <span>Estatística</span>
                            <span className="text-right truncate">Casa</span>
                            <span className="text-right truncate">Fora</span>
                          </div>
                          {familias.map(f => {
                            const [casa, fora] = p.stats?.[f.chave] ?? [null, null]
                            const vazio = casa == null || fora == null
                            const daMao = !!manual[f.chave]
                            if (emEdicao) {
                              const [casaTxt, foraTxt] = rascunho[f.chave] ?? ['', '']
                              const trocar = (lado: 0 | 1, valor: string) =>
                                setRascunho(r => {
                                  const par: [string, string] = [...(r[f.chave] ?? ['', ''])] as [string, string]
                                  par[lado] = valor
                                  return { ...r, [f.chave]: par }
                                })
                              return (
                                <div
                                  key={f.chave}
                                  className="grid grid-cols-[1fr_4.5rem_4.5rem] gap-x-2 items-center px-3 py-1 text-[11px] odd:bg-surface-2/40"
                                >
                                  <span className={`truncate ${vazio ? 'text-yellow-400' : 'text-ink-3'}`}>
                                    {f.rotulo}
                                  </span>
                                  {([0, 1] as const).map(lado => (
                                    <input
                                      key={lado}
                                      type="number"
                                      inputMode="decimal"
                                      min={0}
                                      value={lado === 0 ? casaTxt : foraTxt}
                                      onChange={e => trocar(lado, e.target.value)}
                                      aria-label={`${f.rotulo} · ${lado === 0 ? 'casa' : 'fora'}`}
                                      className="w-full min-h-[32px] bg-surface-0 border border-line-strong rounded px-1.5 py-1 font-mono text-[11px] text-right tabular-nums text-ink-1 focus:border-ink-4 focus:outline-none"
                                    />
                                  ))}
                                </div>
                              )
                            }
                            return (
                              <div
                                key={f.chave}
                                className="grid grid-cols-[1fr_3rem_3rem] gap-x-2 px-3 py-1 text-[11px] odd:bg-surface-2/40"
                              >
                                <span className={`truncate ${vazio ? 'text-yellow-400' : 'text-ink-3'}`}
                                      title={daMao ? `à mão por ${manual[f.chave].por ?? 'admin'}` : undefined}>
                                  {f.rotulo}
                                  {daMao && <span className="text-ink-4 font-mono ml-1">à mão</span>}
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

                        {/* As duas saídas, na ordem: pedir de novo pra API antes
                          * de digitar. Número da mão é o último recurso. */}
                        <div className="flex flex-wrap items-center gap-2 mt-2">
                          {emEdicao ? (
                            <>
                              <Button size="sm" variant="primary" loading={salvando}
                                      onClick={() => salvarManual(p, familias)}>
                                <Save className="w-3.5 h-3.5" />
                                Salvar
                              </Button>
                              <Button size="sm" variant="ghost" disabled={salvando}
                                      onClick={() => setEditando(null)}>
                                <X className="w-3.5 h-3.5" />
                                Cancelar
                              </Button>
                            </>
                          ) : (
                            <>
                              <Button size="sm" variant="ghost"
                                      loading={rodando === p.fixture_id}
                                      disabled={rodando != null}
                                      onClick={() => rodar(p.fixture_id)}>
                                <RefreshCw className="w-3.5 h-3.5" />
                                Rodar
                              </Button>
                              <Button size="sm" variant="ghost"
                                      onClick={() => abrirEdicao(p, familias)}>
                                <Pencil className="w-3.5 h-3.5" />
                                Preencher à mão
                              </Button>
                            </>
                          )}
                        </div>

                        {erroEdicao && emEdicao && (
                          <p className="text-[11px] text-red-400 mt-1.5">{erroEdicao}</p>
                        )}
                        {aviso?.fixture === p.fixture_id && !emEdicao && (
                          <p className={`text-[11px] mt-1.5 ${aviso.ok ? 'text-green-400' : 'text-yellow-400'}`}>
                            {aviso.texto}
                          </p>
                        )}

                        <p className="text-[10px] text-ink-4 mt-1.5 leading-relaxed">
                          {emEdicao ? (
                            <>Campo em branco apaga o número de volta para ausência · é assim que se
                            desfaz um valor digitado errado sem inventar zero no lugar. Salvar refaz
                            o total da família e a média dos dois times na temporada.</>
                          ) : (
                            <>Árbitro: {p.referee || 'não informado'} · coletada em{' '}
                            {diaMes(p.coletada_em)} · fixture{' '}
                            <span className="font-mono">{p.fixture_id}</span></>
                          )}
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
