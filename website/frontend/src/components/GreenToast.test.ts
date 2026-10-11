import { describe, expect, it } from 'vitest'
import { jogoDoResultado, mercadoDoResultado } from './GreenToast'
import { greensParaAvisar, type AppNotification } from '../context/NotificationContext'

const item = (over: Partial<AppNotification>): AppNotification => ({
  id: 1, type: 'pick_result', title: 'GREEN: A x B', body: null, url: '/banca',
  payload: { result: 'GREEN' }, read: false, created_at: null, idade_seg: 60, ...over,
})

describe('greensParaAvisar', () => {
  it('só GREEN e meio-green, não lidos, recentes e ainda não avisados', () => {
    const itens = [
      item({ id: 1 }),
      item({ id: 2, payload: { result: 'RED' } }),
      item({ id: 3, read: true }),
      item({ id: 4, idade_seg: 3 * 60 * 60 }),        // velho: fica só no sino
      item({ id: 5, idade_seg: null }),               // idade desconhecida não toca
      item({ id: 6, type: 'live_novo' }),
      item({ id: 7, payload: { result: 'HALF-WIN' }, idade_seg: 10 }),
      item({ id: 8 }),
    ]
    expect(greensParaAvisar(itens, new Set([8])).map(n => n.id)).toEqual([7, 1])
  })
})

describe('textos do cartão', () => {
  it('tira o prefixo do resultado do título', () => {
    expect(jogoDoResultado('GREEN: Flamengo x Palmeiras')).toBe('Flamengo x Palmeiras')
    expect(jogoDoResultado('HALF-WIN: Múltipla do Dia')).toBe('Múltipla do Dia')
  })

  it('tira o dinheiro do corpo, que vira o destaque', () => {
    expect(mercadoDoResultado('Escanteios Over 9.5 +R$ 12,00 (+0.85u)')).toBe('Escanteios Over 9.5')
    expect(mercadoDoResultado('Gols Under 2.5')).toBe('Gols Under 2.5')
    expect(mercadoDoResultado('+R$ 1.234,50 (+2.00u)')).toBeNull()
    expect(mercadoDoResultado(null)).toBeNull()
  })
})
