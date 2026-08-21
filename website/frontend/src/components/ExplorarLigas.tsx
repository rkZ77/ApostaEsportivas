import { useEffect, useMemo, useState } from 'react'
import {
  Globe, Home, Plane, Search, Database, Radio, Info, X, ChevronRight, Lock,
} from 'lucide-react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { SpinnerBlock, EmptyState, ErrorState, Modal, PillGroup, StatTile, Badge } from './ui'

/*
 * Explorar: liga e temporada que NÃO estão no banco.
 *
 * A aba Estatísticas responde pela liga que a IA cobre, lendo o mesmo
 * `match_statistics` que alimenta o motor. Esta responde pelo resto do mundo ·
 * Serie A de 2014, liga da Turquia, qualquer coisa que a API-Football tenha ·
 * lendo a API na hora e jogando fora depois. Nada aqui vira linha de banco.
 *
 * O QUE ESTA TELA NÃO MOSTRA, e por quê: escanteio, falta, finalização e posse.
 * A API só entrega esses quatro em `/fixtures/statistics`, que custa uma
 * requisição POR JOGO · uma temporada inteira sairia por 380. O que dá pra ler
 * de uma vez é placar, e é de placar que sai tudo que está aqui.
 */

type Recorte = 'todos' | 'casa' | 'fora'

interface LigaItem {
  league_id: number
  nome: string
  pais: string | null
  tipo: string | null
  temporada_atual: number | null
  no_banco: boolean
  ativa: boolean | null
}

interface Temporada {
  ano: number
  inicio: string | null
  fim: string | null
  atual: boolean
  tem_estatistica_por_jogo: boolean
}

interface Corte {
  jogos: number
  v: number; e: number; d: number
  gols_pro: number; gols_contra: number
  media_gols_pro: number; media_gols_contra: number; media_gols_total: number
  saldo: number
  aproveitamento_pct: number
  clean_sheet_pct: number; sem_marcar_pct: number
  btts_pct: number
  over15_pct: number; over25_pct: number; over35_pct: number
  forma: string
}

interface TimeLinha {
  team_id: number; nome: string; logo: string | null
  todos: Corte; casa: Corte; fora: Corte
}

interface Resumo {
  jogos_total: number; jogos_finalizados: number
  media_gols: number; media_gols_casa: number; media_gols_fora: number
  btts_pct: number; over25_pct: number
  vitoria_casa_pct: number; empate_pct: number; vitoria_fora_pct: number
}

interface DetalheTemporada {
  liga: { league_id: number; nome: string | null; pais: string | null; logo: string | null }
  temporada: number
  resumo: Resumo
  times: TimeLinha[]
}

interface DetalheTime {
  team_id: number; nome: string | null; logo: string | null
  forma: string | null
  jogos: { todos: number; casa: number; fora: number }
  cartoes: {
    amarelo: { total: number; por_jogo: number; faixas: { faixa: string; total: number }[] }
    vermelho: { total: number; por_jogo: number; faixas: { faixa: string; total: number }[] }
  }
}

/*
 * As métricas ordenáveis, e o que cada uma significa no recorte escolhido.
 *
 * `melhorAlto` não é enfeite: aproveitamento alto é bom, gol sofrido alto é
 * ruim, e a mesma cor verde nos dois casos ensinaria a ler errado.
 */
const METRICAS = [
  { key: 'aproveitamento_pct', label: 'Aproveitamento', sufixo: '%',  casas: 1, melhorAlto: true },
  { key: 'media_gols_pro',     label: 'Gols marcados',  sufixo: '',   casas: 2, melhorAlto: true },
  { key: 'media_gols_contra',  label: 'Gols sofridos',  sufixo: '',   casas: 2, melhorAlto: false },
  { key: 'media_gols_total',   label: 'Gols no jogo',   sufixo: '',   casas: 2, melhorAlto: true },
  { key: 'over25_pct',         label: 'Over 2.5',       sufixo: '%',  casas: 1, melhorAlto: true },
  { key: 'btts_pct',           label: 'Ambos marcam',   sufixo: '%',  casas: 1, melhorAlto: true },
  { key: 'clean_sheet_pct',    label: 'Sem sofrer gol', sufixo: '%',  casas: 1, melhorAlto: true },
] as const

type MetricaKey = typeof METRICAS[number]['key']

const RECORTES: { value: Recorte; label: React.ReactNode }[] = [
  { value: 'todos', label: <span className="flex items-center gap-1.5"><Globe className="w-3.5 h-3.5" />Todos</span> },
  { value: 'casa',  label: <span className="flex items-center gap-1.5"><Home  className="w-3.5 h-3.5" />Casa</span>  },
  { value: 'fora',  label: <span className="flex items-center gap-1.5"><Plane className="w-3.5 h-3.5" />Fora</span>  },
]

const LOGO_LIGA = (id: number) => `/api/proxy/league/${id}.png`
const LOGO_TIME = (id: number) => `/api/proxy/team/${id}.png`

/** V verde, E cinza, D vermelho. Vazio quando o time ainda não jogou no recorte. */
function Forma({ forma }: { forma: string }) {
  if (!forma) return <span className="text-ink-4 text-[10px]">sem jogo</span>
  return (
    <span className="flex gap-0.5">
      {forma.split('').map((r, i) => (
        <span key={i}
          className={`w-4 h-4 rounded-sm font-mono text-[9px] font-black flex items-center justify-center ${
            r === 'V' ? 'bg-green-500/20 text-green-400'
            : r === 'E' ? 'bg-surface-3 text-ink-3'
            : 'bg-red-500/20 text-red-400'}`}>
          {r}
        </span>
      ))}
    </span>
  )
}

function fmt(valor: number, casas: number, sufixo: string) {
  return `${valor.toFixed(casas)}${sufixo}`
}

export default function ExplorarLigas() {
  const { user } = useAuth()
  /*
   * Mesma régua da aba Estatísticas.
   *
   * Não é só coerência de produto: cada liga aberta aqui gasta cota da fonte de
   * dados, e liberar pra qualquer cadastro transformaria a tela numa torneira
   * que qualquer pessoa abre. O bloqueio de verdade está no servidor
   * (`require_vip` em explorer.py); isto aqui é só não mostrar uma tela que
   * responderia 403 em toda requisição.
   */
  const isVip = user?.plan === 'vip' || user?.plan === 'admin' || user?.plan === 'trial'

  const [busca, setBusca]           = useState('')
  const [ligas, setLigas]           = useState<LigaItem[]>([])
  const [buscando, setBuscando]     = useState(false)
  const [liga, setLiga]             = useState<LigaItem | null>(null)

  const [temporadas, setTemporadas] = useState<Temporada[]>([])
  const [pais, setPais]             = useState<string | null>(null)
  const [temporada, setTemporada]   = useState<number | null>(null)

  const [dados, setDados]           = useState<DetalheTemporada | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro]             = useState<string | null>(null)

  const [recorte, setRecorte]       = useState<Recorte>('todos')
  const [metrica, setMetrica]       = useState<MetricaKey>('aproveitamento_pct')

  const [timeAberto, setTimeAberto]     = useState<TimeLinha | null>(null)
  const [detalheTime, setDetalheTime]   = useState<DetalheTime | null>(null)
  const [carregandoTime, setCarregandoTime] = useState(false)

  /*
   * Busca com atraso de 400ms.
   *
   * Cada tecla dispara uma consulta ao catálogo da API, e "brasileirao" digitado
   * inteiro são onze requisições pra uma resposta só interessar. Abaixo de três
   * letras a rota nem chega na API: devolve as ligas do banco, de graça.
   */
  useEffect(() => {
    if (!isVip) return
    const termo = busca.trim()
    setBuscando(true)
    const timer = setTimeout(() => {
      api.get('/explorer/ligas', { params: termo.length >= 3 ? { busca: termo } : {} })
        .then(r => setLigas(r.data ?? []))
        .catch(() => setLigas([]))
        .finally(() => setBuscando(false))
    }, termo.length >= 3 ? 400 : 0)
    return () => clearTimeout(timer)
  }, [busca, isVip])

  // Abre já com uma liga dentro. Painel vazio na primeira visita obriga a
  // pessoa a adivinhar o que a tela faz antes de ver qualquer número.
  useEffect(() => {
    if (!isVip || liga || ligas.length === 0 || busca.trim().length >= 3) return
    setLiga(ligas.find(l => l.ativa !== false) ?? ligas[0])
  }, [ligas, liga, busca, isVip])

  useEffect(() => {
    if (!isVip || !liga) return
    setTemporadas([]); setTemporada(null); setDados(null); setErro(null); setPais(null)
    api.get(`/explorer/ligas/${liga.league_id}/temporadas`)
      .then(r => {
        const ts: Temporada[] = r.data?.temporadas ?? []
        setTemporadas(ts)
        // O pais so vem da API. A lista do banco nao tem essa coluna, entao
        // liga cadastrada aparecia sem pais ate' esta chamada responder.
        setPais(r.data?.pais ?? null)
        setTemporada((ts.find(t => t.atual) ?? ts[0])?.ano ?? null)
      })
      .catch(() => setErro('Não deu pra listar as temporadas dessa liga.'))
  }, [liga, isVip])

  useEffect(() => {
    if (!isVip || !liga || !temporada) return
    setCarregando(true); setErro(null)
    api.get(`/explorer/ligas/${liga.league_id}/temporadas/${temporada}`)
      .then(r => setDados(r.data))
      .catch(e => {
        setDados(null)
        setErro(e?.response?.data?.detail ?? 'Não deu pra carregar essa temporada.')
      })
      .finally(() => setCarregando(false))
  }, [liga, temporada, isVip])

  useEffect(() => {
    if (!isVip || !timeAberto || !liga || !temporada) return
    setCarregandoTime(true); setDetalheTime(null)
    api.get(`/explorer/times/${timeAberto.team_id}`, {
      params: { league_id: liga.league_id, season: temporada },
    })
      .then(r => setDetalheTime(r.data))
      .catch(() => setDetalheTime(null))
      .finally(() => setCarregandoTime(false))
  }, [timeAberto, liga, temporada, isVip])

  const def = METRICAS.find(m => m.key === metrica)!

  /*
   * Corte de amostra, RELATIVO à mediana de jogos do recorte.
   *
   * Todas as métricas desta tela são média ou percentual, e média de dois jogos
   * ganha de média de trinta e oito por acidente: um time promovido com uma
   * vitória e um empate aparecia em primeiro no aproveitamento, na frente de
   * quem sustentou o número a temporada inteira.
   *
   * O corte não pode ser um número fixo, porque na terceira rodada TODO mundo
   * tem três jogos e a tabela inteira viraria "amostra curta". Metade da
   * mediana se ajusta sozinho: no começo da temporada não exclui ninguém, e com
   * a liga andada separa quem entrou no meio do caminho.
   */
  const minimoJogos = useMemo(() => {
    if (!dados) return 0
    const contagens = dados.times.map(t => t[recorte].jogos).filter(n => n > 0).sort((a, b) => a - b)
    if (contagens.length === 0) return 0
    const mediana = contagens[Math.floor(contagens.length / 2)]
    return mediana / 2
  }, [dados, recorte])

  const ordenados = useMemo(() => {
    if (!dados) return []
    // Três faixas: amostra boa, amostra curta, e quem não jogou. A ordem entre
    // as faixas é fixa; dentro de cada uma vale a métrica escolhida.
    const faixa = (t: TimeLinha) => {
      const n = t[recorte].jogos
      if (n === 0) return 2
      return n < minimoJogos ? 1 : 0
    }
    return [...dados.times].sort((a, b) => {
      const df = faixa(a) - faixa(b)
      if (df !== 0) return df
      const va = a[recorte][metrica], vb = b[recorte][metrica]
      return def.melhorAlto ? vb - va : va - vb
    })
  }, [dados, recorte, metrica, def.melhorAlto, minimoJogos])

  const mostrandoBusca = busca.trim().length >= 3

  // Gate depois dos hooks: React exige a mesma ordem de hooks em toda
  // renderizacao, entao o `return` antecipado so pode vir aqui embaixo.
  if (!isVip) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <div className="w-14 h-14 rounded-full bg-surface-1 flex items-center justify-center">
          <Lock className="w-6 h-6 text-ink-3" />
        </div>
        <h2 className="text-ink-1 font-bold text-lg">Recurso VIP</h2>
        <p className="text-ink-3 text-sm text-center max-w-xs">
          Explorar liga e temporada fora das que a IA cobre e exclusivo para membros VIP.
        </p>
        <a href="/planos" className="btn-primary px-6 py-2 text-sm">Ver planos</a>
      </div>
    )
  }

  return (
    <div className="space-y-5">

      {/* Aviso do que esta aba é. Sem ele, a ausência de escanteios lê como
          defeito em vez de limite da fonte. */}
      <div className="flex items-start gap-3 bg-surface-1 border border-line rounded-lg px-4 py-3">
        <Info className="w-4 h-4 text-ink-3 mt-0.5 shrink-0" />
        <p className="text-ink-2 text-xs leading-relaxed">
          Consulta direto na fonte de dados, <span className="text-ink-1 font-semibold">sem passar pelo banco</span>:
          dá pra abrir qualquer liga e qualquer temporada, inclusive as que a IA não cobre.
          Aqui só entram números tirados do placar · gols, aproveitamento, forma e cartões.
          Escanteios e faltas continuam na aba <span className="text-ink-1 font-semibold">Estatísticas</span>,
          que lê o histórico coletado.
        </p>
      </div>

      {/* Seletor de liga */}
      <div className="space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-4 pointer-events-none" />
          <input
            type="search"
            value={busca}
            onChange={ev => setBusca(ev.target.value)}
            placeholder="Buscar liga (3 letras ou mais)"
            aria-label="Buscar liga"
            className="input pl-9 py-2.5 text-sm"
          />
        </div>

        {(mostrandoBusca || !liga) && (
          <div className="card p-0 overflow-hidden max-h-72 overflow-y-auto">
            {buscando ? (
              <SpinnerBlock className="py-8" />
            ) : ligas.length === 0 ? (
              <p className="p-6 text-center text-ink-4 text-sm">Nenhuma liga com esse nome.</p>
            ) : (
              <div className="divide-y divide-line/60">
                {ligas.map(l => (
                  <button key={l.league_id}
                    onClick={() => { setLiga(l); setBusca('') }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/60 transition-colors">
                    <img src={LOGO_LIGA(l.league_id)} alt="" width={20} height={20}
                      className="w-5 h-5 object-contain shrink-0"
                      onError={ev => (ev.currentTarget.style.display = 'none')} />
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm text-ink-1 font-semibold truncate">{l.nome}</span>
                      {l.pais && <span className="block text-[11px] text-ink-4">{l.pais}</span>}
                    </span>
                    {l.no_banco && (
                      <Badge tone="green" className="shrink-0">
                        <Database className="w-3 h-3" />
                        Coberta
                      </Badge>
                    )}
                    <ChevronRight className="w-4 h-4 text-ink-4 shrink-0" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {liga && (
        <>
          {/* Liga escolhida + temporada */}
          <div className="flex items-center gap-3 flex-wrap">
            <img src={LOGO_LIGA(liga.league_id)} alt="" width={32} height={32}
              className="w-8 h-8 object-contain shrink-0"
              onError={ev => (ev.currentTarget.style.display = 'none')} />
            <div className="min-w-0">
              <h2 className="text-ink-1 font-bold text-base truncate">{liga.nome}</h2>
              <p className="text-ink-3 text-xs">
                {/* Sem pais conhecido, nao escreve nada. O rotulo generico que
                    estava aqui ("Internacional") era pior que o vazio: e' o
                    nome de um time brasileiro, e aparecia em cima de uma lista
                    onde esse time e' uma das linhas. */}
                {[dados?.liga?.pais ?? pais ?? liga.pais,
                  dados && `${dados.resumo.jogos_finalizados} de ${dados.resumo.jogos_total} jogos disputados`]
                  .filter(Boolean).join(' · ')}
              </p>
            </div>
            {temporadas.length > 0 && (
              <select
                value={temporada ?? ''}
                onChange={ev => setTemporada(Number(ev.target.value))}
                aria-label="Temporada"
                className="input py-2 text-sm ml-auto w-auto min-w-[9rem]">
                {temporadas.map(t => (
                  <option key={t.ano} value={t.ano}>
                    {t.ano}{t.atual ? ' (atual)' : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {erro ? (
            <ErrorState
              title="Não deu pra carregar"
              description={erro}
              onRetry={() => setTemporada(t => t)}
            />
          ) : carregando ? (
            <SpinnerBlock className="py-20" />
          ) : !dados || dados.resumo.jogos_finalizados === 0 ? (
            <EmptyState
              Icon={Radio}
              title="Nenhum jogo disputado ainda"
              description="Essa temporada existe na fonte, mas ainda não tem partida finalizada pra somar."
            />
          ) : (
            <>
              {/* Resumo da temporada */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <StatTile label="Gols por jogo"   value={dados.resumo.media_gols.toFixed(2)} tone="green" />
                <StatTile label="Ambos marcam"    value={`${dados.resumo.btts_pct}%`} />
                <StatTile label="Over 2.5"        value={`${dados.resumo.over25_pct}%`} />
                <StatTile
                  label="Mando de campo"
                  value={`${dados.resumo.vitoria_casa_pct}%`}
                  hint={`empate ${dados.resumo.empate_pct}% · fora ${dados.resumo.vitoria_fora_pct}%`}
                />
              </div>

              {/* Recorte e ordenação */}
              <div className="space-y-3">
                <PillGroup options={RECORTES} value={recorte} onChange={setRecorte} />
                <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
                  {METRICAS.map(m => (
                    <button key={m.key} onClick={() => setMetrica(m.key)}
                      className={`shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                        metrica === m.key
                          ? 'bg-green-500/15 border border-green-500/40 text-green-400'
                          : 'bg-surface-2 border border-transparent text-ink-3 hover:text-ink-2'
                      }`}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Tabela por time */}
              <div className="card overflow-hidden p-0">
                <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
                  <h3 className="text-sm font-bold text-ink-1">
                    {def.label}
                    <span className="text-ink-4 font-normal">
                      {' · '}
                      {recorte === 'todos' ? 'todos os jogos' : recorte === 'casa' ? 'só em casa' : 'só fora'}
                    </span>
                  </h3>
                  <span className="text-[11px] text-ink-4 font-semibold shrink-0">{ordenados.length} times</span>
                </div>

                <div className="divide-y divide-line/60">
                  {ordenados.map((t, i) => {
                    const c = t[recorte]
                    const semJogo = c.jogos === 0
                    const amostraCurta = !semJogo && c.jogos < minimoJogos
                    const primeiro = i === 0 && !semJogo && !amostraCurta
                    const posCls = i === 0 ? 'text-yellow-400' : i === 1 ? 'text-ink-2' : i === 2 ? 'text-ink-3' : 'text-ink-4'
                    return (
                      <button key={t.team_id}
                        onClick={() => setTimeAberto(t)}
                        className={`w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/50 transition-colors ${
                          primeiro ? 'bg-green-500/5' : ''}`}>
                        <span className={`font-mono text-sm font-black w-6 shrink-0 text-right ${posCls}`}>{i + 1}</span>
                        <img src={LOGO_TIME(t.team_id)} alt="" width={24} height={24}
                          className="w-6 h-6 object-contain shrink-0"
                          onError={ev => (ev.currentTarget.style.display = 'none')} />
                        <span className="flex-1 min-w-0">
                          <span className="block text-sm text-ink-2 font-semibold truncate">{t.nome}</span>
                          <span className="flex items-center gap-2 mt-0.5">
                            <span className="font-mono text-[10px] text-ink-4 shrink-0">
                              {c.jogos}j {c.v}-{c.e}-{c.d}
                            </span>
                            <Forma forma={c.forma} />
                            {/* Diz POR QUE o time está lá embaixo. Sem a marca,
                                um número alto no fim da lista lê como bug. */}
                            {amostraCurta && (
                              <span className="text-[9px] font-bold text-yellow-400/80 shrink-0">
                                amostra curta
                              </span>
                            )}
                          </span>
                        </span>
                        <span className={`font-mono text-base font-black shrink-0 tabular-nums w-16 text-right ${
                          semJogo || amostraCurta ? 'text-ink-4' : primeiro ? 'text-green-400' : 'text-ink-2'}`}>
                          {semJogo ? '-' : fmt(c[metrica], def.casas, def.sufixo)}
                        </span>
                      </button>
                    )
                  })}
                </div>

                <p className="px-4 py-2.5 text-[10px] text-ink-4 border-t border-line/60 leading-relaxed">
                  Aproveitamento é ponto ganho sobre ponto disputado. Time com menos da metade dos jogos
                  da mediana da liga fica no fim marcado como amostra curta, porque média de dois jogos
                  não se compara com média de trinta e oito. Toque num time pra ver os cartões, que
                  custam uma consulta extra e por isso não vêm na lista.
                </p>
              </div>
            </>
          )}
        </>
      )}

      {/* Detalhe do time */}
      {timeAberto && (
        <Modal onClose={() => setTimeAberto(null)} width="md" hideClose>
          <div className="px-4 py-4 border-b border-line flex items-center justify-between gap-3 bg-surface-2">
            <div className="flex items-center gap-3 min-w-0">
              <img src={LOGO_TIME(timeAberto.team_id)} alt="" width={32} height={32}
                className="w-8 h-8 object-contain shrink-0"
                onError={ev => (ev.currentTarget.style.display = 'none')} />
              <div className="min-w-0">
                <h3 className="text-base font-bold text-ink-1 truncate">{timeAberto.nome}</h3>
                <p className="text-[11px] text-ink-4">{liga?.nome} · {temporada}</p>
              </div>
            </div>
            <button onClick={() => setTimeAberto(null)} aria-label="Fechar"
              className="text-ink-3 hover:text-ink-1 p-1 transition-colors shrink-0">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="p-4 space-y-4 max-h-[70vh] overflow-y-auto">
            {/* Os três recortes lado a lado: é a leitura que a lista não dá,
                porque lá só aparece o recorte escolhido. */}
            <div className="grid grid-cols-3 gap-2">
              {(['todos', 'casa', 'fora'] as Recorte[]).map(r => {
                const c = timeAberto[r]
                return (
                  <div key={r} className="card p-3 text-center">
                    <div className="text-[10px] text-ink-4 font-semibold uppercase tracking-wide mb-1">
                      {r === 'todos' ? 'Todos' : r === 'casa' ? 'Casa' : 'Fora'}
                    </div>
                    <div className="font-mono text-lg font-black text-ink-1">{c.aproveitamento_pct}%</div>
                    <div className="text-[10px] text-ink-4 mt-0.5">{c.jogos}j · {c.v}-{c.e}-{c.d}</div>
                    <div className="mt-2 pt-2 border-t border-line/60 font-mono text-[11px] text-ink-2">
                      {c.media_gols_pro.toFixed(2)} <span className="text-ink-4">marcados</span>
                    </div>
                    <div className="font-mono text-[11px] text-ink-2">
                      {c.media_gols_contra.toFixed(2)} <span className="text-ink-4">sofridos</span>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="grid grid-cols-3 gap-2">
              <StatTile label="Ambos marcam"  value={`${timeAberto[recorte].btts_pct}%`} />
              <StatTile label="Over 2.5"      value={`${timeAberto[recorte].over25_pct}%`} />
              <StatTile label="Sem sofrer"    value={`${timeAberto[recorte].clean_sheet_pct}%`} />
            </div>

            {carregandoTime ? (
              <SpinnerBlock className="py-10" />
            ) : !detalheTime ? (
              <p className="text-center text-ink-4 text-sm py-6">
                A fonte não tem o detalhe de cartões desse time nessa temporada.
              </p>
            ) : (
              <div className="card p-0 overflow-hidden">
                <div className="px-4 py-3 border-b border-line">
                  <h4 className="text-sm font-bold text-ink-1">Cartões na temporada</h4>
                  <p className="text-[11px] text-ink-4 mt-0.5">
                    <span className="text-yellow-400 font-semibold">{detalheTime.cartoes.amarelo.por_jogo}</span> amarelos
                    e <span className="text-red-400 font-semibold">{detalheTime.cartoes.vermelho.por_jogo}</span> vermelhos por jogo
                    · {detalheTime.jogos.todos} jogos
                  </p>
                </div>
                <div className="p-4 space-y-1.5">
                  {detalheTime.cartoes.amarelo.faixas.map(f => {
                    const maior = Math.max(...detalheTime.cartoes.amarelo.faixas.map(x => x.total), 1)
                    return (
                      <div key={f.faixa} className="flex items-center gap-2">
                        <span className="font-mono text-[10px] text-ink-4 w-14 shrink-0">{f.faixa}'</span>
                        <div className="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden">
                          <div className="h-full bg-yellow-400/70 rounded-full transition-all"
                            style={{ width: `${(f.total / maior) * 100}%` }} />
                        </div>
                        <span className="font-mono text-[11px] text-ink-3 w-6 text-right shrink-0">{f.total}</span>
                      </div>
                    )
                  })}
                </div>
                <p className="px-4 py-2.5 text-[10px] text-ink-4 border-t border-line/60">
                  Amarelos por faixa de minuto do jogo. Serve pra ver se o time leva cartão cedo ou
                  só quando o jogo aperta no fim.
                </p>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}
