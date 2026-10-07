import { describe, expect, it } from 'vitest'
import { resumoDoDia } from './LivePicks'

describe('resumoDoDia', () => {
  it('soma o que está em jogo, o retorno possível e o resultado fechado', () => {
    const r = resumoDoDia([
      { stake_units: 2, odd: 2, result: null },               // R$20 em jogo, volta R$40
      { stake_units: 1, odd: 1.5, actual_odd: 1.8, result: 'GREEN' }, // +R$8
      { stake_units: 3, odd: 2, result: 'RED' },              // -R$30
      { stake_units: 1, odd: 2, result: null, cashout_amount: 15 },   // +R$5
      { stake_amount: 30, stake_units: 1, odd: 1.5, result: null },   // alavancagem: R$30
    ], 10)!
    expect(r.emJogo).toBe(50)
    expect(r.potencial).toBe(85)
    expect(r.resultado).toBeCloseTo(-17)
  })

  it('sem valor de unidade não inventa reais', () => {
    expect(resumoDoDia([{ stake_units: 1, odd: 2 }], undefined)).toBeNull()
  })
})
