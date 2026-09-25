/*
 * PAÍS DE CADA LIGA (2026-09-25, pedido do usuário).
 *
 * A tabela `leagues` guarda id, nome e temporada, e não o país. A API-Football
 * manda país e bandeira junto com cada jogo, mas só na hora de buscar jogos ·
 * as listas de liga do site (Por Liga, Performance, Palpites, a fita da Home)
 * leem do histórico de picks, onde o país nunca foi gravado.
 *
 * Como a cobertura é curta e muda devagar, o mapa mora aqui, pelo id da
 * API-Football. Liga fora do mapa aparece como antes, só sem bandeira.
 *
 * `bandeira` é o código da flagcdn (ISO 3166, com `gb-eng` para a Inglaterra).
 * `null` é competição de mais de um país: aparece um globo no lugar.
 *
 * `nome` só entra quando o nome gravado não serve: o pipeline de alavancagem
 * grava "Liga <id>" quando a liga não está em `leagues`, e "Pro League" sozinho
 * também é o nome da liga da Bélgica.
 */
export interface PaisDaLiga {
  pais: string
  bandeira: string | null
  nome?: string
}

export const PAIS_DA_LIGA: Record<number, PaisDaLiga> = {
  1:   { pais: 'Mundo',          bandeira: null },
  2:   { pais: 'Europa',         bandeira: 'eu' },
  3:   { pais: 'Europa',         bandeira: 'eu' },
  11:  { pais: 'América do Sul', bandeira: null },
  13:  { pais: 'América do Sul', bandeira: null },
  39:  { pais: 'Inglaterra',     bandeira: 'gb-eng' },
  40:  { pais: 'Inglaterra',     bandeira: 'gb-eng' },
  61:  { pais: 'França',         bandeira: 'fr' },
  71:  { pais: 'Brasil',         bandeira: 'br' },
  72:  { pais: 'Brasil',         bandeira: 'br' },
  73:  { pais: 'Brasil',         bandeira: 'br' },
  78:  { pais: 'Alemanha',       bandeira: 'de' },
  79:  { pais: 'Alemanha',       bandeira: 'de' },
  88:  { pais: 'Holanda',        bandeira: 'nl' },
  94:  { pais: 'Portugal',       bandeira: 'pt' },
  128: { pais: 'Argentina',      bandeira: 'ar' },
  135: { pais: 'Itália',         bandeira: 'it' },
  140: { pais: 'Espanha',        bandeira: 'es' },
  203: { pais: 'Turquia',        bandeira: 'tr' },
  239: { pais: 'Colômbia',       bandeira: 'co', nome: 'Primera A' },
  253: { pais: 'Estados Unidos', bandeira: 'us' },
  307: { pais: 'Arábia Saudita', bandeira: 'sa', nome: 'Saudi Pro League' },
}

export function paisDaLiga(id?: number | null): PaisDaLiga | null {
  return id != null ? PAIS_DA_LIGA[id] ?? null : null
}

/** Nome pra tela: o gravado, a não ser que seja "Liga 239" ou ambíguo (ver acima). */
export function nomeDaLiga(id: number | null | undefined, gravado?: string | null): string {
  const p = paisDaLiga(id)
  if (p?.nome && (!gravado || /^Liga \d+$/.test(gravado) || gravado === 'Pro League')) return p.nome
  return gravado || (id != null ? `Liga ${id}` : '')
}
