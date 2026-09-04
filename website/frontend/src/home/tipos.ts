/*
 * Formas que a Home e as seções dela trocam entre si.
 *
 * Existem em arquivo próprio porque `RecentResults` saiu do Home.tsx para
 * poder ser `lazy()`, e uma cópia da interface em cada lado é como as duas
 * começam a divergir · o `match_datetime` opcional aqui, por exemplo, é o
 * detalhe que decide se o horário do jogo aparece no card.
 */
export interface RecentTip {
  match_date: string
  /** Horário do jogo · só existe enquanto a partida está em `fixtures`. */
  match_datetime?: string | null
  home_team_name: string
  away_team_name?: string
  home_team_id?: number
  away_team_id?: number
  market: string
  line?: string
  odd: number
  result: string
  profit: number
  source: string
}
