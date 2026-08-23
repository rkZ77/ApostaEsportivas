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
  frescor: { ultima_partida?: string | null; ultimos_7_dias?: number | null }
  buracos: { total?: number | null; mais_antigo?: string | null }
  varredura: {
    habilitada?: boolean; intervalo_s?: number; janela_dias?: number
    rodando?: boolean; ultima_passada_ha_s?: number | null
    ultimo_resultado?: unknown; erro?: string
  }
}

interface Partida {
  fixture_id: number
  data: string | null
  status: string | null
  liga: string | null
  mandante: string | null
  visitante: string | null
  home_goals: number | null
  away_goals: number | null
  escanteios: number | null
  cartoes: number | null
  faltas: number | null
}

interface Historico {
  total: number
  teto: number
  partidas: Partida[]
  erro?: string
}

const POR_PAGINA = 10

const numero = (v: number | null | undefined) =>
  v == null ? '·' : v.toLocaleString('pt-BR')

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

  const buscarHistorico = useCallback((p: number) => {
    setTrocandoPagina(true)
    api.get('/admin/dados/partidas', { params: { pagina: p, por_pagina: POR_PAGINA } })
      .then(r => setHistorico(r.data))
      .catch(() => setHistorico({ total: 0, teto: 40, partidas: [], erro: 'Não deu pra ler as partidas.' }))
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
        <StatTile label="Última partida lida" value={diaMes(dados.frescor?.ultima_partida)} />
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

      {/* Partida a partida · o que o motor leu, e o que veio vazio na linha. */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <h3 className="text-sm font-bold text-ink-1">Últimas partidas coletadas</h3>
          <p className="text-[11px] text-ink-4 mt-0.5">
            As {historico?.teto ?? 40} mais recentes que entraram em{' '}
            <span className="font-mono">match_statistics</span>. Número faltando na linha é
            estatística que o provedor não devolveu para aquele jogo.
          </p>
        </div>

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
              {historico.partidas.map(p => (
                <div key={p.fixture_id} className="px-4 py-2.5">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-[11px] text-ink-4 shrink-0 w-9 tabular-nums">
                      {diaMes(p.data)}
                    </span>
                    <span className="flex-1 min-w-0 text-sm text-ink-2 truncate">
                      {p.mandante ?? 'Time ?'}
                      <span className="font-mono font-bold text-ink-1 mx-1.5 tabular-nums">
                        {numero(p.home_goals)}x{numero(p.away_goals)}
                      </span>
                      {p.visitante ?? 'Time ?'}
                    </span>
                    {p.status && p.status !== 'FT' && (
                      <span className="font-mono text-[10px] text-yellow-400 shrink-0">{p.status}</span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 pl-11 mt-0.5 text-[10px] text-ink-4">
                    <span className="truncate max-w-[45%]">{p.liga ?? 'liga ?'}</span>
                    <span className="font-mono tabular-nums">{numero(p.escanteios)} esc</span>
                    <span className="font-mono tabular-nums">{numero(p.cartoes)} cart</span>
                    <span className="font-mono tabular-nums">{numero(p.faltas)} faltas</span>
                  </div>
                </div>
              ))}
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
