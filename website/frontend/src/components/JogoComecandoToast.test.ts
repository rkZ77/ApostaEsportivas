import { describe, expect, it } from 'vitest'
import { jogosComecandoParaAvisar, type AppNotification } from '../context/NotificationContext'

const aviso = (id: number, extra: Partial<AppNotification> = {}): AppNotification => ({
  id, type: 'jogo_comecando', title: 'A x B', body: 'Jogo do seu bilhete começa às 16:00.',
  url: '/picks#minhas_apostas', payload: { fixture_id: 9 }, read: false, created_at: '', idade_seg: 60,
  ...extra,
} as AppNotification)

describe('jogosComecandoParaAvisar', () => {
  it('só o que é novo, não lido e ainda dentro da janela', () => {
    const itens = [
      aviso(1),
      aviso(2, { read: true }),
      aviso(3, { idade_seg: 30 * 60 }),
      aviso(4, { type: 'pick_result' }),
      aviso(5, { idade_seg: 10 }),
    ]
    expect(jogosComecandoParaAvisar(itens, new Set([1])).map(n => n.id)).toEqual([5])
  })

  it('idade desconhecida não vira cartão', () => {
    expect(jogosComecandoParaAvisar([aviso(1, { idade_seg: null as unknown as number })], new Set())).toEqual([])
  })
})
