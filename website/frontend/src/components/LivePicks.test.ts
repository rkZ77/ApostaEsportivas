import { describe, expect, it } from 'vitest'
import { calcLiveProb, resumoDoDia } from './LivePicks'

describe('calcLiveProb · de onde a odd vale (15/10/2026)', () => {
  const base = { odd: 2, line: 'Over 2.5', market: 'Gols', line_val: 2.5, status: '2H' }

  it('pick AO VIVO: no minuto em que nasceu, a chance é a da odd', () => {
    const p = calcLiveProb({ ...base, elapsed: 60, current_val: 1, minuto_criacao: 60, valor_criacao: 1 })
    expect(p).toBeGreaterThanOrEqual(49)
    expect(p).toBeLessThanOrEqual(51)
  })

  it('a conta antiga (odd tratada como do jogo todo) dava bem menos', () => {
    const antiga = calcLiveProb({ ...base, elapsed: 60, current_val: 1 })
    expect(antiga!).toBeLessThan(40)
  })

  it('pick de pré-jogo no apito continua a chance da odd', () => {
    const p = calcLiveProb({ ...base, status: '1H', elapsed: 0.0001, current_val: 0 })
    expect(p).toBeGreaterThanOrEqual(49)
    expect(p).toBeLessThanOrEqual(51)
  })

  it('Menos de: nasceu aos 60 com 1 gol, odd 2 → ~50% na hora', () => {
    const p = calcLiveProb({ ...base, line: 'Under 2.5', elapsed: 60, current_val: 1, minuto_criacao: 60, valor_criacao: 1 })
    expect(p).toBeGreaterThanOrEqual(49)
    expect(p).toBeLessThanOrEqual(51)
  })
})

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
