import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, Database, Gavel, Pencil, PlayCircle, RefreshCw,
  Save, ShieldAlert, User, Users, X,
} from 'lucide-react'
import api from '../services/api'
import AdminAmostra, { type AlvoAmostra } from './AdminAmostra'
import { sinalizarNavegacao } from '../services/progressBus'
import {
  Button, EmptyState, ErrorState, Pagination, Skeleton, SkeletonRows, SpinnerBlock, StatTile,
} from './ui'

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
  /* Ecoados pelo servidor · ele descarta chave desconhecida, e a tela precisa
   * saber disso pra não desenhar um filtro que não está valendo. */
  filtro?: string | null
  meses?: number | null
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

/** Médias de time que estão mais velhas que a última partida do time.
 *
 * `team_statistics` é o que o motor lê, e é DERIVADA de `match_statistics` ·
 * derivada não se atualiza sozinha. Coletar a partida e não refazer a média
 * deixa o motor lendo a média de ontem sobre um histórico de hoje, que é o pior
 * dos dois mundos porque parece atualizado. */
interface Medias {
  disponivel: boolean
  total: number
  rodando: boolean
  feitas: number
  falhas: number
  terminada_em?: string | null
  erro?: string | null
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

/** Uma linha de `referee_stats`, com a amostra que a sustenta. */
interface Arbitro {
  referee_id: number
  name: string
  games: number | null
  games_total: number | null
  avg_yellow: number | string | null
  avg_red: number | string | null
  avg_fouls: number | string | null
  avg_corners: number | string | null
  atualizado_em: string | null
}

/** Partida com 0x0 gravado que não terminou 0x0 · ver o cartão lá embaixo. */
interface PlacarFalso {
  disponivel: boolean
  total?: number
  corrigiveis?: number
  so_recoleta?: number
  partidas?: {
    fixture_id: number
    data: string | null
    status: string | null
    liga: string | null
    mandante: string | null
    visitante: string | null
    home_goals_90: number | null
    away_goals_90: number | null
    home_goals_ht: number | null
    away_goals_ht: number | null
  }[]
  erro?: string
}

/** Uma linha de `player_match_stats` agregada · o que o Player Stats lê. */
interface Jogador {
  player_id: number
  nome: string | null
  time: string | null
  posicao: string | null
  atuacoes: number
  minutos: number | string | null
  ultima: string | null
  /* As médias e as contagens chegam como `<chave>_m` e `<chave>_n`, uma por
   * coluna · a contagem é por coluna de propósito: defesa aparece em 0,86% das
   * atuações e passe em todas, então um "12 jogos" único mentiria sobre uma
   * das duas. */
  [k: string]: unknown
}

interface Jogadores {
  season: number | null
  temporadas: number[]
  mando: string
  ordenar?: string
  league_id?: number | null
  ligas: { league_id: number; liga: string | null; atuacoes: number }[]
  total: number
  jogadores: Jogador[]
  min_minutos: number
  colunas: { chave: string; rotulo: string }[]
  erro?: string
}

/** Uma linha de `team_statistics` agregada · a média que o motor lê do time.
 *
 * A lista nasce das PARTIDAS, e não da tabela de médias: o time que nunca teve
 * média calculada é o caso mais desatualizado que existe, e partindo da tabela
 * de médias ele simplesmente não apareceria. Por isso `sem_media` é uma linha
 * com as colunas vazias, e não uma ausência de linha. */
interface TimeMedia {
  team_id: number
  league_id: number | null
  season: number | null
  time: string | null
  liga: string | null
  /** Partidas do time em `match_statistics` · a matéria-prima da média. */
  partidas: number
  ultima_partida: string | null
  /** Jogos que entraram na média. Menor que `partidas` quando falta contexto. */
  jogos: number | null
  calculada_em: string | null
  sem_media: boolean
  desatualizada: boolean
  amostra_curta: boolean
  /** As médias chegam como `<chave>_m`, uma por coluna. */
  [k: string]: unknown
}

interface Times {
  season: number | null
  temporadas: number[]
  ligas: { league_id: number; liga: string | null; partidas: number }[]
  league_id?: number | null
  mando: string
  problema?: string | null
  ordenar?: string
  total: number
  times: TimeMedia[]
  min_jogos: number
  colunas: { chave: string; rotulo: string }[]
  velhas: number
  sem_media: number
  curtas: number
  erro?: string
}

interface Vermelho {
  disponivel: boolean
  alvo?: number
  sem_vermelho?: number
  folha_incompleta?: number
  erro?: string
}

const POR_PAGINA = 10

/* AS CINCO PERGUNTAS DA TELA, na ordem em que se caminha por elas.
 *
 * O corte não é por assunto, é pela pergunta que cada uma responde:
 *
 *   Problemas   o que está errado AGORA e o que dá pra fazer;
 *   Cobertura   o que o motor tem pra ler, e onde estão os furos;
 *   Times       a média que o motor de fato lê, e o estado de cada uma;
 *   Partidas    jogo a jogo, com o que a folha não trouxe;
 *   Pessoas     árbitro e jogador, a mesma régua aplicada ao indivíduo.
 *
 * Times e Pessoas nasceram de dentro de Partidas em 28/08: a aba tinha três
 * tabelas grandes empilhadas, e a lista de jogos · que é onde ficam os botões
 * de conserto · era a última das três. Quem abria "Partidas" caía em árbitros.
 */
const SECOES = [
  ['problemas', 'Problemas'],
  ['cobertura', 'Cobertura'],
  ['times', 'Times'],
  ['partidas', 'Partidas'],
  ['pessoas', 'Pessoas'],
] as const

type Secao = (typeof SECOES)[number][0]

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

  /* O filtro que veio do diagnóstico.
   *
   * Ele mora aqui e não dentro do card do diagnóstico porque quem responde é a
   * lista de partidas, que fica em OUTRA seção · clicar num número da Cobertura
   * leva pra Partidas já filtrada. É esse pulo que fecha o ciclo "vejo o
   * buraco, chego na partida, escrevo o número", que era um beco: se a API não
   * publica a folha daquele jogo, e ela não publica folha velha, não havia como
   * alcançar a partida pela tela. */
  const [filtroPartidas, setFiltroPartidas] = useState<{ chave: string; rotulo: string } | null>(null)

  const [buracos, setBuracos] = useState<Buraco[] | null>(null)
  const [verBuracos, setVerBuracos] = useState(false)
  const [vermelho, setVermelho] = useState<Vermelho | null>(null)
  const [corrigindoVermelho, setCorrigindoVermelho] = useState(false)
  const [placar, setPlacar] = useState<PlacarFalso | null>(null)
  const [corrigindoPlacar, setCorrigindoPlacar] = useState(false)

  const [diagnostico, setDiagnostico] = useState<Diagnostico | null>(null)
  const [medias, setMedias] = useState<Medias | null>(null)
  const [pedindoMedias, setPedindoMedias] = useState(false)
  const [recoleta, setRecoleta] = useState<Recoleta | null>(null)
  const [lote, setLote] = useState(20)
  const [pedindoLote, setPedindoLote] = useState(false)

  const [arbitros, setArbitros] = useState<{
    season: number | null; temporadas: number[]; arbitros: Arbitro[]
    amostra_minima?: number; total?: number
  } | null>(null)
  const [recalculandoArbitros, setRecalculandoArbitros] = useState(false)
  const [paginaArbitros, setPaginaArbitros] = useState(0)
  const [buscaArbitro, setBuscaArbitro] = useState('')

  const [jogadores, setJogadores] = useState<Jogadores | null>(null)
  const [mandoJogadores, setMandoJogadores] = useState<'todos' | 'casa' | 'fora'>('todos')
  const [ordenarJogadores, setOrdenarJogadores] = useState('chutes')
  const [paginaJogadores, setPaginaJogadores] = useState(0)
  const [buscaJogador, setBuscaJogador] = useState('')
  /* Competição do recorte. Um jogador atua em duas na mesma temporada, e chute
   * no Brasileirão e chute na Libertadores não são a mesma população · somados
   * numa linha só, o número não descreve nenhum dos dois. Vazio = todas, e aí a
   * linha que mistura é marcada em vez de mentir calada. */
  const [ligaJogadores, setLigaJogadores] = useState<number | ''>('')

  /** Alvo do drawer de amostra · time ou árbitro, um por vez. */
  /* Médias de time · a aba nova. O recorte inteiro vive aqui porque cada
   * controle refaz a consulta, e o servidor devolve o que aceitou (o mando
   * ou a ordenação inválida viram o padrão lá, não um erro). */
  const [times, setTimes] = useState<Times | null>(null)
  const [paginaTimes, setPaginaTimes] = useState(0)
  const [mandoTimes, setMandoTimes] = useState<'todos' | 'casa' | 'fora'>('todos')
  const [ligaTimes, setLigaTimes] = useState<number | ''>('')
  const [problemaTimes, setProblemaTimes] = useState<'' | 'velha' | 'sem_media' | 'curta'>('')
  const [ordenarTimes, setOrdenarTimes] = useState('gols')
  const [buscaTime, setBuscaTime] = useState('')

  const [amostra, setAmostra] = useState<AlvoAmostra | null>(null)

  /* Em qual das três perguntas a tela está.
   *
   * Ela nasceu como uma pilha só, e a pilha cresceu: dois alertas, oito
   * contadores, o estado da varredura, o diagnóstico do histórico com dezesseis
   * cartões, as médias das últimas 40, a tabela de árbitros e a lista paginada
   * de partidas. Num celular isso é meio metro de rolagem em que tudo tem o
   * mesmo peso visual, e o alerta que pede ação some no meio da estatística que
   * é só informação.
   *
   * O corte não é por assunto, é pela pergunta que cada bloco responde:
   *
   *   Problemas   o que está errado AGORA e o que dá pra fazer;
   *   Cobertura   o que o motor tem pra ler, e onde estão os furos;
   *   Partidas    jogo a jogo, com árbitro e amostra.
   *
   * A contagem de problemas fica no próprio botão, senão trocar de seção
   * viraria esconder o alerta. */
  const [secao, setSecao] = useState<Secao>('problemas')

  /** fixture_id em coleta. Um por vez: cada clique custa 2 requisições da cota. */
  const [rodando, setRodando] = useState<number | null>(null)
  const [aviso, setAviso] = useState<{ fixture: number; texto: string; ok: boolean } | null>(null)

  /** Edição manual: fixture aberto, rascunho em texto, erro do servidor. */
  const [editando, setEditando] = useState<number | null>(null)
  const [rascunho, setRascunho] = useState<Record<string, [string, string]>>({})
  const [salvando, setSalvando] = useState(false)
  const [erroEdicao, setErroEdicao] = useState('')

  const buscarHistorico = useCallback((p: number, filtro?: string | null, meses?: number) => {
    setTrocandoPagina(true)
    setAberta(null)
    setEditando(null)
    api.get('/admin/dados/partidas', {
      params: {
        pagina: p, por_pagina: POR_PAGINA,
        ...(filtro ? { filtro, meses: meses ?? 24 } : {}),
      },
    })
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
    api.get('/admin/dados/placar-falso')
      .then(r => setPlacar(r.data))
      .catch(() => setPlacar(null))
  }, [])

  const buscarDiagnostico = useCallback((meses = 12) => {
    api.get('/admin/dados/diagnostico', { params: { meses } })
      .then(r => setDiagnostico(r.data))
      .catch(() => setDiagnostico(null))
  }, [])

  const buscarArbitros = useCallback((season?: number | null, pagina = 0, busca = '') => {
    setPaginaArbitros(pagina)
    api.get('/admin/dados/arbitros', {
      params: {
        ...(season != null ? { season } : {}),
        pagina, por_pagina: POR_PAGINA,
        ...(busca.trim() ? { busca: busca.trim() } : {}),
      },
    })
      .then(r => setArbitros(r.data))
      .catch(() => setArbitros(null))
  }, [])

  const buscarJogadores = useCallback((
    season?: number | null,
    mando: 'todos' | 'casa' | 'fora' = 'todos',
    ordenar = 'chutes',
    pagina = 0,
    busca = '',
    liga: number | '' = '',
  ) => {
    setPaginaJogadores(pagina)
    api.get('/admin/dados/jogadores', {
      params: {
        ...(season != null ? { season } : {}),
        mando, ordenar, pagina, por_pagina: POR_PAGINA,
        ...(busca.trim() ? { busca: busca.trim() } : {}),
        ...(liga !== '' ? { league_id: liga } : {}),
      },
    })
      .then(r => setJogadores(r.data))
      .catch(() => setJogadores(null))
  }, [])

  /* Abre a amostra a partir da PARTIDA. A lista não carrega os ids dos times ·
   * seriam duas colunas a mais em toda linha pra servir a um clique, então o
   * id é resolvido na hora, pelo fixture, que é a chave que as duas pontas
   * têm. O mesmo caminho serve à aba Motor, onde o log guarda só o nome. */
  const abrirAmostraDaPartida = async (fixtureId: number, lado: 'casa' | 'fora') => {
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
    } catch (e) {
      setAviso({ fixture: fixtureId, texto: msgErro(e, 'Não deu pra abrir a amostra.'), ok: false })
    }
  }

  const recalcularArbitros = async () => {
    setRecalculandoArbitros(true)
    try {
      const r = await api.post('/admin/dados/arbitros/recalcular', null,
        { params: arbitros?.season != null ? { season: arbitros.season } : {} })
      setAviso({ fixture: -3, texto: r.data?.mensagem ?? 'Recalculado.', ok: true })
      buscarArbitros(arbitros?.season, paginaArbitros, buscaArbitro)
    } catch (e) {
      setAviso({ fixture: -3, texto: msgErro(e, 'Não deu pra recalcular.'), ok: false })
    } finally {
      setRecalculandoArbitros(false)
    }
  }

  /** A consulta de times. Tudo que a tela filtra viaja junto: o servidor não
   *  guarda recorte nenhum, e cada controle refaz a pergunta inteira. */
  const buscarTimes = useCallback((o: {
    season?: number | null
    liga?: number | ''
    mando?: 'todos' | 'casa' | 'fora'
    problema?: '' | 'velha' | 'sem_media' | 'curta'
    ordenar?: string
    busca?: string
    pagina?: number
  }) => {
    const pagina = o.pagina ?? 0
    setPaginaTimes(pagina)
    api.get('/admin/dados/times', {
      params: {
        ...(o.season != null ? { season: o.season } : {}),
        ...(o.liga !== '' && o.liga != null ? { league_id: o.liga } : {}),
        mando: o.mando ?? 'todos',
        ...(o.problema ? { problema: o.problema } : {}),
        ordenar: o.ordenar ?? 'gols',
        ...(o.busca?.trim() ? { busca: o.busca.trim() } : {}),
        pagina, por_pagina: POR_PAGINA,
      },
    })
      .then(r => setTimes(r.data))
      .catch(() => setTimes(t => (t ? { ...t, erro: 'Não deu pra ler as médias de time.' } : null)))
  }, [])

  const buscarMedias = useCallback(() => {
    api.get('/admin/dados/medias-velhas')
      .then(r => setMedias(r.data))
      .catch(() => setMedias(null))
  }, [])

  const buscarRecoleta = useCallback(() => {
    api.get('/admin/dados/recoleta-status')
      .then(r => setRecoleta(r.data))
      .catch(() => {})
  }, [])

  /* O QUE JÁ FOI PEDIDO. Uma chave por recurso, não por seção · `historico`
   * serve a duas abas, e marcar por seção o faria vir duas vezes. */
  const carregadas = useRef<Set<string>>(new Set())

  const puxar = (chave: string, fn: () => void) => {
    if (carregadas.current.has(chave)) return
    carregadas.current.add(chave)
    fn()
  }

  /* CADA SEÇÃO PUXA O QUE ELA MOSTRA, na primeira vez que é aberta.
   *
   * Até 28/08 o mount disparava NOVE requisições de uma vez · estado do banco,
   * buracos, vermelho legado, placar falso, diagnóstico, recoleta, médias,
   * árbitros e jogadores. O navegador só mantém seis conexões por origem, e
   * várias dessas consultas varrem tabela grande, então as últimas ficavam na
   * fila até estourar o timeout de 15s do axios · a tela inteira travava numa
   * bolinha e terminava no toast de "o servidor demorou para responder".
   *
   * O único bloco que continua no mount é o estado do banco (que desenha a
   * tela) e o de Problemas, que é a seção inicial e a que tem alerta. */
  const buscarEstado = () => {
    setCarregando(true)
    setErro('')
    api.get('/admin/dados')
      .then(r => setDados(r.data))
      .catch(e => setErro(msgErro(e, 'Não deu pra ler o estado do banco.')))
      .finally(() => setCarregando(false))
  }

  useEffect(() => {
    if (secao === 'problemas') {
      puxar('buracos', buscarBuracos)
      puxar('medias', buscarMedias)
      puxar('recoleta', buscarRecoleta)
    } else if (secao === 'cobertura') {
      puxar('diagnostico', () => buscarDiagnostico(12))
      puxar('historico', () => buscarHistorico(0, filtroPartidas?.chave))
    } else if (secao === 'times') {
      puxar('medias', buscarMedias)
      puxar('times', () => buscarTimes({ mando: mandoTimes, ordenar: ordenarTimes }))
    } else if (secao === 'partidas') {
      puxar('historico', () => buscarHistorico(0, filtroPartidas?.chave))
    } else if (secao === 'pessoas') {
      puxar('arbitros', () => buscarArbitros())
      puxar('jogadores', () => buscarJogadores())
    }
  }, [secao])

  /** "Atualizar" · esquece o que já veio e repete só o da seção aberta. */
  const buscar = () => {
    carregadas.current.clear()
    setPagina(0)
    buscarEstado()
    if (secao === 'problemas') {
      buscarBuracos(); buscarMedias(); buscarRecoleta()
      carregadas.current.add('buracos'); carregadas.current.add('medias')
      carregadas.current.add('recoleta')
    } else if (secao === 'cobertura') {
      buscarDiagnostico(diagnostico?.meses ?? 12)
      buscarHistorico(0, filtroPartidas?.chave, diagnostico?.meses)
      carregadas.current.add('diagnostico'); carregadas.current.add('historico')
    } else if (secao === 'times') {
      buscarMedias()
      buscarTimes({ season: times?.season, liga: ligaTimes, mando: mandoTimes,
                    problema: problemaTimes, ordenar: ordenarTimes, busca: buscaTime })
      carregadas.current.add('medias'); carregadas.current.add('times')
    } else if (secao === 'partidas') {
      buscarHistorico(0, filtroPartidas?.chave, diagnostico?.meses)
      carregadas.current.add('historico')
    } else if (secao === 'pessoas') {
      buscarArbitros(arbitros?.season, 0, buscaArbitro)
      buscarJogadores(jogadores?.season, mandoJogadores, ordenarJogadores, 0,
                      buscaJogador, ligaJogadores)
      carregadas.current.add('arbitros'); carregadas.current.add('jogadores')
    }
  }

  useEffect(buscarEstado, [])

  /* Enquanto o lote roda, a tela pergunta o estado. O intervalo é de 3s e não
   * de 1s de propósito: o trabalho é de segundos POR PARTIDA (duas requisições
   * à API cada), então pesquisar mais rápido só gera request sem novidade. */
  /* Enquanto o recálculo roda, a tela pergunta o estado. Não custa API
   * nenhuma do provedor · sai tudo do banco, então o intervalo pode ser curto
   * sem o cuidado que a recoleta exige. */
  useEffect(() => {
    if (!medias?.rodando) return
    const t = setInterval(() => {
      api.get('/admin/dados/medias-velhas')
        .then(r => {
          setMedias(r.data)
          if (!r.data?.rodando) api.get('/admin/dados').then(x => setDados(x.data)).catch(() => {})
        })
        .catch(() => {})
    }, 2000)
    return () => clearInterval(t)
  }, [medias?.rodando])

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
            buscarHistorico(pagina, filtroPartidas?.chave, diagnostico?.meses)
            buscarBuracos()
            buscarDiagnostico(diagnostico?.meses ?? 12)
          }
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(t)
  }, [recoleta?.rodando, pagina, diagnostico?.meses, filtroPartidas?.chave,
      buscarHistorico, buscarBuracos, buscarDiagnostico])

  const recalcularMedias = async () => {
    setPedindoMedias(true)
    setAviso(null)
    try {
      const r = await api.post('/admin/dados/medias-velhas')
      setAviso({ fixture: -5, texto: r.data?.mensagem ?? 'Recálculo iniciado.', ok: true })
      buscarMedias()
    } catch (e) {
      setAviso({ fixture: -5, texto: msgErro(e, 'Não deu pra iniciar.'), ok: false })
    } finally {
      setPedindoMedias(false)
    }
  }

  /* `filtro` é o recorte que a tela está mostrando · sem ele o lote sempre
   * atacou "as mais recentes furadas", que raramente é o que quem clicou
   * acabou de escolher. Com filtro a janela também muda: o recorte de família
   * vive no diagnóstico, e o buraco que ele aponta costuma ser mais velho que
   * os 3 meses do lote solto. */
  const dispararRecoleta = async (filtro?: string) => {
    setPedindoLote(true)
    setAviso(null)
    try {
      const r = await api.post('/admin/dados/recoletar', null,
        { params: filtro
            ? { limite: lote, meses: diagnostico?.meses ?? 12, filtro }
            : { limite: lote, meses: 3 } })
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
    buscarHistorico(p, filtroPartidas?.chave, diagnostico?.meses)
  }

  /* Um número do diagnóstico -> as partidas por trás dele.
   *
   * Troca de seção junto de propósito: o botão de conserto mora na lista, e
   * deixar o usuário filtrando de uma aba e procurando na outra seria o mesmo
   * beco de antes com um clique a mais. */
  const abrirFiltro = (chave: string, rotulo: string) => {
    setFiltroPartidas({ chave, rotulo })
    setPagina(0)
    setSecao('partidas')
    buscarHistorico(0, chave, diagnostico?.meses)
  }

  const limparFiltro = () => {
    setFiltroPartidas(null)
    setPagina(0)
    buscarHistorico(0)
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
        buscarHistorico(pagina, filtroPartidas?.chave, diagnostico?.meses)
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
      buscarHistorico(pagina, filtroPartidas?.chave, diagnostico?.meses)
      buscarBuracos()
    } catch (e) {
      setErroEdicao(msgErro(e, 'Não deu pra gravar.'))
    } finally {
      setSalvando(false)
    }
  }

  const corrigirPlacar = async () => {
    setCorrigindoPlacar(true)
    try {
      const r = await api.post('/admin/dados/placar-falso')
      setAviso({
        fixture: -4, ok: true,
        texto: `${r.data?.corrigidas ?? 0} placar(es) reescrito(s) · ${r.data?.medias ?? 0} média(s) de time refeitas.`,
      })
      buscarBuracos()
      buscarHistorico(pagina, filtroPartidas?.chave, diagnostico?.meses)
      api.get('/admin/dados').then(x => setDados(x.data)).catch(() => {})
    } catch (e) {
      setAviso({ fixture: -4, texto: msgErro(e, 'Não deu pra corrigir.'), ok: false })
    } finally {
      setCorrigindoPlacar(false)
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
      buscarHistorico(pagina, filtroPartidas?.chave, diagnostico?.meses)
      buscarBuracos()
    } catch (e) {
      setAviso({ fixture: -1, texto: msgErro(e, 'Não deu pra corrigir.'), ok: false })
    } finally {
      setCorrigindoVermelho(false)
    }
  }

  /* ESQUELETO NO LUGAR DA BOLINHA (28/08).
   *
   * Um spinner centralizado numa caixa vazia não diz o que está vindo, e
   * quando a resposta demora ele parece travado · a animação continua, mas
   * sem nada em volta pra dar referência de movimento não há como notar.
   * O esqueleto já nasce com a forma da tela (título, as cinco abas, o cartão
   * de alerta, os contadores e a lista), então o conteúdo só preenche o que
   * já estava reservado, e a barra de progresso do topo cuida do resto. */
  if (carregando && !dados) return (
    <div className="space-y-6" aria-busy="true">
      <div className="flex items-center justify-between gap-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="flex gap-1.5">
        {SECOES.map(([chave]) => <Skeleton key={chave} className="h-9 w-24 shrink-0" />)}
      </div>
      <Skeleton className="h-20 w-full rounded-xl" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
      </div>
      <div className="card p-0 overflow-hidden"><SkeletonRows rows={4} /></div>
    </div>
  )
  if (erro) return <ErrorState title="Não deu pra ler o estado do banco" description={erro} onRetry={buscar} />
  if (!dados) return null

  const totalBuracos = dados.buracos?.total ?? 0
  // Um por CARTÃO de alerta, não por partida · o número no botão responde
  // "quantas coisas eu preciso olhar", e 300 buracos continuam sendo uma.
  const abertos = [
    totalBuracos > 0,
    !!placar?.disponivel && (placar.total ?? 0) > 0,
    !!vermelho?.disponivel && (vermelho.alvo ?? 0) > 0,
  ].filter(Boolean).length
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

      {/* Quantos alertas estão abertos. É o que faz a navegação não esconder
        * problema: o número vive no botão, não dentro da seção. */}
      <div className="flex gap-1.5 overflow-x-auto">
        {SECOES.map(([chave, rotulo]) => {
          const n = chave === 'problemas' ? abertos
            : chave === 'times' ? (medias?.total ?? 0)
            : 0
          return (
          <button
            key={chave}
            type="button"
            onClick={() => { if (chave !== secao) sinalizarNavegacao(); setSecao(chave) }}
            className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-2 min-h-[36px] rounded-lg border shrink-0 transition-colors duration-1 ${
              secao === chave
                ? 'border-line-strong bg-surface-2 text-ink-1'
                : 'border-line text-ink-3 hover:text-ink-2'}`}
          >
            {rotulo}
            {n > 0 && (
              <span className="font-mono text-[10px] tabular-nums text-yellow-400">{n}</span>
            )}
          </button>
          )
        })}
      </div>

      {secao === 'problemas' && (<>

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
      {/* Placar 0x0 que não aconteceu.
        *
        * Os três leitores de /fixtures montavam a linha com
        * `goals["home"] or 0`, e `or 0` não separa "a API disse zero" de "a API
        * não disse nada". Campo nulo virava jogo terminado 0x0 · e gol é a
        * família que mais mercado gera.
        *
        * Zero não é NULL, então esse jogo passa por "preenchido" em TODA
        * contagem de cobertura desta tela e some da varredura. É por isso que
        * ele precisa de cartão próprio: nenhum outro número daqui o enxerga.
        *
        * A detecção não é palpite: o placar de 90 minutos e o do intervalo são
        * colunas independentes, gravadas na mesma passada e sem o `or 0`. Final
        * 0x0 com qualquer uma delas acima de zero é impossível. */}
      {placar?.disponivel && (placar.total ?? 0) > 0 && (
        <div className="card p-4 border border-red-500/40 bg-red-500/5">
          <div className="flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-ink-1">
                {numero(placar.total)} partida(s) gravadas 0x0 sem terem terminado 0x0
              </p>
              <p className="text-[11px] text-ink-3 mt-1 leading-relaxed">
                O coletor lia placar ausente como zero. Zero não é ausência: essas linhas entram
                na média de gols como jogo real, e como o campo está "preenchido" elas não
                aparecem em nenhuma contagem de cobertura nem na varredura automática. O placar
                de 90 minutos e o do intervalo, que vêm noutras colunas, provam a contradição ·
                onde os três concordam em zero, o 0x0 é real e a linha não é tocada.
                {!!placar.so_recoleta && (
                  <> {numero(placar.so_recoleta)} delas foram para a prorrogação, e aí o placar
                  de 90 minutos não responde pelo final · essas só voltam pela recoleta.</>
                )}
              </p>

              {!!placar.partidas?.length && (
                <div className="mt-2.5 border-t border-line/60 divide-y divide-line/60">
                  {placar.partidas.slice(0, 6).map(b => (
                    <div key={b.fixture_id} className="py-1.5">
                      <p className="text-[12px] text-ink-2 truncate">
                        <span className="font-mono text-[10px] text-ink-4 mr-1.5">{diaMes(b.data)}</span>
                        {b.mandante ?? 'Time ?'} x {b.visitante ?? 'Time ?'}
                      </p>
                      <p className="text-[10px] text-ink-4 mt-0.5 font-mono tabular-nums">
                        gravado 0x0 · 90 minutos {numero(b.home_goals_90)}x{numero(b.away_goals_90)}
                        {' '}· intervalo {numero(b.home_goals_ht)}x{numero(b.away_goals_ht)}
                        {' '}· {b.status}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {(placar.corrigiveis ?? 0) > 0 && (
                <Button
                  size="sm" variant="ghost" className="mt-3"
                  loading={corrigindoPlacar}
                  onClick={corrigirPlacar}
                >
                  Reescrever {numero(placar.corrigiveis)} placar(es) pelo de 90 minutos e refazer as médias
                </Button>
              )}
              {aviso?.fixture === -4 && (
                <p className={`text-[11px] mt-2 ${aviso.ok ? 'text-green-400' : 'text-red-400'}`}>
                  {aviso.texto}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

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

      {!abertos && (
        <p className="text-[11px] text-ink-4 leading-relaxed">
          Nada pendente aqui. A cobertura e o histórico ficam nas outras duas seções ·
          esta só mostra o que pede ação.
        </p>
      )}

      </>)}

      {secao === 'cobertura' && (<>

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
            {/* Os dois números com conserto viram BOTÃO · levam pra lista de
              * partidas já filtrada, que é onde moram Rodar e Preencher à mão.
              * "Sem linha nenhuma" fica fora porque ele não é desta tabela: é
              * partida sem linha, e o cartão dela está em Problemas. */}
            <button type="button" className="text-left"
                    onClick={() => abrirFiltro('folha_incompleta', 'folha incompleta')}>
              <StatTile label="Folha incompleta" value={numero(diagnostico.incompletas)}
                tone={diagnostico.incompletas > 0 ? 'red' : 'default'}
                hint={diagnostico.incompleta_mais_antiga
                  ? `mais antiga em ${diaMes(diagnostico.incompleta_mais_antiga)} · toque para ver`
                  : 'toque para ver'} />
            </button>
            <button type="button" className="text-left" onClick={() => setSecao('problemas')}>
              <StatTile label="Sem linha nenhuma" value={numero(diagnostico.sem_linha)}
                tone={diagnostico.sem_linha > 0 ? 'red' : 'default'}
                hint="essas ficam em Problemas" />
            </button>
            <button type="button" className="text-left"
                    onClick={() => abrirFiltro('zeradas', 'coletadas zeradas')}>
              <StatTile label="Coletadas zeradas" value={numero(diagnostico.zeradas)}
                tone={diagnostico.zeradas > 0 ? 'red' : 'default'}
                hint="escanteio, chute e falta em 0 · toque para ver" />
            </button>
          </div>

          {/* Família por família, com a data do buraco mais antigo. É o que
            * separa "defeito que voltou agora" de "cicatriz de julho": os dois
            * aparecem como cobertura baixa, e só um pede ação.
            *
            * O número grande é quantos jogos estão SEM aquela estatística ·
            * não quantos têm. Foi a primeira coisa que a tela não conseguiu
            * dizer sozinha, então agora ela diz no cabeçalho e em cada
            * cartão. */}
          <p className="text-[11px] font-semibold text-ink-2 mt-4 mb-1.5">
            Jogos <span className="text-yellow-400">sem</span> cada estatística
          </p>
          <p className="text-[11px] text-ink-4 mb-2 leading-relaxed">
            Quanto maior o número, maior o buraco. Estatística que só passou a existir depois
            aparece alta aqui de propósito: gols do 1º tempo e dos 90 minutos são colunas novas,
            e jogo coletado antes delas nunca vai ter o número · a data ao lado é a do jogo mais
            antigo sem ela.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {diagnostico.familias.map(f => (
              <button
                key={f.chave}
                type="button"
                disabled={f.sem_dado === 0}
                onClick={() => abrirFiltro(f.chave, f.rotulo.toLowerCase())}
                className={`text-left rounded-lg border p-2.5 min-h-[64px] transition-colors duration-1 ${
                  f.sem_dado > 0
                    ? 'border-yellow-500/40 bg-yellow-500/5 hover:border-yellow-500/70'
                    : 'border-line cursor-default'}`}
              >
                <p className="text-[10px] text-ink-4 leading-tight truncate" title={f.rotulo}>
                  {f.rotulo}
                </p>
                <p className={`font-mono text-base font-black tabular-nums leading-tight mt-0.5 ${
                  f.sem_dado > 0 ? 'text-yellow-400' : 'text-ink-1'}`}>
                  {numero(f.sem_dado)}
                </p>
                <p className="text-[10px] font-mono tabular-nums text-ink-4">
                  {f.sem_dado > 0
                    ? `de ${numero(diagnostico.ft)} · desde ${diaMes(f.desde)}`
                    : 'nenhum buraco'}
                </p>
              </button>
            ))}
          </div>

          {/* A frase que faltava. O diagnóstico dizia o tamanho do buraco e
            * parava ali · e a recoleta em lote, logo abaixo, só resolve o caso
            * em que a API AINDA tem a folha. Folha velha ela não publica, e aí
            * o único caminho honesto é digitar olhando a súmula. */}
          <p className="text-[10px] text-ink-4 mt-2 leading-relaxed">
            Toque em qualquer número acima para ver as partidas por trás dele, com os botões de
            Rodar e Preencher à mão. Recoletar resolve o caso em que a API ainda publica a folha;
            quando ela não publica (e folha velha ela não publica), digitar olhando a súmula é o
            único caminho que sobra · e o motor lê o número da mão igual ao coletado.
          </p>

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
                          onClick={() => dispararRecoleta()}>
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

      {/* Árbitros · a mesma régua dos times, com a amostra à vista.
        *
        * A média do árbitro tinha dois defeitos que só apareciam de dentro do
        * SQL: `games` contava a temporada inteira enquanto as médias saíam de
        * AVG (que ignora ausência), então os dois números vinham de conjuntos
        * diferentes; e não havia filtro de status. Os dois foram corrigidos no
        * coletor, que é onde a média nasce · aqui fica o que faltava, que é
        * enxergar a amostra e poder refazer a conta sem esperar o próximo jogo
        * daquele árbitro. Refazer não custa cota: sai tudo do banco. */}
      </>)}

      {secao === 'times' && (<>
      {/* Médias desatualizadas.
        *
        * `team_statistics` é o que o motor lê, e é DERIVADA de
        * `match_statistics`. Derivada não se atualiza sozinha: coletar a
        * partida e não refazer a média deixa o motor lendo a média de ontem
        * sobre um histórico de hoje · o pior dos dois mundos, porque parece
        * atualizado e não tem sintoma nenhum na tela.
        *
        * O cartão fica aqui e não em Problemas de propósito: média velha por
        * alguns minutos é o estado NORMAL entre a coleta e a próxima varredura,
        * e um alerta que acende todo dia deixa de ser alerta. Ele abre a aba
        * porque é o botão que conserta a coluna vazia da tabela de baixo. */}
      {medias?.disponivel && (
        <div className="card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-ink-1">Recalcular médias</h3>
              <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
                {medias.total > 0
                  ? <>
                      <span className="text-yellow-400 font-semibold">
                        {numero(medias.total)} time(s)
                      </span>{' '}
                      têm partida gravada depois da última vez que a média deles foi calculada ·
                      é essa média que o motor lê. Recalcular não gasta requisição da API: sai tudo
                      do banco.
                    </>
                  : <>Toda média está em dia com as partidas coletadas. O motor está lendo o
                      número de agora.</>}
              </p>
              <p className="text-[10px] text-ink-4 mt-1.5 leading-relaxed">
                Só entram os times que de fato mudaram · a varredura antiga refazia a conta de
                todo time que tivesse jogado nos últimos 3 dias, tivesse mudado alguma coisa nele
                ou não, e isso rodava no caminho de uma visita ao site.
              </p>
            </div>
            {medias.total > 0 && !medias.rodando && (
              <Button size="sm" variant="ghost" className="shrink-0"
                      loading={pedindoMedias} onClick={recalcularMedias}>
                <RefreshCw className="w-3.5 h-3.5" />
                Atualizar as {numero(medias.total)}
              </Button>
            )}
          </div>

          {medias.rodando && (
            <>
              <div className="flex items-baseline justify-between gap-3 mt-3">
                <p className="text-[11px] font-semibold text-ink-2">
                  Recalculando {medias.feitas} de {medias.total}
                </p>
                {medias.falhas > 0 && (
                  <p className="text-[10px] font-mono text-yellow-400">{medias.falhas} falha(s)</p>
                )}
              </div>
              <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden mt-2">
                <div
                  className="h-full bg-green-500 transition-all duration-1"
                  style={{ width: `${Math.round((medias.feitas / Math.max(1, medias.total)) * 100)}%` }}
                />
              </div>
              <p className="text-[10px] text-ink-4 mt-1.5">
                Dá pra sair da aba · o recálculo continua no servidor.
              </p>
            </>
          )}

          {!medias.rodando && medias.terminada_em && (
            <p className="text-[11px] text-green-400 mt-2">
              Último recálculo: {medias.feitas} time(s)
              {medias.falhas > 0 && ` · ${medias.falhas} falha(s)`}
            </p>
          )}
          {medias.erro && <p className="text-[11px] text-red-400 mt-2">{medias.erro}</p>}
          {aviso?.fixture === -5 && (
            <p className={`text-[11px] mt-2 ${aviso.ok ? 'text-green-400' : 'text-red-400'}`}>
              {aviso.texto}
            </p>
          )}
        </div>
      )}

      {/* A média de time, linha a linha · a tabela que faltava.
        *
        * `team_statistics` é O NÚMERO QUE O MOTOR LÊ pra todo mercado de time,
        * e era a única tabela grande do banco sem tela: dava pra ver a partida
        * (a matéria-prima), o árbitro e o jogador, mas não o agregado que fica
        * no meio do caminho. Sem ele, "a média está estranha" só se investigava
        * abrindo o banco.
        *
        * A lista nasce das PARTIDAS e não das médias, então o time que nunca
        * teve média calculada aparece com as colunas vazias em vez de sumir ·
        * ele é o caso mais desatualizado que existe. */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="flex items-center gap-2 text-sm font-bold text-ink-1">
                <Users className="w-4 h-4" />
                Médias de time{times?.season ? ` · temporada ${times.season}` : ''}
              </h3>
              <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
                É daqui que sai o baseline de escanteio, falta, cartão e chute de cada pick.
                A média é separada por mando porque o motor lê a do lado em que o time vai
                jogar · mandante e visitante produzem escanteio e falta em taxas diferentes,
                e a média misturada não descreve nenhum dos dois casos. Toque no time para
                ver os jogos que formaram o número.
              </p>
            </div>
            {!!times?.temporadas?.length && times.temporadas.length > 1 && (
              <select
                value={times.season ?? ''}
                onChange={e => buscarTimes({ season: Number(e.target.value), liga: ligaTimes,
                                             mando: mandoTimes, problema: problemaTimes,
                                             ordenar: ordenarTimes, busca: buscaTime })}
                className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] shrink-0 focus:border-ink-4 focus:outline-none"
                aria-label="Temporada dos times"
              >
                {times.temporadas.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 mt-2.5">
            <div className="flex gap-1">
              {([['todos', 'Casa e fora'], ['casa', 'Em casa'], ['fora', 'Fora']] as const)
                .map(([chave, rotulo]) => (
                  <button
                    key={chave}
                    type="button"
                    onClick={() => {
                      setMandoTimes(chave)
                      buscarTimes({ season: times?.season, liga: ligaTimes, mando: chave,
                                    problema: problemaTimes, ordenar: ordenarTimes,
                                    busca: buscaTime })
                    }}
                    className={`text-[11px] font-semibold px-2.5 py-1.5 min-h-[36px] rounded-md border transition-colors duration-1 ${
                      mandoTimes === chave
                        ? 'border-line-strong bg-surface-2 text-ink-1'
                        : 'border-line text-ink-3 hover:text-ink-2'}`}
                  >
                    {rotulo}
                  </button>
                ))}
            </div>

            {(times?.ligas?.length ?? 0) > 1 && (
              <select
                value={ligaTimes}
                onChange={e => {
                  const liga = e.target.value === '' ? '' : Number(e.target.value)
                  setLigaTimes(liga)
                  buscarTimes({ season: times?.season, liga, mando: mandoTimes,
                                problema: problemaTimes, ordenar: ordenarTimes, busca: buscaTime })
                }}
                className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] max-w-[12rem] focus:border-ink-4 focus:outline-none"
                aria-label="Competição"
              >
                <option value="">Todas as competições</option>
                {times?.ligas.map(l => (
                  <option key={l.league_id} value={l.league_id}>
                    {l.liga ?? `liga ${l.league_id}`} · {l.partidas}
                  </option>
                ))}
              </select>
            )}

            {!!times?.colunas?.length && (
              <select
                value={ordenarTimes}
                onChange={e => {
                  setOrdenarTimes(e.target.value)
                  buscarTimes({ season: times?.season, liga: ligaTimes, mando: mandoTimes,
                                problema: problemaTimes, ordenar: e.target.value, busca: buscaTime })
                }}
                className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
                aria-label="Ordenar por"
              >
                {times.colunas.map(c => (
                  <option key={c.chave} value={c.chave}>Maior média de {c.rotulo.toLowerCase()}</option>
                ))}
              </select>
            )}

            <input
              value={buscaTime}
              onChange={e => setBuscaTime(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  buscarTimes({ season: times?.season, liga: ligaTimes, mando: mandoTimes,
                                problema: problemaTimes, ordenar: ordenarTimes, busca: buscaTime })
                }
              }}
              onBlur={() => buscarTimes({ season: times?.season, liga: ligaTimes, mando: mandoTimes,
                                          problema: problemaTimes, ordenar: ordenarTimes,
                                          busca: buscaTime })}
              placeholder="Procurar time"
              aria-label="Procurar time pelo nome"
              className="flex-1 min-w-[8rem] bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
            />
          </div>

          {/* OS TRÊS DEFEITOS DA MÉDIA, cada um virando lista com um toque.
            *
            * O contador sozinho não dá pra agir · saber que há 40 médias velhas
            * não diz de quais times, e era exatamente isso que obrigava a abrir
            * o banco. Os números saem do MESMO recorte da tabela (temporada,
            * liga e busca), senão o chip contaria uma coisa e a lista mostraria
            * outra. */}
          {!!times && !times.erro && (
            <div className="flex flex-wrap gap-1.5 mt-2.5">
              {([
                ['', 'Todos', times.total],
                ['velha', 'Média velha', times.velhas],
                ['sem_media', 'Sem média', times.sem_media],
                ['curta', `Menos de ${times.min_jogos} jogos`, times.curtas],
              ] as const).map(([chave, rotulo, n]) => (
                <button
                  key={chave || 'todos'}
                  type="button"
                  onClick={() => {
                    setProblemaTimes(chave)
                    buscarTimes({ season: times.season, liga: ligaTimes, mando: mandoTimes,
                                  problema: chave, ordenar: ordenarTimes, busca: buscaTime })
                  }}
                  className={`flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 min-h-[32px] rounded-md border transition-colors duration-1 ${
                    problemaTimes === chave
                      ? 'border-line-strong bg-surface-2 text-ink-1'
                      : 'border-line text-ink-3 hover:text-ink-2'}`}
                >
                  {rotulo}
                  <span className={`font-mono tabular-nums ${
                    chave && n > 0 ? 'text-yellow-400' : 'text-ink-4'}`}>{numero(n)}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {times?.erro ? (
          <p className="px-4 py-6 text-[11px] text-red-400">{times.erro}</p>
        ) : !times ? (
          <SkeletonRows rows={6} />
        ) : !times.times.length ? (
          <EmptyState
            compact
            Icon={Users}
            title="Nenhum time neste recorte"
            description="Sem partida coletada para esta temporada, competição ou nome procurado."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs min-w-[44rem]">
                <thead>
                  <tr className="text-ink-4 text-[10px] border-b border-line">
                    <th className="text-left font-medium px-4 py-2">Time</th>
                    <th className="text-right font-medium px-2 py-2">Jogos</th>
                    {times.colunas.map(c => (
                      <th key={c.chave} className="text-right font-medium px-2 py-2 whitespace-nowrap">
                        {c.rotulo}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {times.times.map(t => (
                    <tr
                      key={`${t.team_id}-${t.league_id}`}
                      onClick={() => setAmostra({ tipo: 'time', teamId: t.team_id,
                                                  leagueId: t.league_id, season: t.season,
                                                  nome: t.time })}
                      className={`border-b border-line/60 cursor-pointer hover:bg-surface-2/60 transition-colors duration-1 ${
                        t.sem_media ? 'bg-red-500/5' : ''}`}
                    >
                      <td className="px-4 py-2.5 align-top">
                        <span className="text-ink-2 block truncate max-w-[11rem]">
                          {t.time ?? `time ${t.team_id}`}
                        </span>
                        <span className="text-[10px] text-ink-4 block truncate max-w-[11rem]">
                          {t.liga ?? 'liga ?'}
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-right align-top">
                        {/* "Jogos" é a amostra da MÉDIA, e `partidas` é o que o
                          * banco tem do time · quando os dois diferem, a média
                          * está vendo menos jogo do que existe. É o sintoma que
                          * some quando se olha só o número formatado. */}
                        <span className={`font-mono tabular-nums ${
                          t.sem_media ? 'text-red-400'
                            : t.amostra_curta ? 'text-yellow-400' : 'text-ink-2'}`}>
                          {t.jogos == null ? '·' : numero(t.jogos)}
                          <span className="text-ink-4">/{numero(t.partidas)}</span>
                        </span>
                        {t.sem_media ? (
                          <span className="block text-[10px] text-red-400">sem média</span>
                        ) : t.desatualizada ? (
                          <span className="block text-[10px] text-yellow-400">média velha</span>
                        ) : (
                          <span className="block text-[10px] text-ink-4">{diaMes(t.ultima_partida)}</span>
                        )}
                      </td>
                      {times.colunas.map(c => {
                        const media = t[`${c.chave}_m`] as number | string | null
                        return (
                          <td key={c.chave}
                              className="px-2 py-2.5 text-right font-mono tabular-nums align-top">
                            <span className={media == null ? 'text-ink-4' : 'text-ink-1'}>
                              {media == null ? '·' : decimal(Number(media))}
                            </span>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {times.total > POR_PAGINA && (
              <Pagination
                page={paginaTimes}
                pageSize={POR_PAGINA}
                total={times.total}
                unit="times"
                onChange={pag => buscarTimes({ season: times.season, liga: ligaTimes,
                                               mando: mandoTimes, problema: problemaTimes,
                                               ordenar: ordenarTimes, busca: buscaTime,
                                               pagina: pag })}
              />
            )}
          </>
        )}
      </div>

      </>)}

      {secao === 'partidas' && (<>

      {/* Partida a partida · o que o motor leu, e o que veio vazio na linha. */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <h3 className="text-sm font-bold text-ink-1">
            {filtroPartidas ? `Partidas sem ${filtroPartidas.rotulo}` : 'Últimas partidas coletadas'}
          </h3>
          {filtroPartidas ? (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="text-[11px] text-ink-4 leading-relaxed">
                As {numero(historico?.total)} partidas dos últimos {historico?.meses ?? 24} meses
                que estão sem esse número, da mais recente pra mais antiga. Aqui o teto de{' '}
                {historico?.teto ?? 40} não vale · ele existe pra lista sem filtro, e manteria
                escondida justamente a partida antiga que precisa de conserto.
              </p>
              <button
                type="button"
                onClick={limparFiltro}
                className="text-[11px] font-semibold text-ink-2 underline underline-offset-4 hover:text-ink-1"
              >
                limpar o filtro
              </button>
            </div>
          ) : (
          <p className="text-[11px] text-ink-4 mt-0.5">
            As {historico?.teto ?? 40} mais recentes que entraram em{' '}
            <span className="font-mono">match_statistics</span>. Toque na partida para ver as{' '}
            {historico?.familias ?? 16} estatísticas que o banco tem dela, coletar de novo ou
            preencher o que faltou.
          </p>
          )}

          {/* OS DOIS BURACOS, na própria aba onde estão os botões de conserto.
            *
            * O servidor já aceitava os dois recortes, mas a única entrada pra
            * eles era o diagnóstico, na aba de Cobertura · quem queria "as
            * partidas que a API não trouxe estatística" tinha que sair daqui,
            * achar o cartão certo e voltar. Ligar o filtro amplia a janela das
            * 40 últimas pros últimos meses, que é onde a partida velha mora. */}
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            {([
              ['', 'Últimas coletadas'],
              ['folha_incompleta', 'Falta estatística'],
              ['zeradas', 'Coletada zerada'],
            ] as const).map(([chave, rotulo]) => (
              <button
                key={chave || 'todas'}
                type="button"
                onClick={() => (chave ? abrirFiltro(chave, rotulo.toLowerCase()) : limparFiltro())}
                className={`text-[11px] font-semibold px-2.5 py-1.5 min-h-[32px] rounded-md border transition-colors duration-1 ${
                  (filtroPartidas?.chave ?? '') === chave
                    ? 'border-line-strong bg-surface-2 text-ink-1'
                    : 'border-line text-ink-3 hover:text-ink-2'}`}
              >
                {rotulo}
              </button>
            ))}
          </div>

          {/* RODAR EM TODAS · o que faltava pra esta tela deixar de ser manual.
            *
            * Rodar e Preencher à mão são individuais por natureza, e isso está
            * certo pra folha que a API não publica mais -- digitar olhando a
            * súmula não tem versão em lote. Mas o caso comum não é esse: é
            * partida recente cuja folha a API TEM e a coleta perdeu, e aí
            * clicar 45 vezes no mesmo botão não é cuidado, é trabalho braçal.
            *
            * O lote daqui ataca EXATAMENTE o filtro em cima, na janela do
            * diagnóstico · o do bloco de Cobertura continua existindo pro
            * recorte fixo de "mais recentes furadas". O que sobrar depois dele
            * é justamente o que só a mão resolve, e aí a lista fica com o
            * tamanho real do trabalho manual em vez de escondê-lo. */}
          {filtroPartidas && (
            <div className="mt-2.5 border-t border-line/60 pt-2.5">
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
                      aria-label="Quantas partidas deste filtro recoletar"
                    >
                      {[10, 20, 50, 100].map(n => (
                        <option key={n} value={n}>{n} partidas · {n * 2} requisições</option>
                      ))}
                    </select>
                    <Button size="sm" loading={pedindoLote}
                            onClick={() => dispararRecoleta(filtroPartidas.chave)}>
                      <PlayCircle className="w-3.5 h-3.5" />
                      Rodar nestas {Math.min(lote, historico?.total ?? lote)}
                    </Button>
                  </div>
                  <p className="text-[10px] text-ink-4 mt-2 leading-relaxed">
                    Roda a coleta nas {Math.min(lote, historico?.total ?? lote)} partidas mais
                    recentes <span className="font-semibold">deste filtro</span>, da janela de{' '}
                    {diagnostico?.meses ?? 12} meses · é o botão Rodar de cada linha, aplicado à
                    lista. Quem continuar sem o número depois é folha que a API não publica mais:
                    essa só sai preenchendo à mão.
                  </p>
                  {aviso?.fixture === -2 && (
                    <p className={`text-[11px] mt-1.5 ${aviso.ok ? 'text-green-400' : 'text-red-400'}`}>
                      {aviso.texto}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
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
            title={filtroPartidas ? 'Nenhuma partida neste filtro' : 'Nenhuma partida coletada'}
            description={filtroPartidas
              ? `Nenhuma partida dos últimos ${historico?.meses ?? 24} meses está sem ${filtroPartidas.rotulo}. O buraco pode ser mais antigo que a janela do diagnóstico.`
              : 'Sem linha em match_statistics não há baseline de liga, média de time nem confronto direto.'}
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
                              {/* A média que o motor lê não é a desta partida ·
                                * é a do time na temporada. Daqui se vê quais
                                * jogos formaram esse número. */}
                              <Button size="sm" variant="ghost"
                                      onClick={() => abrirAmostraDaPartida(p.fixture_id, 'casa')}>
                                <Users className="w-3.5 h-3.5" />
                                Amostra do mandante
                              </Button>
                              <Button size="sm" variant="ghost"
                                      onClick={() => abrirAmostraDaPartida(p.fixture_id, 'fora')}>
                                <Users className="w-3.5 h-3.5" />
                                Amostra do visitante
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

      </>)}

      {secao === 'pessoas' && (<>

      {/* Árbitros. Renderiza mesmo com a página vazia desde 27/08: com busca e
        * paginação, lista vazia é resultado de filtro, não ausência de dado ·
        * sumir com o card inteiro esconderia o campo de busca junto e prenderia
        * quem digitou errado. */}
      {!!arbitros && !!(arbitros.total ?? arbitros.arbitros.length) && (
        <div className="card p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-line flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h3 className="flex items-center gap-2 text-sm font-bold text-ink-1">
                <Gavel className="w-4 h-4" />
                Árbitros · temporada {arbitros.season}
              </h3>
              <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
                "Com folha" é a amostra que sustenta a média de cartões · é esse número que o
                motor lê pra liberar o mercado. Abaixo de {arbitros.amostra_minima ?? 3} ele cai
                no fallback da média da liga. Toque no árbitro para ver os jogos.
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {arbitros.temporadas?.length > 1 && (
                <select
                  value={arbitros.season ?? ''}
                  onChange={e => buscarArbitros(Number(e.target.value), 0, buscaArbitro)}
                  className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
                  aria-label="Temporada dos árbitros"
                >
                  {arbitros.temporadas.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              )}
              {/* Procurar pelo nome é o que faz a paginação não atrapalhar:
                * o árbitro que interessa quase nunca está na primeira página,
                * e sem busca paginar só troca rolagem por clique. */}
              <input
                value={buscaArbitro}
                onChange={e => setBuscaArbitro(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') buscarArbitros(arbitros.season, 0, buscaArbitro)
                }}
                onBlur={() => buscarArbitros(arbitros.season, 0, buscaArbitro)}
                placeholder="Procurar árbitro"
                aria-label="Procurar árbitro pelo nome"
                className="w-32 sm:w-40 bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
              />
              <Button size="sm" variant="ghost" loading={recalculandoArbitros}
                      onClick={recalcularArbitros}>
                <RefreshCw className="w-3.5 h-3.5" />
                Recalcular
              </Button>
            </div>
          </div>

          {aviso?.fixture === -3 && (
            <p className={`px-4 py-2 text-[11px] ${aviso.ok ? 'text-green-400' : 'text-red-400'}`}>
              {aviso.texto}
            </p>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[30rem]">
              <thead>
                <tr className="text-ink-4 text-[10px] border-b border-line">
                  <th className="text-left font-medium px-4 py-2">Árbitro</th>
                  <th className="text-right font-medium px-2 py-2">Com folha</th>
                  <th className="text-right font-medium px-2 py-2">Amarelos</th>
                  <th className="text-right font-medium px-2 py-2">Vermelhos</th>
                  <th className="text-right font-medium px-4 py-2">Faltas</th>
                </tr>
              </thead>
              <tbody>
                {arbitros.arbitros.map(a => {
                  const curto = (a.games ?? 0) < (arbitros.amostra_minima ?? 3)
                  const faltando = a.games_total != null && a.games != null
                    && a.games_total > a.games
                  return (
                    <tr
                      key={a.referee_id}
                      onClick={() => setAmostra({ tipo: 'arbitro', refereeId: a.referee_id,
                                                  season: arbitros.season, nome: a.name })}
                      className="border-b border-line/60 cursor-pointer hover:bg-surface-2/60 transition-colors duration-1"
                    >
                      <td className="px-4 py-2.5 text-ink-2 truncate max-w-[12rem]">{a.name}</td>
                      <td className={`px-2 py-2.5 text-right font-mono tabular-nums ${
                        curto ? 'text-yellow-400' : 'text-ink-2'}`}>
                        {a.games ?? '·'}
                        {faltando && <span className="text-ink-4">/{a.games_total}</span>}
                      </td>
                      <td className="px-2 py-2.5 text-right font-mono tabular-nums text-ink-1">
                        {decimal(a.avg_yellow == null ? null : Number(a.avg_yellow))}
                      </td>
                      <td className="px-2 py-2.5 text-right font-mono tabular-nums text-ink-3">
                        {decimal(a.avg_red == null ? null : Number(a.avg_red))}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums text-ink-3">
                        {decimal(a.avg_fouls == null ? null : Number(a.avg_fouls))}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {!arbitros.arbitros.length && (
            <p className="px-4 py-6 text-[11px] text-ink-4">
              Nenhum árbitro com esse nome nesta temporada.
            </p>
          )}

          {(arbitros.total ?? 0) > POR_PAGINA && (
            <Pagination
              page={paginaArbitros}
              pageSize={POR_PAGINA}
              total={arbitros.total ?? 0}
              unit="árbitros"
              onChange={pag => buscarArbitros(arbitros.season, pag, buscaArbitro)}
            />
          )}
        </div>
      )}

      {/* Jogadores · a mesma régua dos times e dos árbitros, aplicada ao
        * indivíduo.
        *
        * `player_match_stats` existe desde 01/08 e alimenta o Player Stats
        * (chutes, chutes no alvo, faltas, desarmes, passes e defesas), mas
        * nenhuma tela mostrava o que há dentro dela · conferir a média de um
        * jogador exigia abrir o banco.
        *
        * O MANDO É O RECORTE, e não enfeite: o próprio motor separa casa de
        * fora ao ler o volume do adversário, com a justificativa de que a média
        * misturada não descreve nem um caso nem o outro. Vale igual aqui. */}
      {!!jogadores && !jogadores.erro && (
        <div className="card p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-line">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="flex items-center gap-2 text-sm font-bold text-ink-1">
                  <User className="w-4 h-4" />
                  Jogadores · temporada {jogadores.season}
                </h3>
                <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
                  Média por atuação de cada contador que vira mercado. Só entram atuações de{' '}
                  {jogadores.min_minutos} minutos ou mais, que é o corte do motor · entrada de
                  doze minutos e jogo inteiro não são a mesma observação, e misturar as duas
                  derruba toda média. Sem filtro de competição, o jogador que atuou em duas na
                  mesma temporada aparece com as duas somadas, e a linha vem marcada em amarelo.
                  Toque no jogador para ver as atuações.
                </p>
              </div>
              {jogadores.temporadas?.length > 1 && (
                <select
                  value={jogadores.season ?? ''}
                  onChange={e => buscarJogadores(Number(e.target.value), mandoJogadores,
                                                 ordenarJogadores, 0, buscaJogador, ligaJogadores)}
                  className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] shrink-0 focus:border-ink-4 focus:outline-none"
                  aria-label="Temporada dos jogadores"
                >
                  {jogadores.temporadas.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2 mt-2.5">
              {/* Mando. Três botões e não um select: é o filtro que muda a
                * leitura da tabela inteira, então ele fica sempre à vista. */}
              <div className="flex gap-1">
                {([['todos', 'Casa e fora'], ['casa', 'Em casa'], ['fora', 'Fora']] as const)
                  .map(([chave, rotulo]) => (
                    <button
                      key={chave}
                      type="button"
                      onClick={() => {
                        setMandoJogadores(chave)
                        buscarJogadores(jogadores.season, chave, ordenarJogadores, 0, buscaJogador, ligaJogadores)
                      }}
                      className={`text-[11px] font-semibold px-2.5 py-1.5 min-h-[36px] rounded-md border transition-colors duration-1 ${
                        mandoJogadores === chave
                          ? 'border-line-strong bg-surface-2 text-ink-1'
                          : 'border-line text-ink-3 hover:text-ink-2'}`}
                    >
                      {rotulo}
                    </button>
                  ))}
              </div>

              {/* Competição. É a "estatística separada" · sem ela, a única
                * saída seria confiar na marca de linha misturada, que avisa mas
                * não conserta o número. */}
              {jogadores.ligas.length > 1 && (
                <select
                  value={ligaJogadores}
                  onChange={e => {
                    const liga = e.target.value === '' ? '' : Number(e.target.value)
                    setLigaJogadores(liga)
                    buscarJogadores(jogadores.season, mandoJogadores, ordenarJogadores,
                                    0, buscaJogador, liga)
                  }}
                  className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] max-w-[12rem] focus:border-ink-4 focus:outline-none"
                  aria-label="Competição"
                >
                  <option value="">Todas as competições</option>
                  {jogadores.ligas.map(l => (
                    <option key={l.league_id} value={l.league_id}>
                      {l.liga ?? `liga ${l.league_id}`} · {l.atuacoes}
                    </option>
                  ))}
                </select>
              )}

              <select
                value={ordenarJogadores}
                onChange={e => {
                  setOrdenarJogadores(e.target.value)
                  buscarJogadores(jogadores.season, mandoJogadores, e.target.value, 0, buscaJogador, ligaJogadores)
                }}
                className="bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
                aria-label="Ordenar por"
              >
                {jogadores.colunas.map(c => (
                  <option key={c.chave} value={c.chave}>Maior média de {c.rotulo.toLowerCase()}</option>
                ))}
              </select>

              <input
                value={buscaJogador}
                onChange={e => setBuscaJogador(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    buscarJogadores(jogadores.season, mandoJogadores, ordenarJogadores, 0, buscaJogador, ligaJogadores)
                  }
                }}
                onBlur={() => buscarJogadores(jogadores.season, mandoJogadores,
                                              ordenarJogadores, 0, buscaJogador, ligaJogadores)}
                placeholder="Procurar jogador ou time"
                aria-label="Procurar jogador ou time"
                className="flex-1 min-w-[8rem] bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[44rem]">
              <thead>
                <tr className="text-ink-4 text-[10px] border-b border-line">
                  <th className="text-left font-medium px-4 py-2">Jogador</th>
                  <th className="text-right font-medium px-2 py-2">Atuações</th>
                  {jogadores.colunas.map(c => (
                    <th key={c.chave} className="text-right font-medium px-2 py-2 whitespace-nowrap">
                      {c.rotulo}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {jogadores.jogadores.map(j => (
                  <tr
                    key={j.player_id}
                    onClick={() => setAmostra({
                      tipo: 'jogador', playerId: j.player_id, season: jogadores.season,
                      nome: j.nome, mando: mandoJogadores,
                      // O recorte viaja junto: abrir a amostra "de todas as
                      // competições" a partir de uma tabela já filtrada daria
                      // dois números diferentes na mesma tela.
                      leagueId: ligaJogadores === '' ? null : ligaJogadores,
                    })}
                    className="border-b border-line/60 cursor-pointer hover:bg-surface-2/60 transition-colors duration-1"
                  >
                    <td className="px-4 py-2.5">
                      <span className="text-ink-2 block truncate max-w-[11rem]">{j.nome ?? '·'}</span>
                      <span className="text-[10px] text-ink-4 block truncate max-w-[11rem]">
                        {j.time ?? 'time ?'}{j.posicao ? ` · ${j.posicao}` : ''}
                      </span>
                    </td>
                    <td className="px-2 py-2.5 text-right font-mono tabular-nums text-ink-2 align-top">
                      {numero(j.atuacoes)}
                      {/* A linha que soma duas competições. Amarelo porque ela
                        * não está errada, está DESCREVENDO OUTRA COISA: é média
                        * de duas populações, e não serve pra nenhuma das duas.
                        * O seletor acima separa. */}
                      {((j.competicoes as number | null) ?? 1) > 1 ? (
                        <span className="block text-[10px] text-yellow-400">
                          {String(j.competicoes)} competições
                        </span>
                      ) : j.minutos != null && (
                        <span className="block text-[10px] text-ink-4">{Number(j.minutos)}min</span>
                      )}
                    </td>
                    {jogadores.colunas.map(c => {
                      const media = j[`${c.chave}_m`] as number | string | null
                      const n = (j[`${c.chave}_n`] as number | null) ?? 0
                      // A contagem POR COLUNA fica ao lado quando ela é menor
                      // que o total de atuações · é a diferença entre "média de
                      // 12 jogos" e "média de 2 dentro de 12", e sem ela defesa
                      // de goleiro parece ter a mesma amostra que passe.
                      const parcial = n > 0 && n < j.atuacoes
                      return (
                        <td key={c.chave}
                            className="px-2 py-2.5 text-right font-mono tabular-nums align-top">
                          <span className={n === 0 ? 'text-ink-4' : 'text-ink-1'}>
                            {media == null ? '·' : decimal(Number(media))}
                          </span>
                          {parcial && (
                            <span className="block text-[10px] text-yellow-400">de {n}</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!jogadores.jogadores.length && (
            <EmptyState
              compact
              Icon={User}
              title="Nenhum jogador neste recorte"
              description="Sem atuação coletada acima do corte de minutos para esta temporada e mando."
            />
          )}

          {jogadores.total > POR_PAGINA && (
            <Pagination
              page={paginaJogadores}
              pageSize={POR_PAGINA}
              total={jogadores.total}
              unit="jogadores"
              onChange={pag => buscarJogadores(jogadores.season, mandoJogadores,
                                               ordenarJogadores, pag, buscaJogador, ligaJogadores)}
            />
          )}
        </div>
      )}

      </>)}

      {amostra && <AdminAmostra alvo={amostra} onClose={() => setAmostra(null)} />}
    </div>
  )
}
