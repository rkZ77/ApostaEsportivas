/*
 * A CHANCE DE UMA SELEÇÃO, e não o "bateu X/N" cru (18/10/2026, pedido do usuário).
 *
 * O caso que motivou: Zwolle x Go Ahead, escanteios +9.5, 8/8 nos últimos
 * jogos, e a bandeja mostrava "100%". A casa pagava 1.60 (~58% sem margem) e
 * o motor dava 64%. Sequência perfeita em amostra curta aparece por sorte o
 * tempo todo quando se olha centenas de linhas.
 *
 * MEDIDO EM PROD (03/09 a 17/10/2026, 23 mil linhas com odd antes do apito,
 * séries de 6 a 8 jogos, nove mercados de gols e escanteios):
 *   - "bateu 100%" acertou 65%; o preço da casa dizia 67%.
 *   - Brier: cru 0,261 · puxado pra liga (peso 40) 0,239 · preço da casa 0,229.
 *   - Puxado pro preço sem margem com peso 80: 0,2294, o mesmo do preço. O
 *     histórico curto não acrescenta nada ao preço, e o peso 80 é o que diz isso.
 *
 * Por isso a ordem: com odd dos dois lados, a base é o preço sem a margem da
 * casa (PESO_DO_PRECO); sem ela, a média da liga naquela linha (PESO_DA_LIGA);
 * sem nenhuma das duas, não há estimativa · a tela mostra só o histórico.
 *
 * A conta é Beta-Binomial: (bateu + peso × base) / (n + peso). O peso é
 * "quantos jogos a base vale". 8 jogos contra 80 do preço quer dizer que a
 * sequência mexe pouco, e é o que os números mandaram.
 */

export const PESO_DO_PRECO = 80
export const PESO_DA_LIGA = 40
/** Liga com menos jogos que isto na temporada não serve de base. */
export const MINIMO_DA_LIGA = 30

export type FonteDaChance = 'preco' | 'liga'

export interface Estimativa {
  /** 0..1 */
  chance: number
  fonte: FonteDaChance
  /** 1 / chance: a odd que empata com a chance estimada. */
  oddJusta: number
  /** chance × odd − 1, quando há odd. Negativo = a odd paga menos do que a chance vale. */
  valor: number | null
}

export function encolher(bateu: number, n: number, base: number, peso: number): number {
  return (bateu + peso * base) / (n + peso)
}

export function estimar(p: {
  bateu: number; n: number
  odd?: number | null
  /** Chance da casa sem margem (oddsDoJogo.precoSemMargem). */
  precoSemMargem?: number | null
  /** Taxa da linha nos jogos da liga e em quantos jogos ela foi contada. */
  taxaLiga?: number | null; nLiga?: number
}): Estimativa | null {
  let chance: number, fonte: FonteDaChance
  if (p.precoSemMargem != null) {
    chance = encolher(p.bateu, p.n, p.precoSemMargem, PESO_DO_PRECO)
    fonte = 'preco'
  } else if (p.taxaLiga != null && (p.nLiga ?? 0) >= MINIMO_DA_LIGA) {
    chance = encolher(p.bateu, p.n, p.taxaLiga, PESO_DA_LIGA)
    fonte = 'liga'
  } else {
    return null
  }
  chance = Math.min(Math.max(chance, 0.01), 0.99)
  return {
    chance, fonte, oddJusta: 1 / chance,
    valor: p.odd && p.odd > 1 ? chance * p.odd - 1 : null,
  }
}

/** Faixa do veredito: com valor de 5% ou mais, justa entre −5% e +5%, negativo abaixo. */
export function vereditoDoValor(valor: number | null): 'valor' | 'justa' | 'negativo' | null {
  if (valor == null) return null
  if (valor >= 0.05) return 'valor'
  if (valor > -0.05) return 'justa'
  return 'negativo'
}

export const ROTULO_DA_FONTE: Record<FonteDaChance, string> = {
  preco: 'histórico ajustado pelo preço do mercado',
  liga: 'histórico ajustado pela média da liga',
}
