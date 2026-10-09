/*
 * A odd da casa pra uma seleção do Raio-X (2026-10-07).
 *
 * A rota /fixtures/<id>/odds devolve a melhor odd de cada mercado (código da
 * API-Football) e valor ("Over 9.5", "Yes") entre as casas ativas. Aqui a
 * seleção da tela vira esse par. Mercado que a coleta não traz (chutes no
 * alvo, faltas) simplesmente não tem odd · a tela mostra só o histórico.
 */
import type { Lado, Periodo } from './raioX'

export interface OddDaCasa { market_id: number; valor: string; odd: number; casa: string | null }

/** Código do mercado na API por [mercado do jogo][de quem][tempo]. */
const MERCADO_DA_API: Record<string, Partial<Record<'jogo' | 'home' | 'away', Partial<Record<Periodo, number>>>>> = {
  gols:       { jogo: { total: 5, '1t': 6, '2t': 26 }, home: { total: 16, '1t': 105, '2t': 107 }, away: { total: 17, '1t': 106, '2t': 108 } },
  escanteios: { jogo: { total: 45, '1t': 77, '2t': 127 }, home: { total: 57, '1t': 132, '2t': 133 }, away: { total: 58, '1t': 134, '2t': 135 } },
  cartoes:    { jogo: { total: 80 }, home: { total: 82 }, away: { total: 83 } },
}

/** "gols_time" e "gols" são o mesmo mercado da API, separados por "de quem". */
const BASE: Record<string, string> = {
  gols: 'gols', gols_time: 'gols', escanteios: 'escanteios', escanteios_time: 'escanteios',
  cartoes: 'cartoes', cartoes_time: 'cartoes',
}

const fmtLinha = (l: number) => (Number.isInteger(l) ? l.toFixed(1) : String(l))

/** Resultado final (Match Winner, 1) e chance dupla (Double Chance, 12) · [mercado, valor]. */
const RESULTADO_DA_API: Record<string, [number, string]> = {
  '1': [1, 'home'], X: [1, 'draw'], '2': [1, 'away'],
  '1X': [12, 'home/draw'], '12': [12, 'home/away'], X2: [12, 'draw/away'],
}

export function oddDaSelecao(
  odds: OddDaCasa[] | null | undefined,
  sel: { mercado: string; quem: 'jogo' | 'home' | 'away'; periodo: Periodo; lado?: Lado; linha?: number; escolha?: string },
): OddDaCasa | null {
  if (!odds?.length) return null
  if (sel.mercado === 'resultado') {
    const alvo = sel.escolha ? RESULTADO_DA_API[sel.escolha] : undefined
    if (!alvo) return null
    return odds.find(o => o.market_id === alvo[0] && o.valor.replace(/\s/g, '').toLowerCase() === alvo[1]) ?? null
  }
  if (sel.mercado === 'btts') {
    const id = sel.periodo === '1t' ? 34 : sel.periodo === '2t' ? 35 : 8
    return odds.find(o => o.market_id === id && o.valor.toLowerCase() === 'yes') ?? null
  }
  const base = BASE[sel.mercado]
  const id = base ? MERCADO_DA_API[base]?.[sel.quem]?.[sel.periodo] : undefined
  if (id == null || sel.linha == null || !sel.lado) return null
  const alvo = `${sel.lado === 'mais' ? 'over' : 'under'} ${fmtLinha(sel.linha)}`
  return odds.find(o => o.market_id === id && o.valor.trim().toLowerCase() === alvo) ?? null
}

/**
 * Chance de vitória, empate e derrota pelas odds do resultado final (09/10).
 *
 * 1/odd de cada lado soma mais de 100% (é a margem da casa); dividir pelo
 * total tira a margem e deixa os três somando 100. As odds são as MELHORES de
 * cada lado, às vezes de casas diferentes, então a soma fica perto de 100 e a
 * correção é pequena. null se faltar qualquer um dos três.
 */
export function chanceDoResultado(odds: OddDaCasa[] | null | undefined): { casa: number; empate: number; fora: number } | null {
  const o = (escolha: string) => oddDaSelecao(odds, { mercado: 'resultado', quem: 'jogo', periodo: 'total', escolha })?.odd
  const [c, e, f] = [o('1'), o('X'), o('2')]
  if (!c || !e || !f) return null
  const soma = 1 / c + 1 / e + 1 / f
  return { casa: 1 / c / soma, empate: 1 / e / soma, fora: 1 / f / soma }
}

/**
 * Vantagem pela taxa histórica: chance × odd − 1. Só com amostra de 8 jogos
 * ou mais · com menos, 4/4 viraria "valor" em cima de quatro jogos.
 */
export function vantagem(bateu: number, n: number, odd: number | null | undefined): number | null {
  if (!odd || n < 8) return null
  return (bateu / n) * odd - 1
}
