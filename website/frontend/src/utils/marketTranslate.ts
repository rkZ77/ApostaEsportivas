const MARKET_PT: Record<string, string> = {
  'match winner': 'Resultado Final (1X2)',
  'double chance': 'Dupla Chance',
  'double chance - 1st half': 'Dupla Chance - 1º Tempo',
  'first half winner': 'Vencedor do 1º Tempo',
  'asian handicap': 'Handicap Asiático',
  'cards asian handicap': 'Cartões Handicap Asiático',
  'cards european handicap': 'Cartões Handicap Asiático',
  'corners asian handicap': 'Escanteios Handicap Asiático',
  'corners european handicap': 'Escanteios Handicap Asiático',
  'both teams score': 'Ambas as Equipes Marcam',
  'both teams to score': 'Ambas as Equipes Marcam',
  'both teams score - first half': 'Ambas Marcam - 1º Tempo',
  'both teams to score - first half': 'Ambas Marcam - 1º Tempo',
  'both teams score first half': 'Ambas Marcam - 1º Tempo',
  'goals over/under': 'Gols Mais/Menos',
  'total goals': 'Gols Mais/Menos',
  'over/under': 'Gols Mais/Menos',
  'goals over/under first half': 'Gols Mais/Menos - 1º Tempo',
  'goals over/under - first half': 'Gols Mais/Menos - 1º Tempo',
  'goals over/under 1st half': 'Gols Mais/Menos - 1º Tempo',
  'goals over/under - second half': 'Gols Mais/Menos - 2º Tempo',
  'goals over/under second half': 'Gols Mais/Menos - 2º Tempo',
  'goals over/under 2nd half': 'Gols Mais/Menos - 2º Tempo',
  'total - home': 'Total de Gols Casa',
  'total - away': 'Total de Gols Visitante',
  'home team total goals': 'Total de Gols Casa',
  'away team total goals': 'Total de Gols Visitante',
  'home team total goals - 1st half': 'Total de Gols Casa (1º Tempo)',
  'away team total goals - 1st half': 'Total de Gols Visitante (1º Tempo)',
  'corners over under': 'Escanteios Mais/Menos',
  'corners over/under': 'Escanteios Mais/Menos',
  'total corners': 'Escanteios Mais/Menos',
  'corners 1x2': 'Escanteios 1x2',
  'home corners over/under': 'Escanteios Casa Mais/Menos',
  'away corners over/under': 'Escanteios Visitante Mais/Menos',
  'total corners (1st half)': 'Escanteios (1º Tempo)',
  'corners over/under - 1st half': 'Escanteios (1º Tempo)',
  'total corners (2nd half)': 'Escanteios (2º Tempo)',
  'corners over/under - 2nd half': 'Escanteios (2º Tempo)',
  'cards over/under': 'Cartões Mais/Menos',
  'home team total cards': 'Cartões Casa',
  'away team total cards': 'Cartões Visitante',
  'home team cards': 'Cartões Casa',
  'away team cards': 'Cartões Visitante',
  'ht/ft': 'Inter./Final',
  'exact score': 'Placar Exato',
  'correct score': 'Placar Exato',
  'first goal scorer': 'Primeiro Gol',
  'anytime goalscorer': 'Marcar a Qualquer Tempo',
  'result': 'Resultado',
  'home/away': '1X2',
  // "Odd/Even" nao tinha traducao nenhuma -- ia cru pro site em ingles, e
  // "Odd" (impar) colide visualmente com "odd" em portugues (coeficiente
  // da aposta), confundindo o usuario ("Odd/Even Odd @ 2.02").
  'odd/even': 'Par/Ímpar',
  'odd or even': 'Par/Ímpar',
  'corners odd/even': 'Escanteios Par/Ímpar',
  // Faltas -- nome cru da API vem "Fouls. Home/Away/[nada] Total".
  'fouls. home total': 'Faltas Casa Mais/Menos',
  'fouls. away total': 'Faltas Visitante Mais/Menos',
  'fouls. total': 'Faltas Mais/Menos',
  'fouls': 'Faltas Mais/Menos',
  // Defesas de goleiro (bet_id 267) -- prop de JOGADOR, nao over/under de
  // time: a linha ja vem com o nome do goleiro ("Fabio · 3 ou mais defesas").
  'goalkeeper saves': 'Defesas do goleiro',
  'player saves': 'Defesas do goleiro',
  'saves': 'Defesas do goleiro',
  'to qualify': 'Classificação',
  'to qualify - extra time': 'Classificação (Prorrogação)',
}

export function translateMarket(m?: string): string {
  if (!m) return ''
  const key = m.trim().toLowerCase()
  if (MARKET_PT[key]) return MARKET_PT[key]
  for (const [k, v] of Object.entries(MARKET_PT)) {
    if (key.includes(k)) return v
  }
  return m
}

// Explicação curta de quando a aposta dá GREEN, em português simples. Ordem
// dos campos importa: entradas mais específicas (escanteios, cartões, times
// isolados) vêm antes das genéricas de gols/over-under, senão o match por
// substring (ex.: "corners over/under" contém "over/under") acertaria a
// explicação errada primeiro.
type OverUnderInfo = { dir: 'maior' | 'menor'; value: string } | null
type ExplainFn = (lineTxt: string, ou: OverUnderInfo) => string

const _ouOr = (subject: string) => (lineTxt: string, ou: OverUnderInfo) =>
  ou
    ? `Dá GREEN se ${subject} for ${ou.dir} que ${ou.value}.`
    : `Dá GREEN se ${subject} bater com a linha ${lineTxt}.`

const MARKET_EXPLAIN: Record<string, ExplainFn> = {
  'match winner':          lineTxt => `Dá GREEN se o resultado da partida for: ${lineTxt}.`,
  'double chance':         lineTxt => `Dá GREEN se a partida terminar em um dos 2 resultados cobertos: ${lineTxt}. Reduz o risco, mas também reduz a odd.`,
  'first half winner':     lineTxt => `Dá GREEN se, ao final do 1º tempo, o resultado for: ${lineTxt}.`,
  'corners asian handicap': lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de escanteios aplicada, o resultado for: ${lineTxt}.`,
  'corners european handicap': lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de escanteios aplicada, o resultado for: ${lineTxt}.`,
  'cards asian handicap':  lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de cartões aplicada, o resultado for: ${lineTxt}.`,
  'cards european handicap': lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de cartões aplicada, o resultado for: ${lineTxt}.`,
  'corners over under':    _ouOr('o total de escanteios da partida'),
  'corners over/under':    _ouOr('o total de escanteios da partida'),
  'total corners':         _ouOr('o total de escanteios da partida'),
  'corners 1x2':           lineTxt => `Dá GREEN se a equipe com mais escanteios na partida for: ${lineTxt}.`,
  'home corners over/under': _ouOr('o total de escanteios só da equipe da casa'),
  'away corners over/under': _ouOr('o total de escanteios só da equipe visitante'),
  'cards over/under':      _ouOr('o total de cartões (amarelos + vermelhos) da partida'),
  'home team total cards': _ouOr('o total de cartões só da equipe da casa'),
  'away team total cards': _ouOr('o total de cartões só da equipe visitante'),
  'home team cards':       _ouOr('o total de cartões só da equipe da casa'),
  'away team cards':       _ouOr('o total de cartões só da equipe visitante'),
  'asian handicap':        lineTxt => `Dá GREEN se, já somando a vantagem/desvantagem de gols aplicada, o resultado for: ${lineTxt}.`,
  'both teams score':      () => 'Dá GREEN se as duas equipes marcarem pelo menos 1 gol cada uma na partida.',
  'both teams to score':   () => 'Dá GREEN se as duas equipes marcarem pelo menos 1 gol cada uma na partida.',
  'total - home':          _ouOr('o total de gols só da equipe da casa'),
  'total - away':          _ouOr('o total de gols só da equipe visitante'),
  'home team total goals': _ouOr('o total de gols só da equipe da casa'),
  'away team total goals': _ouOr('o total de gols só da equipe visitante'),
  'ht/ft':                 lineTxt => `Dá GREEN se a combinação intervalo/final for: ${lineTxt}.`,
  'exact score':           lineTxt => `Dá GREEN se o placar final da partida for exatamente: ${lineTxt}.`,
  'correct score':         lineTxt => `Dá GREEN se o placar final da partida for exatamente: ${lineTxt}.`,
  'first goal scorer':     () => 'Dá GREEN se esse jogador marcar o primeiro gol da partida.',
  'anytime goalscorer':    () => 'Dá GREEN se esse jogador marcar pelo menos 1 gol a qualquer momento da partida.',
  'home/away':             lineTxt => `Dá GREEN se o vencedor da partida (sem opção de empate) for: ${lineTxt}.`,
  'to qualify':            () => 'Dá GREEN se essa equipe avançar de fase. Não depende do placar desse jogo específico.',
  'result':                lineTxt => `Dá GREEN se o resultado da partida for: ${lineTxt}.`,
  'goals over/under':      _ouOr('o total de gols da partida'),
  'total goals':           _ouOr('o total de gols da partida'),
  'over/under':            _ouOr('o total da partida'),
  'corners odd/even':      lineTxt => `Dá GREEN se o total de escanteios da partida (somando os dois times) for um número ${lineTxt === 'Ímpar' ? 'ímpar' : 'par'}.`,
  'odd/even':              lineTxt => `Dá GREEN se o total de gols da partida (somando os dois times) for um número ${lineTxt === 'Ímpar' ? 'ímpar' : 'par'}. Não importa quem vence, só a contagem total.`,
  'fouls. home total':     _ouOr('o total de faltas cometidas só pela equipe da casa'),
  'fouls. away total':     _ouOr('o total de faltas cometidas só pela equipe visitante'),
  'fouls. total':          _ouOr('o total de faltas da partida (somando os dois times)'),
  'fouls':                 _ouOr('o total de faltas da partida (somando os dois times)'),
  // "N ou mais" -- nao e' over/under, entao nao usa _ouOr: da GREEN a partir
  // de N defesas, inclusive N (P(X >= N), ver goalkeeper_model.py).
  'goalkeeper saves':      () => 'Dá GREEN se esse goleiro fizer o número de defesas da linha ou mais. Vale só as defesas dele, não as do time inteiro.',
  'player saves':          () => 'Dá GREEN se esse goleiro fizer o número de defesas da linha ou mais.',
  'saves':                 () => 'Dá GREEN se esse goleiro fizer o número de defesas da linha ou mais.',
}

/** Explicação curta em português de quando essa aposta (mercado + linha) dá GREEN. */
export function explainMarket(market?: string, line?: string): string {
  if (!market) return ''
  const key = market.trim().toLowerCase()
  const lineTxt = translateLine(line) || 'valor definido pela IA'
  const ouMatch = lineTxt.match(/^(Mais de|Menos de)\s+([\d.,]+)$/)
  const ou: OverUnderInfo = ouMatch ? { dir: ouMatch[1] === 'Mais de' ? 'maior' : 'menor', value: ouMatch[2] } : null
  const fn = MARKET_EXPLAIN[key] ?? Object.entries(MARKET_EXPLAIN).find(([k]) => key.includes(k))?.[1]
  if (!fn) return `Dá GREEN conforme as condições do mercado "${translateMarket(market)}"${line ? `, linha ${lineTxt}` : ''}.`
  return fn(lineTxt, ou)
}

const LINE_PT: Record<string, string> = {
  'home': 'Casa',
  'away': 'Visitante',
  'draw': 'Empate',
  'yes': 'Sim',
  'no': 'Não',
  'odd': 'Ímpar',
  'even': 'Par',
}

// Traduz linha completa (ex.: "Away"), "Over/Under X.Y" (ex.: "Over 8.5" ->
// "Mais de 8.5") e combos tipo Dupla Chance no formato cru da API
// ("Home/Draw" -> "Casa/Empate", ver ai_result_checker_service.py que já
// entende esse mesmo formato pra grading).
export function translateLine(line?: string): string {
  if (!line) return ''
  const trimmed = line.trim()
  const key = trimmed.toLowerCase()
  if (LINE_PT[key]) return LINE_PT[key]

  const overUnder = trimmed.match(/^(over|under)\s+([\d.,]+)$/i)
  if (overUnder) {
    const dir = overUnder[1].toLowerCase() === 'over' ? 'Mais de' : 'Menos de'
    return `${dir} ${overUnder[2]}`
  }

  const parts = trimmed.split('/')
  if (parts.length === 2) {
    const [a, b] = parts.map(p => LINE_PT[p.trim().toLowerCase()])
    if (a && b) return `${a}/${b}`
  }

  return line
}

// Seleções nacionais (Copa do Mundo etc.) vêm da API-Football em inglês --
// times de clube ja usam o mesmo nome em PT/EN, entao passam direto (fallback).
const TEAM_PT: Record<string, string> = {
  'brazil': 'Brasil', 'argentina': 'Argentina', 'germany': 'Alemanha',
  'france': 'França', 'spain': 'Espanha', 'england': 'Inglaterra',
  'italy': 'Itália', 'netherlands': 'Holanda', 'portugal': 'Portugal',
  'belgium': 'Bélgica', 'croatia': 'Croácia', 'uruguay': 'Uruguai',
  'colombia': 'Colômbia', 'mexico': 'México', 'usa': 'Estados Unidos',
  'united states': 'Estados Unidos', 'canada': 'Canadá', 'japan': 'Japão',
  'south korea': 'Coreia do Sul', 'korea republic': 'Coreia do Sul',
  'morocco': 'Marrocos', 'senegal': 'Senegal', 'ghana': 'Gana',
  'nigeria': 'Nigéria', 'cameroon': 'Camarões', 'egypt': 'Egito',
  'tunisia': 'Tunísia', 'algeria': 'Argélia', 'ivory coast': 'Costa do Marfim',
  'switzerland': 'Suíça', 'denmark': 'Dinamarca', 'sweden': 'Suécia',
  'norway': 'Noruega', 'poland': 'Polônia', 'serbia': 'Sérvia',
  'austria': 'Áustria', 'scotland': 'Escócia', 'wales': 'País de Gales',
  'ukraine': 'Ucrânia', 'turkey': 'Turquia', 'czech republic': 'República Tcheca',
  'greece': 'Grécia', 'romania': 'Romênia', 'hungary': 'Hungria',
  'ecuador': 'Equador', 'chile': 'Chile', 'peru': 'Peru',
  'paraguay': 'Paraguai', 'venezuela': 'Venezuela', 'bolivia': 'Bolívia',
  'costa rica': 'Costa Rica', 'panama': 'Panamá', 'jamaica': 'Jamaica',
  'australia': 'Austrália', 'new zealand': 'Nova Zelândia',
  'saudi arabia': 'Arábia Saudita', 'qatar': 'Catar', 'iran': 'Irã',
  'iraq': 'Iraque', 'jordan': 'Jordânia', 'china': 'China',
  'south africa': 'África do Sul', 'dr congo': 'Congo RD', 'congo dr': 'Congo RD',
  'bosnia and herzegovina': 'Bósnia e Herzegovina', 'bosnia & herzegovina': 'Bósnia e Herzegovina',
  'slovenia': 'Eslovênia', 'slovakia': 'Eslováquia', 'finland': 'Finlândia',
  'iceland': 'Islândia', 'russia': 'Rússia', 'israel': 'Israel',
  'uzbekistan': 'Uzbequistão', 'india': 'Índia',
}

export function translateTeamName(name?: string): string {
  if (!name) return ''
  return TEAM_PT[name.trim().toLowerCase()] ?? name
}
