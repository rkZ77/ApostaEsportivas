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
 *
 * `pt` (2026-10-07, pedido do usuário) é o nome que o torcedor brasileiro
 * reconhece. O gravado vem do provedor em inglês, e "Serie A" é tanto o
 * Brasileirão quanto o Italiano · no cabeçalho de um jogo isso não diz nada.
 */
export interface PaisDaLiga {
  pais: string
  bandeira: string | null
  nome?: string
  pt?: string
}

export const PAIS_DA_LIGA: Record<number, PaisDaLiga> = {
  1:   { pais: 'Mundo',          bandeira: null, pt: 'Copa do Mundo' },
  2:   { pais: 'Europa',         bandeira: 'eu', pt: 'Champions League' },
  3:   { pais: 'Europa',         bandeira: 'eu', pt: 'Europa League' },
  11:  { pais: 'América do Sul', bandeira: null, pt: 'Copa Sul-Americana' },
  13:  { pais: 'América do Sul', bandeira: null, pt: 'Copa Libertadores' },
  39:  { pais: 'Inglaterra',     bandeira: 'gb-eng', pt: 'Premier League' },
  40:  { pais: 'Inglaterra',     bandeira: 'gb-eng', pt: 'Championship' },
  61:  { pais: 'França',         bandeira: 'fr', pt: 'Ligue 1' },
  71:  { pais: 'Brasil',         bandeira: 'br', pt: 'Brasileirão Série A' },
  72:  { pais: 'Brasil',         bandeira: 'br', pt: 'Brasileirão Série B' },
  73:  { pais: 'Brasil',         bandeira: 'br', pt: 'Copa do Brasil' },
  78:  { pais: 'Alemanha',       bandeira: 'de', pt: 'Bundesliga' },
  79:  { pais: 'Alemanha',       bandeira: 'de', pt: '2. Bundesliga' },
  88:  { pais: 'Holanda',        bandeira: 'nl', pt: 'Eredivisie' },
  94:  { pais: 'Portugal',       bandeira: 'pt', pt: 'Liga Portugal' },
  128: { pais: 'Argentina',      bandeira: 'ar', pt: 'Campeonato Argentino' },
  135: { pais: 'Itália',         bandeira: 'it', pt: 'Campeonato Italiano' },
  140: { pais: 'Espanha',        bandeira: 'es', pt: 'La Liga' },
  203: { pais: 'Turquia',        bandeira: 'tr', pt: 'Campeonato Turco' },
  239: { pais: 'Colômbia',       bandeira: 'co', nome: 'Primera A', pt: 'Campeonato Colombiano' },
  253: { pais: 'Estados Unidos', bandeira: 'us', pt: 'MLS' },
  307: { pais: 'Arábia Saudita', bandeira: 'sa', nome: 'Saudi Pro League', pt: 'Saudi Pro League' },
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

/** O nome em português quando a liga é conhecida; senão o mesmo de `nomeDaLiga`. */
export function nomeDaLigaPt(id: number | null | undefined, gravado?: string | null): string {
  return paisDaLiga(id)?.pt ?? nomeDaLiga(id, gravado)
}

/*
 * RODADA EM PORTUGUÊS (2026-10-07).
 *
 * O provedor manda a fase como texto livre em inglês ("Regular Season - 29",
 * "Round of 16 - 1st Leg", "Group A - 3"). Cada forma conhecida vira a frase
 * do torcedor; forma desconhecida volta como veio, que é melhor do que sumir.
 */
const FASES: Array<[RegExp, string]> = [
  [/^regular season$/i, 'Rodada'],
  [/^league stage$/i, 'Fase de liga'],
  [/^group stage$/i, 'Fase de grupos'],
  [/^group ([a-z])$/i, 'Grupo $1'],
  [/^round of 64$/i, '32-avos de final'],
  [/^round of 32$/i, '16-avos de final'],
  [/^round of 16$/i, 'Oitavas de final'],
  [/^8th finals$/i, 'Oitavas de final'],
  [/^quarter-?finals?$/i, 'Quartas de final'],
  [/^semi-?finals?$/i, 'Semifinal'],
  [/^3rd place final$/i, 'Disputa do 3º lugar'],
  [/^final$/i, 'Final'],
  [/^knockout round play-?offs$/i, 'Playoff das oitavas'],
  [/^play-?offs?$/i, 'Playoffs'],
  [/^preliminary round$/i, 'Fase preliminar'],
  [/^(\d)(st|nd|rd|th) qualifying round$/i, '$1ª fase de qualificação'],
  [/^(\d)(st|nd|rd|th) round$/i, '$1ª fase'],
  [/^(\d)(st|nd|rd|th) phase$/i, '$1ª fase'],
  [/^apertura$/i, 'Apertura'],
  [/^clausura$/i, 'Clausura'],
]

export function rotuloDaRodada(bruto?: string | null): string {
  if (!bruto) return ''
  let texto = bruto.trim()
  let perna = ''
  const mPerna = texto.match(/\s*-\s*(1st|2nd) leg$/i)
  if (mPerna) {
    perna = mPerna[1].toLowerCase() === '1st' ? ' · Ida' : ' · Volta'
    texto = texto.slice(0, mPerna.index)
  }
  // "Regular Season - 29" · a fase e o número da rodada
  const mNum = texto.match(/^(.*?)\s*-\s*(\d+)$/)
  const fase = mNum ? mNum[1] : texto
  const numero = mNum ? mNum[2] : null
  const regra = FASES.find(([re]) => re.test(fase))
  if (!regra) return bruto
  const nomeFase = fase.replace(regra[0], regra[1])
  if (numero == null) return nomeFase + perna
  // Pontos corridos: "Rodada 29". Fase com rodadas dentro: "Grupo A · Rodada 3".
  return (nomeFase === 'Rodada' ? `Rodada ${numero}` : `${nomeFase} · Rodada ${numero}`) + perna
}
