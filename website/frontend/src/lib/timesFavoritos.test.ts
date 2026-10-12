import { describe, expect, it } from 'vitest'
import { separarFavoritos } from './timesFavoritos'

describe('separarFavoritos', () => {
  it('jogo com o time em qualquer lado sobe, e a ordem de cada parte fica', () => {
    const jogos = [
      { id: 1, home_team_id: 10, away_team_id: 20 },
      { id: 2, home_team_id: 30, away_team_id: 5 },
      { id: 3, home_team_id: 5, away_team_id: 40 },
      { id: 4, home_team_id: null, away_team_id: null },
    ]
    const { dosFavoritos, resto } = separarFavoritos(jogos, [5])
    expect(dosFavoritos.map(j => j.id)).toEqual([2, 3])
    expect(resto.map(j => j.id)).toEqual([1, 4])
  })

  it('sem favoritos, nada muda', () => {
    const jogos = [{ home_team_id: 1, away_team_id: 2 }]
    expect(separarFavoritos(jogos, []).resto).toEqual(jogos)
  })
})
