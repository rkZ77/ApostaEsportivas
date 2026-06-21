/**
 * Calcula lucro/prejuízo em unidades para um pick resolvido.
 * Usa a odd real do usuário (user_actual_odd) se disponível, senão a odd do pick.
 * Usa stake_units reais do usuário (userUnits) se disponível, senão Kelly/sugestão.
 */
export function calcProfitUnits(
  result: string,
  pickOdd: number,
  units: number,
  userActualOdd?: number | null,
): number {
  const odd = userActualOdd ?? pickOdd
  switch (result) {
    case 'GREEN':     return (odd - 1) * units
    case 'RED':       return -units
    case 'PUSH':      return 0
    case 'HALF-WIN':  return ((odd - 1) * units) / 2
    case 'HALF-LOSS': return -units / 2
    default:          return 0
  }
}

export interface StakeSuggestion {
  units: number
  amountR: number
  kellyPct: number
}

/**
 * Calcula stake sugerido usando Kelly fracionado.
 * Kelly = (b*p - q) / b  onde b = odd-1, p = prob_real (Poisson), q = 1-p
 * Passar prob_real quando disponível; fallback para confidence quando não há Poisson.
 * kellyFraction: 0.5 para picks simples (½ Kelly), 0.25 para múltiplas (¼ Kelly).
 * Resultado arredondado para o 1u mais próximo, entre 1u e maxUnits.
 */
export function suggestStake(
  probReal: number,
  odd: number,
  bankroll: number,
  unitValue: number,
  maxUnits: number = 10,
  kellyFraction: number = 0.5,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null

  const b = odd - 1
  const p = probReal
  const q = 1 - p

  if (b <= 0 || p <= 0 || p >= 1) return null

  const kelly = (b * p - q) / b
  if (kelly <= 0) return null

  const fracKelly = kelly * kellyFraction
  const stakeR    = bankroll * fracKelly

  let units = stakeR / unitValue
  units = Math.max(1, Math.min(maxUnits, units))
  units = Math.round(units)

  return {
    units,
    amountR:  Math.round(units * unitValue * 100) / 100,
    kellyPct: Math.round(fracKelly * 100 * 10) / 10,
  }
}
