const MARKET_PT: Record<string, string> = {
  'match winner': 'Resultado Final (1X2)',
  'double chance': 'Dupla Chance',
  'double chance - 1st half': 'Dupla Chance - 1º Tempo',
  'first half winner': 'Vencedor do 1º Tempo',
  'asian handicap': 'Handicap Asiático',
  'corners asian handicap': 'Escanteios Handicap Asiático',
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

// Explicação curta do que a aposta significa, em português simples. Ordem dos
// campos importa: entradas mais específicas (escanteios, cartões, times
// isolados) vêm antes das genéricas de gols/over-under, senão o match por
// substring (ex.: "corners over/under" contém "over/under") acertaria a
// explicação errada primeiro.
const MARKET_EXPLAIN: Record<string, string> = {
  'match winner': 'Aposta em quem vence a partida, incluindo a opção de empate: {line}.',
  'double chance': 'Aposta cobrindo 2 dos 3 resultados possíveis. Reduz o risco, mas também reduz a odd: {line}.',
  'first half winner': 'Aposta em quem está na frente no placar ao final do 1º tempo: {line}.',
  'corners asian handicap': 'Uma equipe recebe uma vantagem ou desvantagem de escanteios no papel, pra equilibrar a odd: {line}.',
  'corners over under': 'Aposta se o total de escanteios da partida fica acima ou abaixo do número da linha: {line}.',
  'corners over/under': 'Aposta se o total de escanteios da partida fica acima ou abaixo do número da linha: {line}.',
  'total corners': 'Aposta se o total de escanteios da partida fica acima ou abaixo do número da linha: {line}.',
  'corners 1x2': 'Aposta em qual equipe fecha a partida com mais escanteios, incluindo a opção de empate: {line}.',
  'home corners over/under': 'Aposta no total de escanteios só da equipe da casa, acima ou abaixo da linha: {line}.',
  'away corners over/under': 'Aposta no total de escanteios só da equipe visitante, acima ou abaixo da linha: {line}.',
  'cards over/under': 'Aposta se o total de cartões (amarelos + vermelhos) da partida fica acima ou abaixo da linha: {line}.',
  'home team total cards': 'Aposta no total de cartões só da equipe da casa, acima ou abaixo da linha: {line}.',
  'away team total cards': 'Aposta no total de cartões só da equipe visitante, acima ou abaixo da linha: {line}.',
  'home team cards': 'Aposta no total de cartões só da equipe da casa, acima ou abaixo da linha: {line}.',
  'away team cards': 'Aposta no total de cartões só da equipe visitante, acima ou abaixo da linha: {line}.',
  'asian handicap': 'Uma equipe recebe uma vantagem ou desvantagem de gols no papel, pra equilibrar a odd: {line}.',
  'both teams score': 'Aposta que as duas equipes marcam pelo menos 1 gol cada uma na partida.',
  'both teams to score': 'Aposta que as duas equipes marcam pelo menos 1 gol cada uma na partida.',
  'total - home': 'Aposta no total de gols só da equipe da casa, acima ou abaixo da linha: {line}.',
  'total - away': 'Aposta no total de gols só da equipe visitante, acima ou abaixo da linha: {line}.',
  'home team total goals': 'Aposta no total de gols só da equipe da casa, acima ou abaixo da linha: {line}.',
  'away team total goals': 'Aposta no total de gols só da equipe visitante, acima ou abaixo da linha: {line}.',
  'ht/ft': 'Aposta combinando quem está na frente no intervalo com quem vence no final da partida: {line}.',
  'exact score': 'Aposta no placar exato da partida: {line}.',
  'correct score': 'Aposta no placar exato da partida: {line}.',
  'first goal scorer': 'Aposta em qual jogador marca o primeiro gol da partida.',
  'anytime goalscorer': 'Aposta que esse jogador marca pelo menos 1 gol a qualquer momento da partida.',
  'home/away': 'Aposta em quem vence a partida, sem a opção de empate: {line}.',
  'to qualify': 'Aposta em quem avança de fase. Não depende do placar desse jogo específico.',
  'result': 'Aposta no resultado da partida: {line}.',
  'goals over/under': 'Aposta se o total de gols da partida fica acima ou abaixo do número da linha: {line}.',
  'total goals': 'Aposta se o total de gols da partida fica acima ou abaixo do número da linha: {line}.',
  'over/under': 'Aposta se o total fica acima ou abaixo do número da linha: {line}.',
}

/** Explicação curta em português do que essa aposta (mercado + linha) significa na prática. */
export function explainMarket(market?: string, line?: string): string {
  if (!market) return ''
  const key = market.trim().toLowerCase()
  const lineTxt = translateLine(line) || 'valor definido pela IA'
  const template = MARKET_EXPLAIN[key] ?? Object.entries(MARKET_EXPLAIN).find(([k]) => key.includes(k))?.[1]
  if (!template) return `Aposta no mercado "${translateMarket(market)}"${line ? `, linha ${lineTxt}` : ''}.`
  return template.replace('{line}', lineTxt)
}

const LINE_PT: Record<string, string> = {
  'home': 'Casa',
  'away': 'Visitante',
  'draw': 'Empate',
  'yes': 'Sim',
  'no': 'Não',
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
