import { describe, expect, it } from 'vitest'
import { chanceDoBilhete, jaComecou, rotuloDoMinuto, rotuloDoTempo, type LeituraAoVivo } from './picksAgora'

const leitura = (p: Partial<LeituraAoVivo>): LeituraAoVivo => ({
  status: '2H', minuto: 60, placar: [1, 0], rotulo: null, atual: 4, linha: 5.5, direcao: 'over',
  situacao: 'neutral', travado: false, chance: 0.5, periodo: 'total', idade: 30, ...p,
})

describe('picks ao vivo', () => {
  it('horário de Brasília sem fuso: começou 5 min antes do apito', () => {
    const apito = '2026-10-09T18:00:00'          // 21:00 UTC
    expect(jaComecou(apito, new Date('2026-10-09T20:50:00Z'))).toBe(false)
    expect(jaComecou(apito, new Date('2026-10-09T20:56:00Z'))).toBe(true)
    expect(jaComecou(null)).toBe(true)
  })

  it('minuto, intervalo e pênaltis', () => {
    expect(rotuloDoMinuto({ status: '2H', minuto: 59 })).toBe("59'")
    expect(rotuloDoMinuto({ status: 'HT', minuto: 45 })).toBe('Intervalo')
    expect(rotuloDoMinuto({ status: '1H', minuto: null })).toBe('Ao vivo')
    expect(rotuloDoTempo({ status: '2H', minuto: 59 })).toBe("2ºT 59'")
    expect(rotuloDoTempo({ status: 'HT', minuto: 45 })).toBe('Intervalo')
  })

  it('chance do bilhete: ao vivo onde há, a de antes no resto', () => {
    expect(chanceDoBilhete([
      { antes: 0.8, agora: leitura({ chance: 0.5 }) },
      { antes: 0.6, agora: null },
    ])).toBeCloseTo(0.3)
    // Sem nenhuma perna ao vivo não há "chance agora".
    expect(chanceDoBilhete([{ antes: 0.8, agora: null }])).toBeNull()
    // Perna sem número nenhum não vira 100%.
    expect(chanceDoBilhete([{ antes: null, agora: null }, { antes: 0.6, agora: leitura({}) }])).toBeNull()
  })
})
