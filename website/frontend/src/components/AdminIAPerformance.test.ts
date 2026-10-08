import { describe, expect, it } from 'vitest'
import { leituraDaCalibracao } from './AdminIAPerformance'

const b = (hit: number, prometido: number, implicita: number, resolvidos = 100) => ({
  n: resolvidos, green: 0, red: 0, push: 0, pendentes: 0, resolvidos,
  hit, lucro: 0, roi: null, clv: null, prometido, implicita,
})

describe('leituraDaCalibracao', () => {
  it('acerto bem acima do preço é valor', () => {
    expect(leituraDaCalibracao(b(72, 70, 58))?.tom).toBe('bom')
  })
  it('acerto no preço e abaixo do prometido é valor que o mercado já sabia', () => {
    expect(leituraDaCalibracao(b(57, 70, 58))?.tom).toBe('ruim')
  })
  it('perto dos dois é neutro', () => {
    expect(leituraDaCalibracao(b(62, 64, 60))?.tom).toBe('neutro')
  })
  it('amostra pequena não tem leitura', () => {
    expect(leituraDaCalibracao(b(90, 70, 58, 12))).toBeNull()
  })
})
