import { useState } from 'react'
import api from '../services/api'

/*
 * Odd do momento do clique em "Apostei".
 *
 * A odd salva no pick é a da hora em que o motor rodou. Entre a geração e o
 * clique passam horas, e é a odd da CASA naquele instante que o usuário vai
 * pegar de fato · registrar a antiga estraga a banca dele e o CLV do site.
 *
 * Antes isto vivia copiado dentro do card VIP e do card free, e não existia nos
 * de múltipla e alavancagem: nesses dois o modal abria direto com a odd da
 * geração, sem nunca conferir. Um lugar só, os quatro tipos passam por aqui.
 *
 * SEM TRAVA DE DIREÇÃO: o que a casa estiver pagando é o que volta, para cima
 * ou para baixo. (A impressão de que "só atualizava para menos" vinha de o
 * backend só saber ler odd ao vivo · pré-jogo devolvia nulo e o front caía na
 * odd antiga. Jogo em andamento quase sempre repreça para baixo, então a única
 * atualização que aparecia era essa.)
 *
 * Nunca bloqueia o fluxo: qualquer falha cai na odd já salva e o modal abre
 * igual. Registrar a aposta é mais importante que atualizar a odd.
 */

export interface OddAtualizada {
  /** A odd para abrir o modal · a nova quando veio, a do pick quando não. */
  odd: number
  /** true quando a consulta trouxe número diferente do salvo no pick. */
  mudou: boolean
  /** 'live' | 'prematch' | null · de onde veio a odd nova. */
  origem: string | null
  /** Bilhete com pernas que não puderam ser reconsultadas. */
  parcial: boolean
}

const DIFERENCA_MINIMA = 0.001

export function useOddAtualizada() {
  const [buscando, setBuscando] = useState(false)

  /** Pick de um jogo só (VIP, free, faltas, defesas). */
  async function odd(
    pickOdd: number,
    params: { fixture_id?: number | null; market_type?: string | null; line?: string | null },
  ): Promise<OddAtualizada> {
    const base = Number(pickOdd)
    if (!params.fixture_id) return { odd: base, mudou: false, origem: null, parcial: false }
    setBuscando(true)
    try {
      const { data } = await api.get('/live/pick-odd', {
        params: {
          fixture_id: params.fixture_id,
          market_type: params.market_type ?? '',
          line: params.line ?? '',
        },
      })
      const nova = Number(data?.odd)
      if (!nova || !Number.isFinite(nova)) return { odd: base, mudou: false, origem: null, parcial: false }
      return {
        odd: nova,
        mudou: Math.abs(nova - base) > DIFERENCA_MINIMA,
        origem: data?.source ?? null,
        parcial: false,
      }
    } catch {
      return { odd: base, mudou: false, origem: null, parcial: false }
    } finally {
      setBuscando(false)
    }
  }

  /** Bilhete combinado (múltipla, alavancagem): o backend refaz o produto das pernas. */
  async function oddBilhete(
    pickOdd: number,
    pickId: number,
    pickType: 'multipla' | 'alavancagem',
  ): Promise<OddAtualizada> {
    const base = Number(pickOdd)
    setBuscando(true)
    try {
      const { data } = await api.get('/live/ticket-odd', {
        params: { pick_id: pickId, pick_type: pickType },
      })
      const nova = Number(data?.odd)
      if (!nova || !Number.isFinite(nova)) return { odd: base, mudou: false, origem: null, parcial: true }
      return {
        odd: nova,
        mudou: Math.abs(nova - base) > DIFERENCA_MINIMA,
        origem: 'ticket',
        parcial: !!data?.partial,
      }
    } catch {
      return { odd: base, mudou: false, origem: null, parcial: true }
    } finally {
      setBuscando(false)
    }
  }

  return { odd, oddBilhete, buscando }
}
