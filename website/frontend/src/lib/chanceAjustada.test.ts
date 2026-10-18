import { describe, expect, it } from 'vitest'
import { encolher, estimar, PESO_DA_LIGA, PESO_DO_PRECO, vereditoDoValor } from './chanceAjustada'
import { precoSemMargem, type OddDaCasa } from './oddsDoJogo'

const odd = (market_id: number, valor: string, o: number): OddDaCasa => ({ market_id, valor, odd: o, casa: null })

describe('chance ajustada', () => {
  it('8/8 com o preço dizendo 58% fica perto do preço, não de 100%', () => {
    // Zwolle x Go Ahead, escanteios +9.5 (18/10/2026): 1.60 contra 2.20.
    const preco = precoSemMargem([odd(45, 'Over 9.5', 1.6), odd(45, 'Under 9.5', 2.2)],
      { mercado: 'escanteios', quem: 'jogo', periodo: 'total', lado: 'mais', linha: 9.5 })!
    expect(preco).toBeCloseTo(0.579, 3)
    const e = estimar({ bateu: 8, n: 8, odd: 1.6, precoSemMargem: preco })!
    expect(e.fonte).toBe('preco')
    expect(e.chance).toBeCloseTo((8 + PESO_DO_PRECO * preco) / (8 + PESO_DO_PRECO), 6)
    expect(e.chance).toBeLessThan(0.65)
    expect(e.oddJusta).toBeCloseTo(1 / e.chance, 6)
    expect(e.valor).toBeCloseTo(e.chance * 1.6 - 1, 6)
  })

  it('sem preço dos dois lados, puxa pra média da liga', () => {
    const e = estimar({ bateu: 6, n: 6, odd: 1.42, taxaLiga: 0.6, nLiga: 120 })!
    expect(e.fonte).toBe('liga')
    expect(e.chance).toBeCloseTo(encolher(6, 6, 0.6, PESO_DA_LIGA), 6)
  })

  it('liga com poucos jogos não serve de base, e sem base não há estimativa', () => {
    expect(estimar({ bateu: 6, n: 6, taxaLiga: 0.6, nLiga: 10 })).toBeNull()
    expect(estimar({ bateu: 6, n: 6 })).toBeNull()
  })

  it('veredito do valor', () => {
    expect(vereditoDoValor(0.08)).toBe('valor')
    expect(vereditoDoValor(0.01)).toBe('justa')
    expect(vereditoDoValor(-0.12)).toBe('negativo')
    expect(vereditoDoValor(null)).toBeNull()
  })
})

describe('preço sem margem', () => {
  it('resultado e chance dupla saem dos três lados', () => {
    const odds = [odd(1, 'Home', 2.0), odd(1, 'Draw', 3.4), odd(1, 'Away', 3.8)]
    const casa = precoSemMargem(odds, { mercado: 'resultado', quem: 'jogo', periodo: 'total', escolha: '1' })!
    const x = precoSemMargem(odds, { mercado: 'resultado', quem: 'jogo', periodo: 'total', escolha: 'X' })!
    const dupla = precoSemMargem(odds, { mercado: 'resultado', quem: 'jogo', periodo: 'total', escolha: '1X' })!
    expect(dupla).toBeCloseTo(casa + x, 6)
  })

  it('ambas marcam usa o Sim contra o Não', () => {
    const odds = [odd(8, 'Yes', 1.8), odd(8, 'No', 2.0)]
    const sim = precoSemMargem(odds, { mercado: 'btts', quem: 'jogo', periodo: 'total' })!
    const nao = precoSemMargem(odds, { mercado: 'btts', quem: 'jogo', periodo: 'total', escolha: 'nao' })!
    expect(sim + nao).toBeCloseTo(1, 6)
  })

  it('falta um lado: null', () => {
    expect(precoSemMargem([odd(45, 'Over 9.5', 1.6)],
      { mercado: 'escanteios', quem: 'jogo', periodo: 'total', lado: 'mais', linha: 9.5 })).toBeNull()
  })
})
