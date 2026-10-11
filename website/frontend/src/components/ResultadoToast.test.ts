import { describe, expect, it } from 'vitest'
import { jogoDoResultado, mercadoDoResultado, visualDoResultado } from './ResultadoToast'
import { resultadosParaAvisar, type AppNotification } from '../context/NotificationContext'

const item = (over: Partial<AppNotification>): AppNotification => ({
  id: 1, type: 'pick_result', title: 'GREEN: A x B', body: null, url: '/banca',
  payload: { result: 'GREEN' }, read: false, created_at: null, idade_seg: 60, ...over,
})

describe('resultadosParaAvisar', () => {
  it('todo resultado não lido, recente e ainda não avisado', () => {
    const itens = [
      item({ id: 1 }),
      item({ id: 2, payload: { result: 'RED' }, idade_seg: 30 }),
      item({ id: 3, read: true }),
      item({ id: 4, idade_seg: 3 * 60 * 60 }),        // velho: fica só no sino
      item({ id: 5, idade_seg: null }),               // idade desconhecida não toca
      item({ id: 6, type: 'live_novo' }),
      item({ id: 7, payload: { result: 'PUSH' }, idade_seg: 10 }),
      item({ id: 8 }),
      item({ id: 9, payload: { result: 'OUTRA' } }),  // rótulo desconhecido não toca
    ]
    expect(resultadosParaAvisar(itens, new Set([8])).map(n => n.id)).toEqual([7, 2, 1])
  })
})

describe('visualDoResultado', () => {
  it('cada resultado com a sua cor', () => {
    expect(visualDoResultado('GREEN').tom).toBe('green')
    expect(visualDoResultado('half-win').tom).toBe('green')
    expect(visualDoResultado('RED').tom).toBe('red')
    expect(visualDoResultado('HALF-LOSS').tom).toBe('red')
    expect(visualDoResultado('PUSH').tom).toBe('neutro')
    expect(visualDoResultado(undefined).tom).toBe('neutro')   // nunca verde por engano
  })
})

describe('textos do cartão', () => {
  it('tira o prefixo do resultado do título', () => {
    expect(jogoDoResultado('GREEN: Flamengo x Palmeiras')).toBe('Flamengo x Palmeiras')
    expect(jogoDoResultado('RED: Múltipla do Dia')).toBe('Múltipla do Dia')
  })

  it('tira o dinheiro do corpo, que vira o destaque', () => {
    expect(mercadoDoResultado('Escanteios Over 9.5 +R$ 12,00 (+0.85u)')).toBe('Escanteios Over 9.5')
    expect(mercadoDoResultado('Gols Under 2.5 -R$ 10,00 (-1.00u)')).toBe('Gols Under 2.5')
    expect(mercadoDoResultado('Gols Under 2.5')).toBe('Gols Under 2.5')
    expect(mercadoDoResultado(null)).toBeNull()
  })
})
