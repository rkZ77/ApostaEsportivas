import { describe, expect, it } from 'vitest'
import { linhasDoCampo } from './Campinho'

const j = (id: number, posicao: string, grid: string | null = null) =>
  ({ player_id: id, nome: `J${id}`, posicao, grid })

describe('linhas do campo', () => {
  it('oficial: segue o grid do provedor (linha e coluna)', () => {
    const linhas = linhasDoCampo([j(9, 'A', '3:1'), j(1, 'G', '1:1'), j(5, 'D', '2:2'), j(4, 'D', '2:1')])
    expect(linhas.map(l => l.map(x => x.player_id))).toEqual([[1], [4, 5], [9]])
  })

  it('provável: distribui pela formação, na ordem de posição', () => {
    const xi = [j(9, 'A'), j(1, 'G'), ...[2, 3, 4, 5].map(i => j(i, 'D')),
                ...[6, 7, 8].map(i => j(i, 'M')), j(10, 'A'), j(11, 'A')]
    const linhas = linhasDoCampo(xi, '4-3-3')
    expect(linhas.map(l => l.length)).toEqual([1, 4, 3, 3])
    expect(linhas[0][0].player_id).toBe(1)
  })

  it('formação que não fecha com o número de jogadores: agrupa por posição', () => {
    const linhas = linhasDoCampo([j(1, 'G'), j(2, 'D'), j(9, 'A')], '4-4-2')
    expect(linhas.map(l => l.map(x => x.posicao))).toEqual([['G'], ['D'], ['A']])
  })
})
