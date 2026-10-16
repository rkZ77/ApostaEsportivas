import { describe, expect, it } from 'vitest'
import { distribuicaoDeGols, linhasDaLiga } from './linhasDaLiga'

const j = (h: number | null, a: number | null, esc: number | null = 10, am: number | null = 4) =>
  ({ home_goals: h, away_goals: a, total_corners: esc, total_yellow_cards: am })

describe('linhas da liga', () => {
  it('conta em quantos jogos cada linha bateu', () => {
    const [golsG, esc, cart] = linhasDaLiga([j(2, 1), j(0, 0), j(1, 1, 8), j(3, 2, null, null)])
    const por = (g: typeof golsG, r: string) => g.linhas.find(l => l.rotulo === r)!
    expect(por(golsG, 'Mais de 2,5')).toEqual({ rotulo: 'Mais de 2,5', bateu: 2, total: 4, pct: 50 })
    expect(por(golsG, 'Ambas marcam').pct).toBe(75)
    // Jogo sem escanteio fica fora da conta, não vira "não bateu".
    expect(por(esc, 'Mais de 9,5')).toMatchObject({ bateu: 2, total: 3, pct: 67 })
    expect(por(cart, 'Mais de 3,5')).toMatchObject({ total: 3, pct: 100 })
  })

  it('sem dado nenhum o percentual é nulo', () => {
    expect(linhasDaLiga([])[0].linhas[0].pct).toBeNull()
  })

  it('distribui os gols de 0 a 5+', () => {
    const d = distribuicaoDeGols([j(0, 0), j(4, 3), j(1, 0), j(null, 1)])
    expect(d.map(x => x.jogos)).toEqual([1, 1, 0, 0, 0, 1])
    expect(d[5].rotulo).toBe('5+')
  })
})
