import { describe, expect, it } from 'vitest'
import { caminhoDoJogo, slugDoJogo } from './jogoPublico'

/* Os mesmos casos de test_jogo_publico_2026_10.py · as duas pontas têm que
 * produzir o mesmo slug pro mesmo nome. */
describe('slugDoJogo', () => {
  it('tira acento, caixa e pontuação', () => {
    expect(slugDoJogo('Atlético-MG', 'São Paulo')).toBe('atletico-mg-x-sao-paulo')
    expect(slugDoJogo('Bayern München', 'Paris Saint Germain')).toBe('bayern-munchen-x-paris-saint-germain')
    expect(slugDoJogo('  Grêmio  ', 'Athletico Paranaense')).toBe('gremio-x-athletico-paranaense')
  })

  it('nome vazio não deixa a URL quebrada', () => {
    expect(slugDoJogo(null, '')).toBe('casa-x-fora')
  })

  it('monta o caminho com o id na frente', () => {
    expect(caminhoDoJogo({ fixture_id: 123, home_team: 'Flamengo', away_team: 'Palmeiras' }))
      .toBe('/jogo/123/flamengo-x-palmeiras')
  })
})
