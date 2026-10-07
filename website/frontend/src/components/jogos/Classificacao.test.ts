import { describe, expect, it } from 'vitest'
import { recortar, zonaDaLinha } from './Classificacao'

const linha = (team_id: number, rank: number, casa: [number, number, number, number], fora: [number, number, number, number]) => ({
  group_name: null, team_id, team_name: `T${team_id}`, rank, points: 0, goals_diff: 0, form: null, description: null,
  played: 0, win: 0, draw: 0, lose: 0, goals_for: 0, goals_against: 0,
  home_played: 5, home_win: casa[0], home_draw: casa[1], home_lose: 5 - casa[0] - casa[1], home_goals_for: casa[2], home_goals_against: casa[3],
  away_played: 5, away_win: fora[0], away_draw: fora[1], away_lose: 5 - fora[0] - fora[1], away_goals_for: fora[2], away_goals_against: fora[3],
})

describe('tabela por mando', () => {
  it('em casa reordena pelos pontos de mandante', () => {
    const linhas = [linha(1, 1, [1, 1, 3, 6], [5, 0, 10, 2]), linha(2, 2, [4, 1, 9, 3], [0, 1, 2, 9])]
    const casa = recortar(linhas as any, 'casa')
    expect(casa.map(r => [r.l.team_id, r.rank, r.pts])).toEqual([[2, 1, 13], [1, 2, 4]])
    const fora = recortar(linhas as any, 'fora')
    expect(fora[0].l.team_id).toBe(1)
    expect(fora[0].sg).toBe(8)
  })
})

describe('zona da tabela', () => {
  it.each([
    ['Promotion - CONMEBOL Libertadores', 'titulo'],
    ['Promotion - Champions League (Group Stage: )', 'titulo'],
    ['Promotion - CONMEBOL Sudamericana', 'continental'],
    ['Promotion - Europa League (Group Stage: )', 'continental'],
    ['Relegation - Serie B', 'rebaixamento'],
    [null, null],
  ])('%s', (desc, esperado) => {
    expect(zonaDaLinha(desc)).toBe(esperado)
  })
})
