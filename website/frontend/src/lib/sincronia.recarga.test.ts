import { describe, expect, it } from 'vitest'
import { temPendenteRolando } from './sincronia'

// 15/10/2026 21:00 em Brasília = 16/10 00:00 UTC
const AGORA = Date.parse('2026-10-16T00:00:00Z')

describe('temPendenteRolando', () => {
  it('pick sem resultado com o jogo já começado (horário de Brasília sem fuso)', () => {
    expect(temPendenteRolando({ vip: [{ result: null, match_datetime: '2026-10-15 20:30:00' }] }, AGORA)).toBe(true)
  })

  it('jogo que ainda não começou, ou pick já resolvido, não conta', () => {
    expect(temPendenteRolando({ vip: [{ result: null, match_datetime: '2026-10-15 21:30:00' }] }, AGORA)).toBe(false)
    expect(temPendenteRolando({ vip: [{ result: 'GREEN', match_datetime: '2026-10-15 20:30:00' }] }, AGORA)).toBe(false)
  })

  it('múltipla: olha o horário das pernas', () => {
    const dados = { multiplas: [{ result: null, games: [{ match_datetime: '2026-10-15 19:00:00' }] }] }
    expect(temPendenteRolando(dados, AGORA)).toBe(true)
  })

  it('sem dado nenhum', () => {
    expect(temPendenteRolando(null, AGORA)).toBe(false)
  })
})
