import { describe, expect, it } from 'vitest'
import { timesDoAviso } from './CartaoDeAviso'

describe('timesDoAviso', () => {
  it('separa os times e pega os ids do payload', () => {
    expect(timesDoAviso('Flamengo x Fluminense', { home_team_id: 127, away_team_id: 124 }))
      .toEqual({ casa: 'Flamengo', fora: 'Fluminense', casaId: 127, foraId: 124 })
  })

  it('sem ids, os times saem com iniciais (id nulo)', () => {
    expect(timesDoAviso('Grêmio x Inter', {}))
      .toEqual({ casa: 'Grêmio', fora: 'Inter', casaId: null, foraId: null })
  })

  it('título que não é jogo fica sem times', () => {
    expect(timesDoAviso('Múltipla do Dia', {})).toBeNull()
    expect(timesDoAviso('Meu bilhete', null)).toBeNull()
  })
})
