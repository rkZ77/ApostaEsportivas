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
