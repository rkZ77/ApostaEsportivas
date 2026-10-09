import { describe, expect, it } from 'vitest'
import { chanceDoResultado, type OddDaCasa } from './oddsDoJogo'

const odd = (market_id: number, valor: string, o: number): OddDaCasa => ({ market_id, valor, odd: o, casa: 'X' })

describe('chanceDoResultado', () => {
  it('tira a margem: os três somam 100', () => {
    const c = chanceDoResultado([odd(1, 'Home', 1.36), odd(1, 'Draw', 5.99), odd(1, 'Away', 9.5)])!
    expect(c.casa + c.empate + c.fora).toBeCloseTo(1)
    expect(c.casa).toBeGreaterThan(c.empate)
    expect(c.empate).toBeGreaterThan(c.fora)
  })

  it('sem um dos três não inventa', () => {
    expect(chanceDoResultado([odd(1, 'Home', 1.36), odd(1, 'Away', 9.5)])).toBeNull()
  })
})
