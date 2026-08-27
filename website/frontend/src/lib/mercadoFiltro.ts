/*
 * Regras de filtragem da aba Mercados.
 *
 * Só a lógica mora aqui. Os CONTROLES eram próprios deste arquivo (busca
 * inline, três filas de pill, um select de ordenação) e faziam a aba parecer
 * outra ferramenta dentro da mesma página · a aba VIP, logo acima, filtrava
 * com o painel dobrável. Agora as duas usam components/FilterPanel, e este
 * módulo virou o que ele sempre deveria ter sido: as regras, sem casca.
 *
 * A filtragem é client-side de propósito: a aba já recebe os dois conjuntos
 * inteiros junto com o resto do dia (são poucas dezenas de picks), então
 * filtrar no servidor só somaria ida e volta.
 */

/* `goleiros` continua aqui e não vai sair: o motor parou de escrever nela em
   27/08 (defesas virou o método `saves` do Player Stats), mas os picks antigos
   continuam no banco e no placar público · tirar a categoria esconderia o
   histórico do produto. O que a tela faz é só não desenhar a seção nos dias em
   que ela vem vazia, que hoje são todos. */
export type MercadoCategoria = 'todos' | 'faltas' | 'goleiros' | 'player_stats'
export type MercadoOrdem = 'margem' | 'odd' | 'data'
export type MercadoEstado = 'todos' | 'pendentes' | 'resolvidos'

export interface Filtravel {
  home_team: string
  away_team: string
  player_name?: string
  team_name?: string
  market: string
  line: string
  odd: number
  edge?: number
  match_date: string
  result?: string | null
  /* Player Stats ordena por `score` (0-100) e não por edge · nele a odd é
     faixa de sanidade, não critério, então "maior margem" tem que cair no
     Score quando ele existe. Ver services/player_stats_engine/config.py. */
  score?: number | null
}

export interface MercadoFiltro {
  busca: string
  categoria: MercadoCategoria
  ordem: MercadoOrdem
  estado: MercadoEstado
}

export const FILTRO_INICIAL: MercadoFiltro = {
  busca: '', categoria: 'todos', ordem: 'margem', estado: 'todos',
}

/** Normaliza pra busca tolerar acento: "sao paulo" acha "São Paulo".
    O intervalo vai escrito como escape (\u0300-\u036f, os diacríticos
    combinantes) e não como caractere literal: literal aqui é invisível no
    editor e não sobrevive a uma conversão de encoding. */
const norm = (s: string) =>
  s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

export function aplicarFiltro<T extends Filtravel>(
  picks: T[],
  f: MercadoFiltro,
): T[] {
  let out = picks


  if (f.busca.trim()) {
    const q = norm(f.busca.trim())
    out = out.filter(p =>
      [p.home_team, p.away_team, p.player_name, p.team_name, p.market, p.line]
        .filter(Boolean)
        .some(v => norm(String(v)).includes(q)),
    )
  }

  if (f.estado === 'pendentes')  out = out.filter(p => !p.result)
  if (f.estado === 'resolvidos') out = out.filter(p => !!p.result)

  // Cópia antes de ordenar: sort muta, e o array vem direto do state.
  return [...out].sort((a, b) => {
    if (f.ordem === 'odd')  return Number(b.odd) - Number(a.odd)
    if (f.ordem === 'data') return a.match_date.localeCompare(b.match_date)
    // Score primeiro quando os dois têm · comparar o Score de um com o edge
    // do outro ordenaria por duas réguas diferentes na mesma lista.
    if (a.score != null && b.score != null) return Number(b.score) - Number(a.score)
    return (Number(b.edge ?? 0)) - (Number(a.edge ?? 0))
  })
}
