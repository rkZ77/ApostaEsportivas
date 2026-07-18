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
