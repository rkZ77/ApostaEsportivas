/*
 * O jogo de cada pick com a bola rolando (09/10/2026, pedido do usuário).
 *
 * A tela de picks junta TODOS os picks e pernas de jogo começado num pedido só
 * pra /live/picks-agora, a cada minuto, e espalha a resposta pelos cards por
 * contexto. A rota não gasta cota da API: ela só lê o cache que a varredura de
 * resultados já mantém (ver routers/live.py · leitura_ao_vivo_do_pick).
 *
 * Fora da tela de picks (Home, histórico) o contexto vem vazio e o card fica
 * como sempre foi.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import api from '../services/api'

export interface LeituraAoVivo {
  status: string
  minuto: number | null
  placar: [number | null, number | null]
  rotulo: string | null
  atual: number | null
  linha: number | null
  direcao: 'over' | 'under' | null
  situacao: 'winning' | 'losing' | 'neutral' | string
  travado: boolean
  /** 0..1 · a chance de ganhar agora; null quando o mercado não é de linha. */
  chance: number | null
  periodo: 'total' | '1t' | '2t'
  idade: number
}

export interface ItemAoVivo {
  chave: string
  fixture_id: number
  market: string
  market_type?: string | null
  line?: string | null
  prob?: number | null
  home?: string
  away?: string
  /** "2026-10-09T18:00:00" em horário de Brasília · só pra saber se já começou. */
  inicio?: string | null
}

export const PicksAgoraContext = createContext<Record<string, LeituraAoVivo>>({})

/* As chaves saem SÓ daqui: a página monta os itens com elas e o card procura
   com elas. Escritas à mão nos dois lados, uma divergência deixava o card sem
   leitura em silêncio (aconteceu na primeira versão, 09/10). */
export const chaveDoPick = (tipo: string, id: number | string) => `${tipo}:${id}`
export const chaveDaPerna = (tipo: string, id: number | string, perna: number) => `${tipo}:${id}:${perna}`

/** A leitura de um pick (ou perna), se o jogo dele está rolando. */
export function usePickAgora(chave: string | null | undefined): LeituraAoVivo | null {
  const mapa = useContext(PicksAgoraContext)
  return chave ? mapa[chave] ?? null : null
}

/** "2026-10-09T18:00:00" (Brasília, sem fuso) já passou? Na dúvida, sim. */
export function jaComecou(inicio: string | null | undefined, agora = new Date()): boolean {
  const m = inicio?.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  if (!m) return true
  // Brasília é UTC-3 o ano todo desde 2019.
  const utc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] + 3, +m[5])
  return agora.getTime() >= utc - 5 * 60_000
}

const PASSO = 60_000

/**
 * Busca e mantém a leitura dos itens. Só pede quando há item de jogo já
 * começado, e para sozinho quando a resposta vem vazia e nada mais começa.
 */
export function useFonteDePicksAgora(itens: ItemAoVivo[]): Record<string, LeituraAoVivo> {
  const [mapa, setMapa] = useState<Record<string, LeituraAoVivo>>({})
  const assinatura = useMemo(() => itens.map(i => i.chave).sort().join('|'), [itens])

  useEffect(() => {
    let vivo = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const ler = () => {
      const candidatos = itens.filter(i => jaComecou(i.inicio))
      if (!candidatos.length) {
        setMapa({})
        timer = setTimeout(ler, PASSO)
        return
      }
      const corpo = candidatos.map(({ inicio: _inicio, ...resto }) => resto)
      api.post('/live/picks-agora', { itens: corpo })
        .then(r => { if (vivo) setMapa(r.data ?? {}) })
        .catch(() => {})
        .finally(() => { if (vivo) timer = setTimeout(ler, PASSO) })
    }
    ler()
    return () => { vivo = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assinatura])

  return mapa
}

/** "59'", "Intervalo", "45+2'". */
export function rotuloDoMinuto(l: Pick<LeituraAoVivo, 'status' | 'minuto'>): string {
  if (l.status === 'HT') return 'Intervalo'
  if (l.status === 'BT') return 'Pausa'
  if (l.status === 'P') return 'Pênaltis'
  if (l.minuto == null) return 'Ao vivo'
  return `${l.minuto}'`
}

/** "1º tempo 23'", "2º tempo 59'", "Intervalo" · o lugar do horário no topo do card. */
export function rotuloDoTempo(l: Pick<LeituraAoVivo, 'status' | 'minuto'>): string {
  const min = l.minuto != null ? ` ${l.minuto}'` : ''
  if (l.status === '1H') return `1º tempo${min}`
  if (l.status === '2H') return `2º tempo${min}`
  if (l.status === 'ET') return `Prorrogação${min}`
  return rotuloDoMinuto(l)
}

/**
 * Chance do BILHETE agora: produto das pernas, cada uma com a chance ao vivo
 * quando o jogo dela está rolando, ou a de antes do jogo quando ainda não
 * começou. Perna sem número nenhum derruba a conta (null), em vez de inventar.
 */
export function chanceDoBilhete(pernas: Array<{ antes: number | null | undefined; agora: LeituraAoVivo | null }>): number | null {
  if (!pernas.some(p => p.agora?.chance != null)) return null
  let total = 1
  for (const p of pernas) {
    const c = p.agora?.chance ?? p.antes
    if (c == null) return null
    total *= Number(c)
  }
  return total
}
