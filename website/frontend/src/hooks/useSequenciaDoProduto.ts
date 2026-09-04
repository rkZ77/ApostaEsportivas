import { useEffect, useState } from 'react'
import api from '../services/api'

/*
 * A SEQUÊNCIA ATUAL DE CADA PRODUTO, lida uma vez por sessão.
 *
 * O número já existia no backend (`/suggestions/stats/quick`, campos `streak` e
 * `streak_type`) e só aparecia no placar de cinco ladrilhos dentro do "O que é"
 * de cada aba. Ele passou a valer no CARD (ver `SequenciaBadge`), e card de
 * pick aparece aos montes na mesma tela.
 *
 * Por isso o cache e a fila de espera moram aqui, no módulo, e não no
 * componente: sem isso, oito cards de Boost na mesma grade disparariam oito
 * requisições idênticas ao mesmo endpoint no mesmo instante. Com a fila, a
 * primeira busca é a única, e as outras sete esperam a mesma promessa.
 *
 * Não expira: a sequência muda quando um pick é liquidado, e liquidação não
 * acontece com a tela aberta a ponto de valer uma revalidação. Recarregar a
 * página busca de novo.
 */
export interface SequenciaDoProduto {
  streak: number
  streakType: 'green' | 'red' | null
}

const cache = new Map<string, SequenciaDoProduto>()
const emVoo = new Map<string, Promise<SequenciaDoProduto>>()

function buscar(source: string): Promise<SequenciaDoProduto> {
  const pronto = emVoo.get(source)
  if (pronto) return pronto
  const p = api.get('/suggestions/stats/quick', { params: { source } })
    .then(r => {
      const dado: SequenciaDoProduto = {
        streak: Number(r.data?.streak ?? 0),
        streakType: (r.data?.streak_type ?? null) as 'green' | 'red' | null,
      }
      cache.set(source, dado)
      return dado
    })
    /* Sequência é contexto, não conteúdo: falhar em silêncio como zero deixa o
       card exatamente como era antes de existir este selo. */
    .catch(() => ({ streak: 0, streakType: null } as SequenciaDoProduto))
    .finally(() => { emVoo.delete(source) })
  emVoo.set(source, p)
  return p
}

export function useSequenciaDoProduto(source: string | null | undefined): SequenciaDoProduto {
  const [dado, setDado] = useState<SequenciaDoProduto>(
    () => (source ? cache.get(source) : null) ?? { streak: 0, streakType: null })

  useEffect(() => {
    if (!source) return
    const guardado = cache.get(source)
    if (guardado) { setDado(guardado); return }
    let vivo = true
    buscar(source).then(d => { if (vivo) setDado(d) })
    return () => { vivo = false }
  }, [source])

  return dado
}
