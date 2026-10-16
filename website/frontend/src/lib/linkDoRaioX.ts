/*
 * Endereço do Raio-X de um jogo (/jogos/<id>). Os times vão na URL porque o
 * jogo pode ser de uma data que a coleta ainda não trouxe pro banco. Usado pela
 * lista de Jogos e pelo "Hoje na liga" da aba Ligas.
 */
export interface JogoParaRaioX {
  fixture_id: number
  home_team: string; away_team: string
  home_team_id?: number; away_team_id?: number
  league_id: number; league_name: string
  match_datetime?: string
  status?: string
  home_goals?: number | null; away_goals?: number | null
}

export function linkDoRaioX(f: JogoParaRaioX): string {
  const q = new URLSearchParams()
  if (f.home_team_id) q.set('home', String(f.home_team_id))
  if (f.away_team_id) q.set('away', String(f.away_team_id))
  q.set('league', String(f.league_id))
  q.set('liga', f.league_name)
  q.set('casa', f.home_team); q.set('fora', f.away_team)
  if (f.match_datetime) q.set('quando', f.match_datetime)
  if (f.status) q.set('st', f.status)
  if (f.home_goals != null && f.away_goals != null) { q.set('gc', String(f.home_goals)); q.set('gf', String(f.away_goals)) }
  return `/jogos/${f.fixture_id}?${q}`
}
