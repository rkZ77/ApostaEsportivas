export interface StakeSuggestion {
  units: number
  amountR: number
  kellyPct: number
}

/**
 * Calcula stake sugerido usando Kelly fracionado.
 * Kelly = (b*p - q) / b  onde b = odd-1, p = confiança, q = 1-p
 * kellyFraction: 0.5 para picks simples (½ Kelly), 0.25 para múltiplas (¼ Kelly).
 * Resultado arredondado para o 1u mais próximo, entre 1u e maxUnits.
 */
export function suggestStake(
  confidence: number,
  odd: number,
  bankroll: number,
  unitValue: number,
  maxUnits: number = 10,
  kellyFraction: number = 0.5,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null

  const b = odd - 1
  const p = confidence
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
