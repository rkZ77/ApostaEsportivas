import { describe, expect, it } from 'vitest'
import { jogoDoTitulo, partesDoCorpo } from './LivePickToast'

describe('partesDoCorpo', () => {
  it('separa mercado, odd e minuto do texto do servidor', () => {
    expect(partesDoCorpo("Escanteios Mais/Menos Over 9.5 @ 1.85 (criado aos 34')"))
      .toEqual({ mercado: 'Escanteios Mais/Menos Over 9.5', odd: '1.85', minuto: '34' })
  })

  it('sem minuto', () => {
    expect(partesDoCorpo('Gols Over 2.5 @ 2.1'))
      .toEqual({ mercado: 'Gols Over 2.5', odd: '2.1', minuto: null })
  })

  it('formato desconhecido volta inteiro, sem odd', () => {
    expect(partesDoCorpo('Oportunidade no jogo')).toEqual({ mercado: 'Oportunidade no jogo', odd: null, minuto: null })
    expect(partesDoCorpo(null)).toEqual({ mercado: null, odd: null, minuto: null })
  })
})

describe('jogoDoTitulo', () => {
  it('tira o prefixo que o selo do cartão já mostra', () => {
    expect(jogoDoTitulo('Pick ao vivo: Flamengo x Palmeiras')).toBe('Flamengo x Palmeiras')
  })

  it('título fora do formato passa inteiro', () => {
    expect(jogoDoTitulo('Oportunidade agora')).toBe('Oportunidade agora')
    expect(jogoDoTitulo('Pick ao vivo:')).toBe('Pick ao vivo:')
  })
})
